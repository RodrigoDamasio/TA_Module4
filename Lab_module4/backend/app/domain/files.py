"""Source files: languages, path rules, and which files are indexed at all (§6.5)."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from .errors import InvalidPath


class Language(StrEnum):
    PYTHON = "python"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    MARKDOWN = "markdown"
    TEXT = "text"


EXTENSIONS: dict[str, Language] = {
    ".py": Language.PYTHON,
    ".pyi": Language.PYTHON,
    ".ts": Language.TYPESCRIPT,
    ".tsx": Language.TYPESCRIPT,
    ".js": Language.JAVASCRIPT,
    ".jsx": Language.JAVASCRIPT,
    ".mjs": Language.JAVASCRIPT,
    ".cjs": Language.JAVASCRIPT,
    ".md": Language.MARKDOWN,
    ".txt": Language.TEXT,
    ".json": Language.TEXT,
    ".toml": Language.TEXT,
    ".yaml": Language.TEXT,
    ".yml": Language.TEXT,
    ".cfg": Language.TEXT,
    ".ini": Language.TEXT,
}

SKIPPED_DIRS = frozenset(
    {"node_modules", ".git", "dist", "build", "__pycache__", ".venv", "venv", ".next"}
)
LOCKFILES = frozenset(
    {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock", "Pipfile.lock"}
)
MAX_PATH_CHARS = 200
MINIFIED_LINE_CHARS = 1000


@dataclass(frozen=True)
class SourceFile:
    path: str
    content: str


def validate_path(path: str) -> str:
    """A relative, '/'-separated path without '..' — raises InvalidPath otherwise."""
    if not path or len(path) > MAX_PATH_CHARS:
        raise InvalidPath(f"File path must be 1-{MAX_PATH_CHARS} characters: '{path[:40]}'.")
    if "\\" in path or path.startswith("/") or ":" in path.split("/")[0]:
        raise InvalidPath(f"Use a relative path with '/' separators: '{path}'.")
    if not path.isprintable():
        raise InvalidPath("File paths must not contain control characters.")
    parts = PurePosixPath(path).parts
    if any(p in ("..", ".") for p in path.split("/")) or not parts:
        raise InvalidPath(f"File paths must not contain '.' or '..' segments: '{path}'.")
    return path


def language_for(path: str) -> Language | None:
    name = PurePosixPath(path).name
    if name == ".env.example":
        return Language.TEXT
    return EXTENSIONS.get(PurePosixPath(path).suffix.lower())


def skip_reason(path: str, content: str) -> str | None:
    """Why an otherwise valid file is not indexed (reported, not an error), or None."""
    pure = PurePosixPath(path)
    if any(part in SKIPPED_DIRS for part in pure.parts[:-1]):
        return "vendored-or-generated"
    if pure.name == ".env" or (pure.name.startswith(".env.") and pure.name != ".env.example"):
        return "secrets"
    if pure.name in LOCKFILES:
        return "lockfile"
    if language_for(path) is None:
        return "unsupported-type"
    if "\x00" in content:
        return "binary"
    if any(len(line) > MINIFIED_LINE_CHARS for line in content.splitlines()):
        return "minified"
    return None
