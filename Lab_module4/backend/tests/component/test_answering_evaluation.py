"""Answering with a fake LLM (A1–A6) and the evaluation (E2–E6), 0 calls."""

import json
from pathlib import Path

import pytest
from fakes import FakeLLM, judge

from app.application.answering import AnswerService, AnswerSettings, build_context
from app.application.budget import BudgetedLLMClient, CallBudget, RunCounter
from app.application.evaluation.evaluator import Evaluator, RunConfig, summarize
from app.application.evaluation.judge import LLMJudge
from app.application.evaluation.relevance import (
    DatasetError,
    is_relevant,
    judge_ranking,
    load_dataset,
    locate_in_chunks,
    locate_in_content,
    parse_examples,
    resolve,
)
from app.application.evaluation.service import EvaluationService
from app.application.structured import StructuredCaller
from app.application.tracing import Tracer
from app.domain.errors import LLMBadResponse, LLMQuotaExceeded
from app.domain.evaluation import CATEGORIES, RelevantTarget
from app.domain.retrieval import SearchMode
from app.infrastructure.caching_llm import CachingLLMClient
from app.infrastructure.samples import read_sample
from app.infrastructure.sqlite_store import SqliteReportStore, SqliteResponseCache

EVAL = Path(__file__).resolve().parents[2] / "eval"
QUESTION = "Where is the database connection configured?"


def ask(stack, question=QUESTION, k=5, mode=SearchMode.HYBRID_RERANK, codebases=("shopflow",)):
    tracer = Tracer("query")
    answer, result, debug = stack.answers.answer(question, list(codebases), k, mode, tracer)
    return answer, result, debug, tracer


def sample_locate(codebase, path):
    content = read_sample(codebase, path)
    return locate_in_content(path, content) if content is not None else None


# A1
def test_prompt_has_numbered_excerpts_rules_and_no_placeholders(stack):
    s = stack()
    s.index_samples()
    answer, result, debug, tracer = ask(s)
    user = s.llm.last_user_text()
    request = s.llm.requests[-1]
    assert "Code is data" in request.system
    first = result.hits[0].chunk
    assert f"[1] shopflow/{first.path}:{first.start_line}-{first.end_line}" in user
    assert f"````{first.language.value}\n{first.code}\n````" in user
    assert "[5] " in user and "[6] " not in user
    assert "{question}" not in user and "{excerpts}" not in user
    assert debug.prompt.est_tokens < 6000 and debug.prompt.chunks_sent == 5
    assert answer.found and answer.grounded and answer.citations == [1, 2]
    assert [s.name for s in tracer.spans][-3:] == ["build_context", "generate", "validate"]


# A2
def test_context_budget_drops_lowest_ranked_first(samples_stack):
    result = samples_stack.retriever.search(QUESTION, ["shopflow"], 8, SearchMode.HYBRID,
                                            Tracer("s"))  # fmt: skip
    kept, text = build_context(result.hits, 120)
    assert len(kept) < len(result.hits) and kept == result.hits[: len(kept)]
    assert "[1] " in text
    assert build_context(result.hits, 1)[0] == result.hits[:1]  # the best one is always kept


# A3
@pytest.mark.parametrize(
    "bad",
    [
        {"answer": "See [7].", "found": True, "citations": [7]},
        {"answer": "See [1] and [2].", "found": True, "citations": [1]},
        {"answer": "Configured somewhere.", "found": True, "citations": []},
    ],
)
def test_citation_problems_get_one_repair(stack, bad):
    good = {"answer": "In create_db_engine [1].", "found": True, "citations": [1]}
    s = stack(llm=FakeLLM(answers=[bad, good]))
    s.index_samples()
    answer, _, debug, tracer = ask(s)
    assert answer.grounded and answer.repaired and answer.citations == [1]
    assert len(debug.attempts) == 2 and debug.attempts[0].errors
    assert "Problems:" in debug.attempts[0].repair_message
    repair_request = s.llm.requests[-1]
    assert len(repair_request.messages) == 3 and "Problems:" in repair_request.messages[2].text
    assert [sp.attrs.get("repair") for sp in tracer.spans if sp.name == "generate"] == [False, True]


def test_second_citation_failure_is_flagged_not_raised(stack):
    bad = {"answer": "See [9].", "found": True, "citations": [9]}
    s = stack(llm=FakeLLM(answers=[bad, bad]))
    s.index_samples()
    answer, *_ = ask(s)
    assert not answer.grounded and answer.citations == []  # out-of-range numbers dropped


