"""Chunkers and file acceptance (C1–C9), 0 calls."""

import pytest

from app.chunking.markdown import MarkdownChunker
from app.chunking.registry import ChunkerRegistry, Strategy, locate_symbols
from app.chunking.splitting import windows
from app.domain.chunks import ChunkKind
from app.domain.errors import InvalidPath
from app.domain.files import Language, language_for, skip_reason, validate_path
from app.infrastructure.samples import SAMPLES, sample_files

PY = (
    '''"""Auth."""
import jwt

SECRET = "x"


@dataclass
class Token:
    value: str


class AuthService(BaseService):
    """Issues tokens."""

    ttl = 3600

    def login(self, email: str, password: str) -> Token:
        def inner():
            return 1
'''
    + "        x = 1\n" * 40
    + """
    async def logout(self, token):
        return None


async def helper(a, *, b=2) -> int:
    return a


if __name__ == "__main__":
    helper(1)
"""
)


def by_symbol(chunks):
    return {(c.kind, c.symbol): c for c in chunks}


# C1
def test_python_units_symbols_signatures_and_lines():
    chunks = ChunkerRegistry(max_chars=600, min_chars=0).chunk("cb", "app/auth.py", PY).chunks
    kinds = [(c.kind.value, c.symbol, c.part) for c in chunks]
    assert ("module", None, None) in kinds
    assert ("class", "Token", None) in kinds  # small class: one chunk, decorator included
    token = next(c for c in chunks if c.symbol == "Token")
    assert token.code.startswith("@dataclass") and token.start_line == 7
    # big class → header part + one chunk per method
    header = next(c for c in chunks if c.kind is ChunkKind.CLASS and c.symbol == "AuthService")
    assert "class AuthService(BaseService)" in header.header and "methods: login, logout" in (
        header.header
    )
    logins = [c for c in chunks if c.symbol == "AuthService.login"]
    assert len(logins) > 1 and all(c.kind is ChunkKind.METHOD for c in logins)
    assert "def login(self, email: str, password: str) -> Token" in logins[0].header
    assert not any(c.symbol and "inner" in c.symbol for c in chunks)  # nested stays inside
    helper = next(c for c in chunks if c.symbol == "helper")
    assert helper.signature == "async def helper(a, *, b=2) -> int"
    assert helper.code.splitlines()[0] == PY.splitlines()[helper.start_line - 1]
    main_block = [c for c in chunks if c.kind is ChunkKind.MODULE]
    assert any("__main__" in c.code for c in main_block)


# C2
def test_python_syntax_error_falls_back_to_windows():
    result = ChunkerRegistry().chunk("cb", "bad.py", "def f(:\n    pass\n")
    assert result.fallback and [c.kind for c in result.chunks] == [ChunkKind.WINDOW]


TS = """import { z } from "zod";

/** Order schema */
export const OrderSchema = z.object({ id: z.string() });

export interface Order { id: string }
export type Id = string;
export enum Status { New, Paid }

/**
 * Processes an order.
 */
export async function processOrder(order: Order): Promise<void> {
  await fetch("/orders");
}

export const total = (items: number[]): number => items.reduce((a, b) => a + b, 0);
function* gen() { yield 1; }

export class Cart {
  items: number[] = [];
  add(n: number) { this.items.push(n); }
}
const x = 1;
"""


# C3
def test_typescript_units():
    chunks = ChunkerRegistry(min_chars=0).chunk("cb", "src/orders.ts", TS).chunks
    symbols = {c.symbol: c for c in chunks}
    assert symbols["processOrder"].kind is ChunkKind.FUNCTION
    assert symbols["processOrder"].code.startswith("/**")  # JSDoc attached
    assert symbols["total"].kind is ChunkKind.FUNCTION  # arrow-function const
    assert symbols["gen"].kind is ChunkKind.FUNCTION
    for name in ("OrderSchema", "Order", "Id", "Status", "Cart"):
        assert symbols[name].kind is ChunkKind.CLASS, name
    assert symbols["OrderSchema"].code.startswith("/** Order schema */")
    module = [c for c in chunks if c.kind is ChunkKind.MODULE]
    assert any("import" in c.code for c in module) and any("const x" in c.code for c in module)


