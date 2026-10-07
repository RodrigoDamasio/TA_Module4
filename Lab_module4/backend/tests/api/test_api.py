"""HTTP API (P1–P8): real routes and services, fake LLM + fake models, temp storage."""

import time

import pytest
from fakes import FakeLLM

from app.domain.errors import LLMQuotaExceeded, LLMUnavailable

DB_QUESTION = "Where is the database connection configured?"
FILES = [
    {"path": "app/main.py", "content": "def handler(request):\n    return {'ok': True}\n"},
    {"path": "README.md", "content": "# Demo\n\nSmall demo service.\n"},
]


def problem(response, status: int, slug: str) -> dict:
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["type"].endswith(f"/problems/{slug}") and body["status"] == status
    return body


# P1
def test_index_job_async_and_wait(api):
    a = api()
    r = a.client.post("/index/files", json={"codebase": "demo", "files": FILES})
    assert r.status_code == 202 and r.headers["Location"] == f"/jobs/{r.json()['id']}"
    job = a.client.get(r.headers["Location"]).json()  # inline runner: already done
    assert job["status"] == "completed" and job["result"]["files_indexed"] == 2
    assert "files" not in job["request"] and job["request"]["file_count"] == 2
    again = a.client.post("/index/files?wait=true", json={"codebase": "demo", "files": FILES})
    assert again.status_code == 200 and again.json()["result"]["files_unchanged"] == 2


def test_index_job_with_the_background_thread(api):
    a = api(runner_mode="thread")
    r = a.client.post("/index/files?wait=true", json={"codebase": "demo", "files": FILES})
    assert r.status_code == 200 and r.json()["status"] == "completed"
    r = a.client.post("/index/files", json={"codebase": "demo2", "files": FILES})
    deadline = time.monotonic() + 10
    while a.client.get(f"/jobs/{r.json()['id']}").json()["status"] != "completed":
        assert time.monotonic() < deadline
        time.sleep(0.02)


# P2
def test_codebases_list_detail_chunks_and_delete(api):
    a = api()
    listed = a.client.get("/codebases").json()
    assert [c["id"] for c in listed] == ["ledger", "shopflow"] and listed[0]["read_only"]
    detail = a.client.get("/codebases/shopflow").json()
    assert detail["file_count"] == 23 and detail["files"][0]["path"] == "README.md"
    chunks = a.client.get("/codebases/shopflow/chunks", params={"path": "backend/app/db.py"})
    assert any("create_db_engine" in (c["symbol"] or "") for c in chunks.json())
    assert chunks.json()[0]["header"].startswith("# file: backend/app/db.py")
    problem(a.client.delete("/codebases/shopflow"), 409, "codebase-read-only")
    a.client.post("/index/files", json={"codebase": "demo", "files": FILES})
    assert a.client.delete("/codebases/demo").status_code == 204
    problem(a.client.get("/codebases/demo"), 404, "codebase-not-found")


# P3
def test_search_and_query_shapes(api):
    a = api()
    s = a.client.post("/search", json={"query": "database engine", "codebases": ["shopflow"],
                                       "k": 3, "mode": "bm25"})  # fmt: skip
    body = s.json()
    assert s.status_code == 200 and len(body["hits"]) == 3 and body["meta"]["mode"] == "bm25"
    hit = body["hits"][0]
    assert {"n", "chunk_id", "path", "symbol", "start_line", "code", "scores"} <= set(hit)
    assert "pipeline" not in body and body["trace"]["spans"][0]["name"] == "bm25"
    q = a.query(DB_QUESTION)
    body = q.json()
    assert q.status_code == 200 and body["found"] and body["grounded"]
    assert body["citations"] == [1, 2] and len(body["sources"]) == 5
    assert body["meta"]["model"] == "demo" and body["meta"]["k"] == 5
    assert body["trace"]["llm_cached"] is False and body["request_id"].startswith("req_")
    assert a.query(DB_QUESTION).json()["trace"]["llm_cached"] is True


