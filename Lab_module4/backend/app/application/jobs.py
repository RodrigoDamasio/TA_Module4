"""JobService: index and full-evaluation jobs (submit → background run → poll / wait)."""

import logging
import time
from collections.abc import Callable
from typing import Any

from app.domain.errors import DomainError, ModelsLoading, QueueFull
from app.domain.files import SourceFile
from app.domain.jobs import Job, JobStatus
from app.domain.ports import JobRepository, JobRunner

from .embedding import Models
from .indexing import IndexingService

logger = logging.getLogger(__name__)
EvaluationRun = Callable[[dict[str, Any], Callable[[dict[str, Any]], None]], dict[str, Any]]


class JobService:
    def __init__(
        self,
        jobs: JobRepository,
        indexing: IndexingService,
        models: Models,
        run_evaluation: EvaluationRun,
        model_wait_s: float = 600,
    ) -> None:
        self._jobs, self._indexing, self._models = jobs, indexing, models
        self._run_evaluation = run_evaluation
        self._model_wait = model_wait_s
        self.runner: JobRunner | None = None  # set by the composition root

    # ---- submit ------------------------------------------------------------------------

    def submit_index(self, codebase: str, files: list[SourceFile]) -> Job:
        self._indexing.validate(codebase, files)
        job = Job.create(
            "index",
            {
                "codebase": codebase,
                "files": [{"path": f.path, "content": f.content} for f in files],
            },
        )
        return self._submit(job)

    def submit_evaluation(self, request: dict[str, Any]) -> Job:
        return self._submit(Job.create("evaluate", request))

    def _submit(self, job: Job) -> Job:
        assert self.runner is not None  # noqa: S101 — wired at startup
        if not self.runner.has_capacity():
            raise QueueFull()
        self._jobs.save(job)
        self.runner.submit(job.id)
        return self._jobs.get(job.id)  # the inline runner may already have finished it

    # ---- run (worker thread) -----------------------------------------------------------------

    def run(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        job.start()
        self._jobs.save(job)

        def progress(update: dict[str, Any]) -> None:
            job.progress = update
            self._jobs.save(job)

        try:
            if job.kind == "index":
                result = self._index(job, progress)
            else:
                result = self._run_evaluation(job.request, progress)
            job.complete(result)
        except DomainError as err:
            job.fail(type(err).__name__, str(err))
        except Exception as err:  # never kill the worker; the job records the failure
            logger.exception("job %s crashed", job.id)
            job.fail("InternalError", f"Unexpected error ({type(err).__name__}).")
        self._jobs.save(job)
        logger.info("job=%s kind=%s status=%s", job.id, job.kind, job.status.value)

    def _index(self, job: Job, progress: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        files = [SourceFile(f["path"], f["content"]) for f in job.request["files"]]
        codebase = job.request["codebase"]
        job.request = {"codebase": codebase, "file_count": len(files)}  # drop the contents
        if not self._models.wait_ready(self._model_wait):
            raise ModelsLoading()
        return self._indexing.index(codebase, files, progress=progress)

    # ---- read --------------------------------------------------------------------------------

    def get(self, job_id: str) -> Job:
        return self._jobs.get(job_id)

    def wait(self, job_id: str, timeout_s: float, poll_s: float = 0.1) -> Job:
        deadline = time.monotonic() + timeout_s
        job = self._jobs.get(job_id)
        while not job.done and time.monotonic() < deadline:
            time.sleep(poll_s)
            job = self._jobs.get(job_id)
        return job

    def recover(self) -> int:
        """Jobs left queued or running by a restart cannot resume: mark them failed. Files
        already indexed by an interrupted job stay indexed."""
        stale = self._jobs.with_status({JobStatus.QUEUED.value, JobStatus.RUNNING.value})
        for job in stale:
            if job.kind == "index":
                job.request = {k: v for k, v in job.request.items() if k != "files"}
            job.fail("Interrupted", "Interrupted by a server restart — please submit it again.")
            self._jobs.save(job)
        return len(stale)
