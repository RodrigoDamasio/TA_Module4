"""SQLite adapters: codebases + file records, embedding cache, LLM response cache, jobs,
traces, evaluation reports. The only module with SQL; every value is a bound parameter."""

import json
import threading
from array import array
from dataclasses import asdict

from app.domain.codebases import Codebase, CodebaseKind, FileRecord
from app.domain.errors import EvaluationNotFound, JobNotFound
from app.domain.files import Language
from app.domain.jobs import Job
from app.domain.tracing import Span, Trace

from . import database

_GET_CODEBASE = "SELECT data_json FROM codebases WHERE id = ?"
_LIST_CODEBASES = "SELECT data_json FROM codebases ORDER BY id"
_PUT_CODEBASE = "INSERT OR REPLACE INTO codebases (id, kind, data_json) VALUES (?, ?, ?)"
_DELETE_CODEBASE = "DELETE FROM codebases WHERE id = ?"
_DELETE_FILES = "DELETE FROM files WHERE codebase = ?"
_FILES = "SELECT data_json FROM files WHERE codebase = ? ORDER BY path"
_GET_FILE = "SELECT data_json FROM files WHERE codebase = ? AND path = ?"
_PUT_FILE = "INSERT OR REPLACE INTO files (codebase, path, data_json) VALUES (?, ?, ?)"
_DELETE_FILE = "DELETE FROM files WHERE codebase = ? AND path = ?"
_GET_VECTOR = "SELECT vector FROM embedding_cache WHERE model = ? AND key = ?"
_PUT_VECTOR = "INSERT OR REPLACE INTO embedding_cache (model, key, vector) VALUES (?, ?, ?)"
_COUNT_VECTORS = "SELECT COUNT(*) AS n FROM embedding_cache"
_GET_CACHE = "SELECT response_json FROM llm_cache WHERE key = ?"
_PUT_CACHE = "INSERT OR REPLACE INTO llm_cache (key, response_json) VALUES (?, ?)"
_ALL_CACHE = "SELECT key, response_json FROM llm_cache"
_PUT_JOB = "INSERT OR REPLACE INTO jobs (id, status, data_json) VALUES (?, ?, ?)"
_GET_JOB = "SELECT data_json FROM jobs WHERE id = ?"
_JOBS_WITH_STATUS = "SELECT data_json FROM jobs WHERE status = ?"
_PUT_TRACE = "INSERT INTO traces (request_id, kind, data_json) VALUES (?, ?, ?)"
_PRUNE_TRACES = "DELETE FROM traces WHERE seq <= (SELECT MAX(seq) FROM traces) - ?"
_RECENT_TRACES = "SELECT data_json FROM traces ORDER BY seq DESC LIMIT ?"
_PUT_REPORT = "INSERT OR REPLACE INTO reports (id, kind, data_json) VALUES (?, ?, ?)"
_GET_REPORT = "SELECT data_json FROM reports WHERE id = ?"
_LIST_REPORTS = "SELECT id, kind, created_at, data_json FROM reports ORDER BY created_at DESC"


class _Store:
    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.Lock()
        database.init(path)

    def _conn(self):
        return database.connect(self._path)