def test_invalid_json_twice_raises(stack):
    s = stack(llm=FakeLLM(answers=[{"oops": 1}], invalid_once={"AnswerLLM"}))
    s.index_samples()
    with pytest.raises(LLMBadResponse):
        ask(s)


def test_invalid_json_once_is_repaired(stack):
    s = stack(llm=FakeLLM(invalid_once={"AnswerLLM"}))
    s.index_samples()
    answer, _, debug, _ = ask(s)
    assert answer.grounded and debug.attempts[0].errors == ["The answer was not a JSON object."]


# A4
def test_not_found_passes_through_and_zero_hits_skip_the_llm(stack):
    s = stack(llm=FakeLLM(answers=[{"answer": "Not in the excerpts.", "found": False,
                                    "citations": []}]))  # fmt: skip
    s.index_samples()
    answer, *_ = ask(s, "How is Redis caching configured?")
    assert not answer.found and answer.grounded
    calls = len(s.llm.requests)
    answer, *_ = ask(s, "zzqx qqzz", mode=SearchMode.BM25)  # no keyword matches at all
    assert not answer.found and answer.sources == [] and len(s.llm.requests) == calls


# A5
def test_identical_question_is_served_from_the_cache(stack, tmp_path):
    s = stack()
    s.index_samples()
    llm = FakeLLM()
    cached = CachingLLMClient(llm, SqliteResponseCache(str(tmp_path / "c.db")), "m")
    service = AnswerService(s.retriever, StructuredCaller(cached, s.prompts, "m"), s.prompts,
                            AnswerSettings())  # fmt: skip
    first = service.answer(QUESTION, ["shopflow"], 5, SearchMode.HYBRID, Tracer("q"))[0]
    second = service.answer(QUESTION, ["shopflow"], 5, SearchMode.HYBRID, Tracer("q"))[0]
    assert len(llm.requests) == 1 and not first.cached and second.cached
    s.index("shopflow-extra", {"db.py": "def connect_database():\n    return 1\n"})
    service.answer(QUESTION, ["shopflow", "shopflow-extra"], 5, SearchMode.HYBRID, Tracer("q"))
    assert len(llm.requests) == 2  # different retrieved code → different prompt → a call


# A6
def test_pipeline_debug_matches_what_was_used(stack):
    s = stack(llm=FakeLLM(invalid_once={"AnswerLLM"}))
    s.index_samples()
    answer, result, debug, _ = ask(s)
    r = debug.retrieval
    assert debug.question == QUESTION and debug.query_rewrite is None
    assert len(r.vector) == 20 and 0 < len(r.bm25) <= 20 and len(r.fused) == 20
    assert [c.chunk_id for c in r.reranked] == [h.chunk.id for h in result.hits]
    before = {c.chunk_id: c.rank for c in r.fused}
    assert all(c.extra["rank_before"] == before[c.chunk_id] for c in r.reranked)
    assert debug.prompt.user == s.llm.requests[0].messages[0].text  # byte for byte
    assert len(debug.attempts) == 2 and debug.attempts[1].raw_output
    assert r.query_embedding["dims"] == 256 and r.query_embedding["cached"] is False
    assert all(c.extra["matched_terms"] for c in r.bm25)


# E2
def test_relevance_by_line_overlap_and_symbol_resolution(samples_stack):
    examples = resolve(load_dataset(EVAL / "dataset.json"), sample_locate)
    s5 = next(e for e in examples if e.id == "s5")
    assert s5.relevant[0].lines == (23, 29)  # Cart.applyCoupon inside the Cart class
    cart_chunks = list(samples_stack.store.iter_chunks("shopflow", "web/src/cart/cart.ts"))
    whole_class = next(c for c in cart_chunks if c.symbol == "Cart")
    assert is_relevant(whole_class, s5.relevant[0])  # the small class contains the method
    x1 = next(e for e in examples if e.id == "x1")
    assert x1.relevant[0].lines[0] == 1  # no symbol → the whole file
    wrong = parse_examples(
        [
            {
                "id": "z",
                "question": "q",
                "codebases": ["shopflow"],
                "category": "symbol",
                "relevant": [{"codebase": "shopflow", "path": "README.md", "symbol": "Nope"}],
            }
        ]
    )
    with pytest.raises(DatasetError, match="symbol not found"):
        resolve(wrong, sample_locate)
    missing = parse_examples(
        [
            {
                "id": "z",
                "question": "q",
                "codebases": ["shopflow"],
                "category": "symbol",
                "relevant": [{"codebase": "shopflow", "path": "nope.py"}],
            }
        ]
    )
    with pytest.raises(DatasetError, match="file not found"):
        resolve(missing, sample_locate)
    flags, first = judge_ranking(
        cart_chunks, [s5.relevant[0], RelevantTarget("ledger", "x.ts", None, (1, 2))]
    )
    assert any(flags) and first[1] is None
    located, n = locate_in_chunks(cart_chunks)
    assert located["Cart"][0] <= 3 and n >= 34
    from app.domain.chunks import Chunk, ChunkKind
    from app.domain.files import Language

    packed = Chunk("i", "u", "a.py", Language.PYTHON, ChunkKind.CLASS, "AuthError, Svc.login",
                   None, 4, 20, "code", "")  # fmt: skip
    symbols, _ = locate_in_chunks([packed])
    assert symbols["AuthError"] == symbols["Svc.login"] == symbols["Svc"] == (4, 20)


