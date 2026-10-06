"""EvaluationService: the built-in dataset, retrieval runs (synchronous, 0 calls), full
runs (background job, call budget), and stored reports (runs + published results)."""

import json
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.domain.errors import InvalidPath
from app.domain.evaluation import EvalExample
from app.domain.ports import ReportStore
from app.domain.retrieval import SearchMode

from ..budget import CallBudget
from .evaluator import Evaluator, RunConfig
from .relevance import DatasetError, Located, load_dataset, parse_examples, resolve

EvaluatorFactory = Callable[[int], tuple[Evaluator, CallBudget]]
MAX_CUSTOM_EXAMPLES = 30


class EvaluationService:
    def __init__(
        self,
        retrieval_evaluator: Evaluator,
        full_evaluator: EvaluatorFactory,
        reports: ReportStore,
        locate: Callable[[str, str], Located | None],
        dataset_path: Path,
        bad_answers_path: Path,
        results_dir: Path,
        base_config: RunConfig,
        full_max_calls: int,
    ) -> None:
        self._retrieval = retrieval_evaluator
        self._full = full_evaluator
        self._reports, self._locate = reports, locate
        self._dataset_path, self._bad_path, self._results = (
            dataset_path,
            bad_answers_path,
            results_dir,
        )
        self._base, self._max_calls = base_config, full_max_calls
        self._builtin: list[EvalExample] | None = None

    # ---- dataset ---------------------------------------------------------------------

    def builtin(self) -> list[EvalExample]:
        if self._builtin is None:
            self._builtin = resolve(load_dataset(self._dataset_path), self._locate)
        return self._builtin

    def bad_answers(self) -> list[dict[str, Any]]:
        return json.loads(self._bad_path.read_text())

    def custom(self, raw: list[dict[str, Any]]) -> list[EvalExample]:
        if not raw or len(raw) > MAX_CUSTOM_EXAMPLES:
            raise InvalidPath(f"Send 1-{MAX_CUSTOM_EXAMPLES} examples.", pointer="#/examples")
        try:
            return resolve(parse_examples(raw), self._locate)
        except (DatasetError, KeyError, TypeError, ValueError) as err:
            raise InvalidPath(f"Invalid examples: {err}", pointer="#/examples") from err

    def config(self, k: int | None, mode: SearchMode | None) -> RunConfig:
        return RunConfig(
            k=k or self._base.k,
            mode=mode or self._base.mode,
            embedder=self._base.embedder,
            prompt_version=self._base.prompt_version,
            model=self._base.model,
        )

    # ---- runs ------------------------------------------------------------------------

    def run_retrieval(
        self, examples: list[EvalExample], k: int | None, mode: SearchMode | None
    ) -> dict[str, Any]:
        report = self._retrieval.retrieval(examples, self.config(k, mode))
        return self._store("ret", report)

    def run_full_job(
        self, request: dict[str, Any], progress: Callable[[dict[str, Any]], None]
    ) -> dict[str, Any]:
        """Runs inside a background job. The budget caps REAL calls; cache hits are free."""
        mode = SearchMode(request["search_mode"]) if request.get("search_mode") else None
        max_calls = request.get("max_calls")
        budget_limit = self._max_calls if max_calls is None else min(max_calls, self._max_calls)
        evaluator, _ = self._full(budget_limit)
        report = evaluator.full(
            self.builtin(), self.config(request.get("k"), mode), self.bad_answers(), progress
        )
        report["config"]["max_calls"] = budget_limit
        return self._store("full", report)

    def _store(self, prefix: str, report: dict[str, Any]) -> dict[str, Any]:
        report_id = f"{prefix}_{secrets.token_hex(5)}"
        report["id"] = report_id
        self._reports.save(report_id, report["kind"], report)
        return report

    # ---- stored reports ---------------------------------------------------------------

    def published(self) -> dict[str, dict[str, Any]]:
        """Reports committed under eval/results/ (comparison grid, reference full run)."""
        out = {}
        for file in sorted(self._results.glob("*.json")):
            data = json.loads(file.read_text())
            out[file.stem] = data | {"id": file.stem}
        return out

    def all(self) -> list[dict[str, Any]]:
        published = [
            {"id": k, "kind": v.get("kind"), "created_at": v.get("created_at"),
             "summary": v.get("summary"), "published": True}
            for k, v in self.published().items()
        ]  # fmt: skip
        runs = [r | {"published": False} for r in self._reports.all()]
        return published + runs

    def get(self, report_id: str) -> dict[str, Any]:
        published = self.published()
        if report_id in published:
            return published[report_id]
        return self._reports.get(report_id)  # raises EvaluationNotFound