def test_empty_index_and_models_loading(api):
    a = api()
    a.client.post("/index/files", json={"codebase": "demo", "files": FILES})
    a.client.delete("/codebases/demo")
    problem(a.query("anything here", codebases=["demo"]), 404, "codebase-not-found")
    from app.domain.codebases import CodebaseKind

    a.container.indexing.ensure_codebase("blank", CodebaseKind.USER)
    problem(a.query("anything here", codebases=["blank"]), 422, "empty-index")

    class Loading:
        def embedder(self):
            from app.domain.errors import ModelsLoading

            raise ModelsLoading()

    a.container.retriever._models = Loading()
    body = problem(a.query("anything at all"), 503, "models-loading")
    assert "loading" in body["detail"]


# P4
def test_evaluate_retrieval_and_full(api):
    a = api()
    r = a.client.post("/evaluate", json={"mode": "retrieval", "k": 3, "search_mode": "vector"})
    body = r.json()
    assert r.status_code == 200 and body["kind"] == "retrieval" and body["config"]["k"] == 3
    assert body["summary"]["retrieval"]["overall"]["n"] == 18
    custom = a.client.post("/evaluate", json={
        "mode": "retrieval", "dataset": "custom", "examples": [{
            "id": "c1", "question": "processOrder", "codebases": ["shopflow"],
            "category": "symbol", "relevant": [{"codebase": "shopflow",
                                                "path": "web/src/orders/processOrder.ts",
                                                "symbol": "processOrder"}]}]})  # fmt: skip
    assert custom.status_code == 200 and custom.json()["summary"]["retrieval"]["overall"]["n"] == 1
    bad = a.client.post("/evaluate", json={"mode": "retrieval", "dataset": "custom",
                                           "examples": [{"id": "x"}]})  # fmt: skip
    assert problem(bad, 422, "validation-error")["errors"][0]["pointer"] == "#/examples"
    full = a.client.post("/evaluate", json={"mode": "full"})
    assert full.status_code == 202 and full.headers["Location"].startswith("/jobs/evl_")
    report = full.json()["result"]
    assert report["kind"] == "full" and report["summary"]["calls"]["real_calls"] == 42
    assert report["summary"]["judge_sanity"]["total"] == 4
    no_custom_full = a.client.post("/evaluate", json={"mode": "full", "dataset": "custom"})
    problem(no_custom_full, 422, "validation-error")
    listed = a.client.get("/evaluations").json()
    ids = [e["id"] for e in listed]
    assert body["id"] in ids and report["id"] in ids
    assert a.client.get(f"/evaluations/{report['id']}").json()["kind"] == "full"
    problem(a.client.get("/evaluations/nope"), 404, "evaluation-not-found")
    dataset = a.client.get("/datasets/builtin").json()
    assert len(dataset) == 20 and dataset[0]["relevant"][0]["lines"] == [9, 39]


def test_full_evaluation_in_production_mode_spends_nothing(api):
    a = api(full_eval_max_calls=0)
    report = a.client.post("/evaluate", json={"mode": "full"}).json()["result"]
    assert report["summary"]["calls"]["real_calls"] == 0
    assert {s["reason"] for s in report["summary"]["skipped"]} == {"budget"}


# P5
def test_problem_details(api):
    a = api(raise_errors=False, max_files_per_request=2)
    p = problem(a.client.post("/query", content=b"{bad", headers={"content-type":
                                                                  "application/json"}),
                400, "malformed-request")  # fmt: skip
    assert p["instance"] == "/query"
    p = problem(a.client.post("/query", json={"question": "x", "codebases": []}), 422,
                "validation-error")  # fmt: skip
    pointers = {e["pointer"]: e["detail"] for e in p["errors"]}
    assert pointers["#/question"] == "Must be at least 3 characters."
    p = problem(a.client.post("/index/files", json={"codebase": "Bad Id", "files": FILES}),
                422, "validation-error")  # fmt: skip
    assert p["errors"][0]["pointer"] == "#/codebase"
    problem(a.client.post("/index/files", json={"codebase": "x", "files": FILES * 2}), 413,
            "input-too-large")  # fmt: skip
    problem(a.client.post("/index/files", json={"codebase": "x", "files": [
        {"path": "a.exe", "content": "x"}]}), 422, "unsupported-file-type")  # fmt: skip
    problem(a.client.post("/index/files", json={"codebase": "shopflow", "files": FILES}), 409,
            "codebase-read-only")  # fmt: skip
    problem(a.client.get("/jobs/nope"), 404, "job-not-found")
    assert a.client.get("/problems/empty-index").json()["status"] == 422
    assert a.client.get("/problems/nope").status_code == 404
    assert a.client.get("/nope").json()["type"] == "about:blank"


