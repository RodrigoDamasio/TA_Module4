"""Python chunker (§6.1): one chunk per function / class / method, plus the code between
definitions (imports, constants). Parsed with `ast` — never compiled or executed."""

import ast

from app.domain.chunks import ChunkKind

from .splitting import Draft, uncovered_blocks

_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
MODULE_CONTEXT = "module code (imports, constants, top-level statements)"


def signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix} {node.name}({ast.unparse(node.args)}){returns}"


def class_label(node: ast.ClassDef) -> str:
    bases = [ast.unparse(b) for b in node.bases] + [ast.unparse(k) for k in node.keywords]
    return f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"


def _span(node: ast.stmt, lines: list[str]) -> tuple[int, int]:
    decorators = getattr(node, "decorator_list", [])
    start = min([node.lineno] + [d.lineno for d in decorators])
    end = node.end_lineno or node.lineno
    return start, end


class PythonChunker:
    def __init__(self, max_chars: int) -> None:
        self._max = max_chars

    def drafts(self, content: str) -> list[Draft] | None:
        """None when the file does not parse (the caller falls back to fixed-size)."""
        try:
            tree = ast.parse(content)
        except (SyntaxError, ValueError):
            return None
        lines = content.splitlines()
        out: list[Draft] = []
        self._scope(tree.body, 1, len(lines), lines, [], None, None, out)
        return out

    def _scope(
        self,
        body: list[ast.stmt],
        first: int,
        last: int,
        lines: list[str],
        context: list[str],
        owner: str | None,
        owner_label: str | None,
        out: list[Draft],
    ) -> None:
        covered: list[tuple[int, int]] = []
        methods: list[str] = []
        for node in body:
            if not isinstance(node, _DEFS):
                continue
            start, end = _span(node, lines)
            covered.append((start, end))
            qual = f"{owner}.{node.name}" if owner else node.name
            if isinstance(node, ast.ClassDef):
                label = class_label(node)
                size = sum(len(line) + 1 for line in lines[start - 1 : end])
                has_methods = any(isinstance(n, _DEFS) for n in node.body)
                if size <= self._max or not has_methods:
                    out.append(Draft(ChunkKind.CLASS, start, end, qual, label, [*context, label],
                                     owner or ""))  # fmt: skip
                else:  # big class: header part + one chunk per method (recursively)
                    self._scope(node.body, start, end, lines, [*context, label], qual, label, out)
            else:
                methods.append(node.name)
                sig = signature(node)
                kind = ChunkKind.METHOD if owner else ChunkKind.FUNCTION
                out.append(Draft(kind, start, end, qual, sig, [*context, sig], owner or ""))

        for s, e in uncovered_blocks(first, last, covered, lines):
            if owner is None:
                out.append(
                    Draft(ChunkKind.MODULE, s, e, None, None, [*context, MODULE_CONTEXT], "")
                )
            else:
                outline = [f"methods: {', '.join(methods)}"] if methods else []
                out.append(
                    Draft(ChunkKind.CLASS, s, e, owner, owner_label, [*context, *outline], owner)
                )
