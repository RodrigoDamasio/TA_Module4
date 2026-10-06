"""Layering and security guards (S1, Q4), as in Labs 1–3."""

import ast
import logging
import sqlite3
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
LIBRARIES = ("google", "sqlite3", "chromadb", "fastembed", "onnxruntime", "tree_sitter",
             "tree_sitter_typescript", "tree_sitter_javascript", "subprocess")  # fmt: skip
WEB_AND_IO = {"fastapi", "starlette", "httpx", *LIBRARIES}


def imported_modules(path: Path) -> set[str]:
    modules = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def offenders(layer: str, forbidden: set[str]) -> set[str]:
    return {
        f"{p.relative_to(APP)} imports {m}"
        for p in (APP / layer).rglob("*.py")
        for m in imported_modules(p)
        if any(m == f or m.startswith(f + ".") for f in forbidden)
    }


def test_domain_imports_only_stdlib_and_pydantic():
    inner = {"app.application", "app.infrastructure", "app.api", "app.chunking"}
    assert offenders("domain", WEB_AND_IO | inner) == set()


def test_application_and_chunking_never_touch_web_storage_or_models():
    outer = {"app.infrastructure", "app.api"}
    assert offenders("application", WEB_AND_IO | outer) == set()
    tree_sitter = {"tree_sitter", "tree_sitter_typescript", "tree_sitter_javascript"}
    assert offenders("chunking", (WEB_AND_IO - tree_sitter) | outer | {"app.application"}) == set()


def test_libraries_stay_in_their_modules():
    where: dict[str, set[str]] = {lib: set() for lib in LIBRARIES}
    for path in APP.rglob("*.py"):
        for module in imported_modules(path):
            for lib in LIBRARIES:
                if module == lib or module.startswith(lib + "."):
                    where[lib].add(str(path.relative_to(APP)))
    assert where == {
        "google": {"infrastructure/gemini_client.py"},
        "sqlite3": {"infrastructure/database.py"},
        "chromadb": {"infrastructure/chroma_store.py"},
        "fastembed": {"infrastructure/fastembed_models.py"},
        "onnxruntime": set(),
        "tree_sitter": {"chunking/typescript.py"},
        "tree_sitter_typescript": {"chunking/typescript.py"},
        "tree_sitter_javascript": {"chunking/typescript.py"},
        "subprocess": set(),  # uploaded code is never run
    }


def test_sql_lives_only_in_the_sqlite_adapters():
    sql_words = ("SELECT ", "INSERT ", "UPDATE ", "DELETE FROM")
    files = {
        str(p.relative_to(APP))
        for p in APP.rglob("*.py")
        if any(w in p.read_text() for w in sql_words)
    }
    assert files <= {"infrastructure/database.py", "infrastructure/sqlite_store.py"}


def test_uploaded_code_is_never_executed():
    """No exec/eval/compile/import of user content anywhere in the app."""
    for path in APP.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"exec", "eval", "compile", "__import__"}, path


def test_ruff_flags_sql_built_from_strings(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def f(c, x):\n    return c.execute(f\"SELECT * FROM t WHERE a = '{x}'\")\n")
    result = subprocess.run(  # noqa: S603 — fixed argv
        [sys.executable, "-m", "ruff", "check", "--no-cache", "--select", "S608", str(bad)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0 and "S608" in result.stdout


# Q4
def test_question_and_code_never_reach_logs_or_stored_traces(api, caplog, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-never-used")
    marker_q, marker_code = "ZEBRA_QUESTION_MARKER", "TOP_SECRET_ALGORITHM_MARKER"
    a = api()
    files = [{"path": "algo.py", "content": f"def secret():\n    {marker_code} = 42\n"}]
    with caplog.at_level(logging.DEBUG):
        a.client.post("/index/files?wait=true", json={"codebase": "private", "files": files})
        r = a.client.post(
            "/query?debug=true",
            json={"question": f"What does secret do with {marker_q}?", "codebases": ["private"]},
        )
        a.client.post("/search?debug=true", json={"query": marker_q, "codebases": ["private"]})
    body = r.text
    assert marker_q in body and marker_code in body  # the caller gets everything back
    assert "event" in caplog.text and "request_end" in caplog.text
    for secret in (marker_q, marker_code, "test-key-never-used"):
        assert secret not in caplog.text
    with sqlite3.connect(a.container.settings.database_path) as conn:
        rows = conn.execute("SELECT data_json FROM traces").fetchall()
    assert rows and not any(marker_q in row[0] or marker_code in row[0] for row in rows)