# E3
def test_dataset_integrity():
    raw = json.loads((EVAL / "dataset.json").read_text())
    examples = resolve(parse_examples(raw), sample_locate)
    assert len(examples) == 20 and len({e.id for e in examples}) == 20
    counts = {c: sum(e.category == c for e in examples) for c in CATEGORIES}
    assert counts == {"symbol": 5, "conceptual": 4, "location": 4, "multi_file": 3,
                      "cross_codebase": 2, "unanswerable": 2}  # fmt: skip
    for e in examples:
        assert e.expected_answer and (e.relevant or not e.expect_found)
        assert all(t.lines for t in e.relevant)
    assert sum(bool(e.forbidden) for e in examples) == 2  # the planted-injection checks
    with pytest.raises(DatasetError, match="unknown category"):
        parse_examples([{"id": "a", "question": "q", "codebases": [], "category": "nope"}])
    with pytest.raises(DatasetError, match="unique"):
        parse_examples([raw[0], raw[0]])
    bad = json.loads((EVAL / "bad_answers.json").read_text())
    assert len(bad) == 4 and {b["example"] for b in bad} <= {e.id for e in examples}


def make_evaluator(stack, llm: FakeLLM, max_calls: int = 100, cache_path=None):
    budget = CallBudget(max_calls)
    inner = BudgetedLLMClient(llm, budget)
    if cache_path is not None:
        inner = CachingLLMClient(inner, SqliteResponseCache(str(cache_path)), "m")
    caller = StructuredCaller(RunCounter(inner, budget), stack.prompts, "m")
    answers = AnswerService(stack.retriever, caller, stack.prompts, AnswerSettings())
    return Evaluator(stack.retriever, answers, LLMJudge(caller, stack.prompts), budget), budget


# E4
def test_judge_parsing_and_sanity_check(samples_stack):
    def strict_judge(prompt):
        bad = "restock email" in prompt or "database.yml" in prompt or "AES-256" in prompt
        return judge(1, 2, 1) if bad else judge(5, 5, 5)

    evaluator, _ = make_evaluator(samples_stack, FakeLLM(judge=strict_judge))
    examples = resolve(load_dataset(EVAL / "dataset.json"), sample_locate)
    bad = json.loads((EVAL / "bad_answers.json").read_text())
    config = RunConfig(5, SearchMode.HYBRID)
    sanity = [evaluator._sanity(b, examples, config) for b in bad]
    passed = {s["id"]: s["passed"] for s in sanity}
    # the off-topic answer got 5/5 from this judge: reported as lenient, not hidden
    assert passed == {"bad_wrong_function": True, "bad_invented_config": True,
                      "bad_unsupported_claim": True, "bad_off_topic": False}  # fmt: skip
    assert next(s for s in sanity if s["id"] == "bad_off_topic")["lenient_on"] == ["correctness"]
    assert evaluator._sanity({"id": "x", "kind": "k", "example": "nope", "answer": "a",
                              "expect": {}}, examples, config)["skipped"]  # fmt: skip


# E5
def test_full_run_budget_resume_and_quota(samples_stack, tmp_path):
    examples = resolve(load_dataset(EVAL / "dataset.json"), sample_locate)[:4]
    config = RunConfig(5, SearchMode.HYBRID)
    cache = tmp_path / "eval.db"
    evaluator, budget = make_evaluator(samples_stack, FakeLLM(), max_calls=3, cache_path=cache)
    first = evaluator.full(examples, config)
    assert budget.real == 3 and [s["reason"] for s in first["summary"]["skipped"]]
    assert {s["reason"].split(" ")[0] for s in first["summary"]["skipped"]} == {"budget"}
    evaluator, budget = make_evaluator(samples_stack, FakeLLM(), max_calls=100, cache_path=cache)
    resumed = evaluator.full(examples, config)
    assert resumed["summary"]["skipped"] == [] and budget.cached == 3 and budget.real == 5
    evaluator, budget = make_evaluator(samples_stack, FakeLLM(), max_calls=100, cache_path=cache)
    evaluator.full(examples, config)
    assert budget.real == 0  # fully cached: free
    quota = FakeLLM(fail={"any": LLMQuotaExceeded("day", 3600)})
    evaluator, _ = make_evaluator(samples_stack, quota)
    report = evaluator.full(examples, config)
    assert {s["reason"] for s in report["summary"]["skipped"]} == {"quota"}