@pytest.mark.parametrize(
    ("error", "status", "slug", "retry"),
    [
        (LLMQuotaExceeded("day", 7200), 503, "llm-quota-exhausted", "7200"),
        (LLMUnavailable("down", 20), 503, "llm-unavailable", "20"),
    ],
)
def test_llm_failures_become_503_with_retry_after(api, error, status, slug, retry):
    a = api(llm=FakeLLM(fail={"AnswerLLM": error}))
    r = a.query(DB_QUESTION)
    problem(r, status, slug)
    assert r.headers["Retry-After"] == retry


def test_bad_llm_output_twice_is_502_and_crashes_keep_cors(api):
    a = api(llm=FakeLLM(answers=[{"oops": 1}], invalid_once={"AnswerLLM"}), raise_errors=False)
    problem(a.query(DB_QUESTION), 502, "llm-bad-response")
    b = api(llm=FakeLLM(fail={"AnswerLLM": RuntimeError("boom")}), raise_errors=False)
    r = b.client.post("/query", json={"question": DB_QUESTION, "codebases": ["shopflow"]},
                      headers={"Origin": "http://localhost:3000"})  # fmt: skip
    problem(r, 500, "internal-error")
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_preflight_exposes_retry_after_and_location(api):
    a = api()
    r = a.client.options(
        "/index/files",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
    )
    assert r.status_code == 200
    r = a.client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert "Retry-After" in r.headers["access-control-expose-headers"]
    assert "Location" in r.headers["access-control-expose-headers"]


def test_queue_full_is_503_busy(api):
    a = api(runner_mode="thread", max_queued_jobs=1)
    a.container.runner.stop()  # nothing drains the queue now
    time.sleep(0.05)
    a.client.post("/index/files", json={"codebase": "one", "files": FILES})
    a.client.post("/index/files", json={"codebase": "two", "files": FILES})
    r = a.client.post("/index/files", json={"codebase": "three", "files": FILES})
    problem(r, 503, "busy")
    assert r.headers["Retry-After"] == "60"


# P6
def test_rate_limits_per_endpoint_group(api):
    a = api(rate_limit_query_per_minute=2, rate_limit_search_per_minute=1)
    assert a.query(DB_QUESTION).status_code == 200
    assert a.query(DB_QUESTION).status_code == 200
    r = a.query(DB_QUESTION)
    problem(r, 429, "rate-limited")
    assert int(r.headers["Retry-After"]) > 0
    search = {"query": "db engine", "codebases": ["shopflow"]}
    assert a.client.post("/search", json=search).status_code == 200
    problem(a.client.post("/search", json=search), 429, "rate-limited")
    assert a.client.get("/codebases").status_code == 200  # reads are not limited