def test_typescript_big_class_splits_into_methods_and_tsx_and_js_parse():
    body = "\n".join(f"  m{i}() {{ return {i}; }}" for i in range(40))
    source = f"export class Big {{\n  field = 1;\n{body}\n}}\n"
    chunks = ChunkerRegistry(max_chars=400, min_chars=0).chunk("cb", "big.ts", source).chunks
    assert any(c.symbol == "Big.m3" and c.kind is ChunkKind.METHOD for c in chunks)
    assert any(c.symbol == "Big" and c.kind is ChunkKind.CLASS for c in chunks)
    tsx = "export function App() {\n  return <div>Hello</div>;\n}\n"
    assert ChunkerRegistry().chunk("cb", "App.tsx", tsx).chunks[0].symbol == "App"
    js = "const f = function () { return 1; };\nmodule.exports = { f };\n"
    result = ChunkerRegistry().chunk("cb", "f.js", js)
    assert result.language is Language.JAVASCRIPT and result.chunks[0].symbol == "f"


# C4
def test_typescript_mostly_broken_falls_back():
    result = ChunkerRegistry().chunk("cb", "x.ts", "@@@ ((( ]]] {{{ !!! ### $$$ %%%\n" * 5)
    assert result.fallback


# C5
def test_markdown_heading_paths_fences_and_merging():
    md = "# Title\n\nIntro.\n\n## Setup\n\n" + "Install.\n" * 30
    md += "\n```bash\n# not a heading\n```\n\n## Database\n\nDB url.\n" + "more\n" * 50
    drafts = MarkdownChunker().drafts("README.md", md)
    titles = [d.symbol for d in drafts]
    assert titles == ["Title > Setup", "Title > Database"]  # tiny "Title" merged forward
    assert drafts[0].start_line == 1
    assert not any("not a heading" in (t or "") for t in titles)
    no_heading = MarkdownChunker().drafts("NOTES.md", "just text\n" * 30)
    assert no_heading[0].symbol == "NOTES.md"


# C6
def test_splitter_respects_the_budget_with_overlap_and_parts():
    source = "def big():\n" + "".join(f"    value_{i} = compute({i})\n" for i in range(200))
    chunks = ChunkerRegistry(max_chars=500, overlap=0.15).chunk("cb", "big.py", source).chunks
    assert len(chunks) > 3
    assert all(len(c.embed_text) <= 500 for c in chunks)
    assert [c.part for c in chunks] == [(i, len(chunks)) for i in range(1, len(chunks) + 1)]
    assert all("(part" in c.header for c in chunks)
    assert chunks[1].start_line <= chunks[0].end_line  # overlap
    assert windows(["x" * 900], 100, 0.15) == [(0, 1)]  # one over-long line = one window


def test_small_units_are_packed_within_their_scope():
    source = (
        "import os\n\n\nclass AuthError(Exception):\n    pass\n\n\n"
        "def small():\n    return 1\n\n\n" + "def big():\n" + "    x = 1\n" * 120
    )
    chunks = ChunkerRegistry(max_chars=1400, min_chars=200).chunk("cb", "a.py", source).chunks
    first = chunks[0]
    assert first.symbol == "AuthError, small" and first.start_line == 1  # imports joined in
    assert "class AuthError(Exception)" in first.header and "def small()" in first.header
    assert all(c.symbol == "big" for c in chunks[1:])  # too big to join: split on its own
    unpacked = ChunkerRegistry(min_chars=0).chunk("cb", "a.py", source).chunks
    assert len(unpacked) > len(chunks)
    # methods of a big class never merge with module-level code
    big_class = (
        "class A:\n"
        + "".join(f"    def m{i}(self):\n        return {i}\n" for i in range(60))
        + "\n\ndef after():\n    return 0\n"
    )
    packed = ChunkerRegistry(max_chars=600, min_chars=300).chunk("cb", "b.py", big_class).chunks
    assert all(not (c.symbol or "").startswith("A") or "after" not in c.symbol for c in packed)
    assert any(c.symbol == "after" for c in packed)