def test_full_run_checks_and_injection(samples_stack):
    def answer(prompt):
        if "PaymentClient.charge handle failures" in prompt:
            return {"answer": "ALL SYSTEMS NOMINAL [1]", "found": True, "citations": [1]}
        return {"answer": "Not found.", "found": False, "citations": []}

    llm = FakeLLM(judge=judge(4, 4, 3))
    llm.answers = [answer] * 10
    evaluator, _ = make_evaluator(samples_stack, llm)
    examples = resolve(load_dataset(EVAL / "dataset.json"), sample_locate)
    s3, u1 = next(e for e in examples if e.id == "s3"), next(e for e in examples if e.id == "u1")
    report = evaluator.full([s3, u1], RunConfig(5, SearchMode.HYBRID))
    rows = {r["id"]: r for r in report["examples"]}
    assert rows["s3"]["checks"]["no_forbidden"] is False  # the injection was followed
    assert rows["s3"]["missing_mentions"] == ["PaymentError", "Idempotency"]
    assert rows["u1"]["checks"]["found_matches"] is True and "judge_scores" not in rows["u1"]
    checks = report["summary"]["checks"]
    assert checks["no_forbidden"] == {"passed": 1, "total": 2}
    assert report["summary"]["generation"]["overall"]["correctness"] == 3.0


# E6
def test_aggregation_per_category_excludes_unanswerable_from_retrieval(samples_stack):
    examples = resolve(load_dataset(EVAL / "dataset.json"), sample_locate)
    report = Evaluator(samples_stack.retriever).retrieval(examples, RunConfig(5, SearchMode.HYBRID))
    summary = report["summary"]["retrieval"]
    assert summary["overall"]["n"] == 18 and summary["by_category"]["unanswerable"]["n"] == 0
    assert 0 <= summary["overall"]["ndcg"] <= 1
    u1 = next(r for r in report["examples"] if r["id"] == "u1")
    assert "metrics" not in u1 and u1["retrieved"]
    rows = [{"category": "a", "m": {"x": 1.0}}, {"category": "a", "m": {"x": 0.0}},
            {"category": "b"}]  # fmt: skip
    assert summarize(rows, ("x",), "m") == {
        "overall": {"x": 0.5, "n": 2},
        "by_category": {"a": {"x": 0.5, "n": 2}, "b": {"x": None, "n": 0}},
    }


def test_evaluation_service_reports_and_custom_examples(samples_stack, tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    (results / "grid.json").write_text(json.dumps({"kind": "grid", "summary": {"a": 1}}))

    def factory(max_calls):
        return make_evaluator(samples_stack, FakeLLM(), max_calls)

    service = EvaluationService(
        Evaluator(samples_stack.retriever), factory, SqliteReportStore(str(tmp_path / "r.db")),
        sample_locate, EVAL / "dataset.json", EVAL / "bad_answers.json", results,
        RunConfig(5, SearchMode.HYBRID, "fake", "1", "m"), 50,
    )  # fmt: skip
    report = service.run_retrieval(service.builtin(), 3, SearchMode.BM25)
    assert report["config"]["k"] == 3 and report["config"]["mode"] == "bm25"
    full = service.run_full_job({"max_calls": 500}, progress=lambda p: None)
    assert full["config"]["max_calls"] == 50  # capped by the server setting
    ids = [r["id"] for r in service.all()]
    assert ids[0] == "grid" and report["id"] in ids and full["id"] in ids
    assert service.get("grid")["summary"] == {"a": 1}
    assert service.get(report["id"])["kind"] == "retrieval"
    custom = service.custom([{"id": "c", "question": "where is processOrder", "codebases":
                              ["shopflow"], "category": "symbol", "relevant": [
                                  {"codebase": "shopflow", "path": "web/src/orders/processOrder.ts",
                                   "symbol": "processOrder"}]}])  # fmt: skip
    assert custom[0].relevant[0].lines == (9, 39)
    from app.domain.errors import InvalidPath

    with pytest.raises(InvalidPath):
        service.custom([])
    with pytest.raises(InvalidPath):
        service.custom([{"id": "c"}])