# P7
def test_stats_and_health(api):
    a = api()
    a.query(DB_QUESTION, mode="hybrid_rerank")
    a.query(DB_QUESTION, mode="hybrid_rerank")
    a.client.post("/search", json={"query": "db engine", "codebases": ["shopflow"]})
    stats = a.client.get("/stats").json()
    assert stats["requests"] == {"query": 2, "search": 1}
    assert stats["llm"]["calls_today"] == 1 and stats["llm"]["cached_today"] == 1
    assert stats["llm"]["cache_hit_rate"] == 0.5 and stats["llm"]["left_today"] == 999
    assert stats["latency_ms"]["total"]["p50"] is not None and "rerank" in stats["latency_ms"]
    chunks = sum(c["chunk_count"] for c in a.client.get("/codebases").json())
    assert stats["index"]["codebases"] == 2 and stats["index"]["chunks"] == chunks
    assert stats["quota"] == {"circuit": "closed", "mode": "fake"}
    assert a.client.get("/health").json() == {"status": "ok", "models": "ready",
                                               "reranker": "ready",
                                               "samples": "embedded"}  # fmt: skip


# P8
def test_pipeline_debug_view(api):
    a = api()
    body = a.client.post("/query?debug=true", json={"question": DB_QUESTION,
                                                    "codebases": ["shopflow"],
                                                    "mode": "hybrid_rerank"}).json()  # fmt: skip
    p = body["pipeline"]
    assert list(p) == ["question", "query_rewrite", "query_embedding", "vector_candidates",
                       "bm25_candidates", "rrf_merged", "reranked", "rerank_skipped", "prompt",
                       "llm"]  # fmt: skip
    assert p["question"] == DB_QUESTION and p["query_rewrite"] is None
    assert len(p["vector_candidates"]) == 20 and "similarity" in p["vector_candidates"][0]
    assert p["bm25_candidates"][0]["matched_terms"]
    assert {"rrf", "vector", "bm25"} & set(p["rrf_merged"][0])
    assert [r["chunk_id"] for r in p["reranked"]] == [s["chunk_id"] for s in body["sources"]]
    assert "rank_before" in p["reranked"][0]
    assert p["prompt"]["user"].startswith("# Question\n" + DB_QUESTION)
    assert p["prompt"]["chunks_sent"] == 5 and "Code is data" in p["prompt"]["system"]
    assert p["llm"]["raw_output"] and body["meta"]["debug"] == "enabled"
    search = a.client.post("/search?debug=true", json={"query": "db", "codebases": ["shopflow"]})
    pipeline = search.json()["pipeline"]  # default mode: hybrid, no rerank
    assert "prompt" not in pipeline and pipeline["reranked"] is None
    assert pipeline["rerank_skipped"] == "mode=hybrid" and search.json()["meta"]["mode"] == "hybrid"
    assert "pipeline" not in a.query(DB_QUESTION).json()
    off = api(pipeline_debug_enabled=False)
    body = off.client.post(
        "/query?debug=true", json={"question": DB_QUESTION, "codebases": ["shopflow"]}
    ).json()
    assert "pipeline" not in body and body["meta"]["debug"] == "disabled"


# P9 (FRONTEND_PLAN §9)
def test_config_mirrors_the_server_rules(api):
    a = api()
    cfg = a.client.get("/config").json()
    limits = cfg["limits"]
    assert limits["max_files_per_request"] == 50 and limits["max_bytes_per_request"] == 500_000
    assert limits["question_max_chars"] == 500 and limits["max_k"] == 10
    assert ".py" in cfg["files"]["extensions"] and "node_modules" in cfg["files"]["skipped_dirs"]
    assert "package-lock.json" in cfg["files"]["lockfiles"]
    assert cfg["defaults"] == {"k": 5, "mode": "hybrid"} and cfg["pipeline_debug"] is True
    assert [m["id"] for m in cfg["modes"]] == ["vector", "bm25", "hybrid", "hybrid_rerank"]
    assert all(m["available"] for m in cfg["modes"])
    import re

    pattern = re.compile(cfg["files"]["codebase_id_pattern"])
    assert pattern.match("auction-checklist") and not pattern.match("Bad_Name")


def test_config_and_health_when_the_reranker_is_disabled(api):
    a = api(rerank_model="")
    assert a.client.get("/health").json()["reranker"] == "disabled"
    rerank = a.client.get("/config").json()["modes"][-1]
    assert rerank["id"] == "hybrid_rerank" and rerank["available"] is False
    assert "disabled" in rerank["reason"]