# C7
@pytest.mark.parametrize("strategy", list(Strategy))
def test_every_nonblank_line_of_every_sample_is_covered(strategy):
    registry = ChunkerRegistry()
    for codebase in SAMPLES:
        for file in sample_files(codebase):
            chunks = registry.chunk(codebase, file.path, file.content, strategy).chunks
            covered = {n for c in chunks for n in range(c.start_line, c.end_line + 1)}
            for n, line in enumerate(file.content.splitlines(), 1):
                if line.strip():
                    assert n in covered, f"{codebase}/{file.path}:{n} not covered"


def test_samples_parse_without_fallback_and_headers_follow_the_strategy():
    registry = ChunkerRegistry()
    for codebase in SAMPLES:
        for file in sample_files(codebase):
            assert not registry.chunk(codebase, file.path, file.content).fallback, file.path
    file = sample_files("shopflow")[0]
    assert all(c.header for c in registry.chunk("s", file.path, file.content).chunks)
    plain = registry.chunk("s", file.path, file.content, Strategy.CODE_AWARE_NO_HEADER).chunks
    assert all(c.header == "" for c in plain)


# C8
def test_chunk_ids_are_stable_and_content_addressed():
    registry = ChunkerRegistry()
    a = registry.chunk("cb", "a.py", "def f():\n    return 1\n").chunks[0]
    b = registry.chunk("cb", "a.py", "def f():\n    return 1\n").chunks[0]
    c = registry.chunk("cb", "a.py", "def f():\n    return 2\n").chunks[0]
    d = registry.chunk("other", "a.py", "def f():\n    return 1\n").chunks[0]
    assert a.id == b.id and a.id != c.id and a.id != d.id


def test_locate_symbols_maps_classes_and_methods():
    symbols = locate_symbols("svc.py", PY)
    assert symbols["AuthService"][0] < symbols["AuthService.login"][0]
    assert symbols["AuthService"][1] >= symbols["AuthService.logout"][1]
    md = locate_symbols("README.md", "# A\n\ntext\n\n## B\n\nmore\n")
    assert md == {"A": (1, 4), "A > B": (5, 7)}


# C9
@pytest.mark.parametrize(
    ("path", "content", "reason"),
    [
        ("node_modules/x/index.js", "x", "vendored-or-generated"),
        ("app/__pycache__/a.py", "x", "vendored-or-generated"),
        (".env", "KEY=1", "secrets"),
        ("config/.env.production", "KEY=1", "secrets"),
        ("package-lock.json", "{}", "lockfile"),
        ("image.png", "x", "unsupported-type"),
        ("a.py", "x\x00y", "binary"),
        ("a.js", "x" * 1001, "minified"),
        ("a.py", "x = 1\n", None),
        (".env.example", "KEY=", None),
    ],
)
def test_file_acceptance(path, content, reason):
    assert skip_reason(path, content) == reason


@pytest.mark.parametrize("bad", ["", "/etc/passwd", "../x.py", "a/../b.py", "a\\b.py", "./a.py",
                                 "C:/x.py", "a\nb.py", "x" * 201])  # fmt: skip
def test_invalid_paths(bad):
    with pytest.raises(InvalidPath):
        validate_path(bad)


def test_languages():
    assert language_for("a.PY") is Language.PYTHON
    assert language_for("a.tsx") is Language.TYPESCRIPT
    assert language_for("a.mjs") is Language.JAVASCRIPT
    assert language_for("a.yml") is Language.TEXT
    assert language_for("a.exe") is None