class SqliteIndexRepository(_Store):
    def get_codebase(self, codebase: str) -> Codebase | None:
        with self._conn() as conn:
            row = conn.execute(_GET_CODEBASE, (codebase,)).fetchone()
        return _codebase(json.loads(row["data_json"])) if row else None

    def list_codebases(self) -> list[Codebase]:
        with self._conn() as conn:
            rows = conn.execute(_LIST_CODEBASES).fetchall()
        return [_codebase(json.loads(r["data_json"])) for r in rows]

    def save_codebase(self, codebase: Codebase) -> None:
        data = asdict(codebase) | {"kind": codebase.kind.value}
        with self._lock, self._conn() as conn:
            conn.execute(_PUT_CODEBASE, (codebase.id, codebase.kind.value, json.dumps(data)))

    def delete_codebase(self, codebase: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(_DELETE_FILES, (codebase,))
            conn.execute(_DELETE_CODEBASE, (codebase,))

    def files(self, codebase: str) -> list[FileRecord]:
        with self._conn() as conn:
            rows = conn.execute(_FILES, (codebase,)).fetchall()
        return [_file(json.loads(r["data_json"])) for r in rows]

    def get_file(self, codebase: str, path: str) -> FileRecord | None:
        with self._conn() as conn:
            row = conn.execute(_GET_FILE, (codebase, path)).fetchone()
        return _file(json.loads(row["data_json"])) if row else None

    def save_file(self, record: FileRecord) -> None:
        data = asdict(record) | {"language": record.language.value}
        with self._lock, self._conn() as conn:
            conn.execute(_PUT_FILE, (record.codebase, record.path, json.dumps(data)))

    def delete_file(self, codebase: str, path: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(_DELETE_FILE, (codebase, path))


def _codebase(data: dict) -> Codebase:
    return Codebase(**(data | {"kind": CodebaseKind(data["kind"])}))


def _file(data: dict) -> FileRecord:
    return FileRecord(**(data | {"language": Language(data["language"])}))


class SqliteEmbeddingCache(_Store):
    """Vectors as float32 blobs (384 dims ≈ 1.5 KB). Hit/miss counters for /stats."""

    def __init__(self, path: str) -> None:
        super().__init__(path)
        self.hits = 0
        self.misses = 0

    def get_many(self, model: str, keys: list[str]) -> dict[str, list[float]]:
        found: dict[str, list[float]] = {}
        with self._conn() as conn:
            for key in keys:
                row = conn.execute(_GET_VECTOR, (model, key)).fetchone()
                if row is not None:
                    found[key] = array("f", row["vector"]).tolist()
        self.hits += len(found)
        self.misses += len(keys) - len(found)
        return found

    def put_many(self, model: str, items: dict[str, list[float]]) -> None:
        rows = [(model, k, array("f", v).tobytes()) for k, v in items.items()]
        with self._lock, self._conn() as conn:
            conn.executemany(_PUT_VECTOR, rows)

    def stats(self) -> dict[str, int]:
        with self._conn() as conn:
            stored = conn.execute(_COUNT_VECTORS).fetchone()["n"]
        return {"stored": stored, "hits": self.hits, "misses": self.misses}


class SqliteResponseCache(_Store):
    def get(self, key: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(_GET_CACHE, (key,)).fetchone()
        return json.loads(row["response_json"]) if row else None

    def put(self, key: str, value: dict) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(_PUT_CACHE, (key, json.dumps(value)))

    def export(self) -> dict[str, dict]:
        with self._conn() as conn:
            rows = conn.execute(_ALL_CACHE).fetchall()
        return {r["key"]: json.loads(r["response_json"]) for r in rows}

    def seed(self, entries: dict[str, dict]) -> int:
        with self._lock, self._conn() as conn:
            conn.executemany(_PUT_CACHE, [(k, json.dumps(v)) for k, v in entries.items()])
        return len(entries)


class SqliteJobRepository(_Store):
    def save(self, job: Job) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(_PUT_JOB, (job.id, job.status.value, json.dumps(job.to_dict())))

    def get(self, job_id: str) -> Job:
        with self._conn() as conn:
            row = conn.execute(_GET_JOB, (job_id,)).fetchone()
        if row is None:
            raise JobNotFound(job_id)
        return Job.from_dict(json.loads(row["data_json"]))

    def with_status(self, statuses: set[str]) -> list[Job]:
        with self._conn() as conn:
            rows = [r for s in sorted(statuses) for r in conn.execute(_JOBS_WITH_STATUS, (s,))]
        return [Job.from_dict(json.loads(r["data_json"])) for r in rows]


class SqliteTraceStore(_Store):
    """Content-free traces (ids, counts, scores, timings); pruned to `retention`."""

    def __init__(self, path: str, retention: int = 500) -> None:
        super().__init__(path)
        self._retention = retention

    def save(self, trace: Trace) -> None:
        data = {
            "request_id": trace.request_id,
            "kind": trace.kind,
            "total_ms": trace.total_ms,
            "spans": [asdict(s) for s in trace.spans],
            "attrs": trace.attrs,
        }
        with self._lock, self._conn() as conn:
            conn.execute(_PUT_TRACE, (trace.request_id, trace.kind, json.dumps(data, default=str)))
            conn.execute(_PRUNE_TRACES, (self._retention,))

    def recent(self, limit: int) -> list[Trace]:
        with self._conn() as conn:
            rows = conn.execute(_RECENT_TRACES, (limit,)).fetchall()
        traces = []
        for row in rows:
            d = json.loads(row["data_json"])
            spans = [Span(**s) for s in d["spans"]]
            traces.append(Trace(d["request_id"], d["kind"], d["total_ms"], spans, d["attrs"]))
        return traces


class SqliteReportStore(_Store):
    def save(self, report_id: str, kind: str, report: dict) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(_PUT_REPORT, (report_id, kind, json.dumps(report, default=str)))

    def get(self, report_id: str) -> dict:
        with self._conn() as conn:
            row = conn.execute(_GET_REPORT, (report_id,)).fetchone()
        if row is None:
            raise EvaluationNotFound(report_id)
        return json.loads(row["data_json"])

    def all(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(_LIST_REPORTS).fetchall()
        out = []
        for r in rows:
            data = json.loads(r["data_json"])
            out.append(
                {
                    "id": r["id"],
                    "kind": r["kind"],
                    "created_at": r["created_at"],
                    "summary": data.get("summary"),
                }
            )
        return out
