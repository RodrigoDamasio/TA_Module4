"""TypeScript / JavaScript chunker (§6.2) with tree-sitter: functions, classes (methods
when big), arrow-function consts, interfaces / types / enums, Zod schemas. JSDoc comments
stay with their declaration. Parsed only — never executed."""

from functools import cache

import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts
from tree_sitter import Language, Node, Parser

from app.domain.chunks import ChunkKind

from .splitting import Draft, uncovered_blocks

MODULE_CONTEXT = "module code (imports, constants, top-level statements)"
MAX_ERROR_RATIO = 0.2
_FUNCTIONS = {"function_declaration", "generator_function_declaration"}
_CLASSES = {"class_declaration", "abstract_class_declaration"}
_TYPES = {"interface_declaration", "type_alias_declaration", "enum_declaration"}
_VARIABLES = {"lexical_declaration", "variable_declaration"}
_FUNCTION_VALUES = {"arrow_function", "function_expression", "function", "generator_function"}
_METHODS = {"method_definition", "abstract_method_signature"}


@cache
def _parser(grammar: str) -> Parser:
    language = {
        "typescript": lambda: Language(tsts.language_typescript()),
        "tsx": lambda: Language(tsts.language_tsx()),
        "javascript": lambda: Language(tsjs.language()),
    }[grammar]()
    return Parser(language)


def grammar_for(path: str) -> str:
    if path.endswith(".tsx"):
        return "tsx"
    if path.endswith(".ts"):
        return "typescript"
    return "javascript"


def _text(node: Node) -> str:
    return (node.text or b"").decode("utf-8", errors="replace")


def _name(node: Node) -> str | None:
    name = node.child_by_field_name("name")
    return _text(name) if name is not None else None


def first_line(node: Node, limit: int = 160) -> str:
    line = _text(node).splitlines()[0] if _text(node) else ""
    line = line.split("{")[0].rstrip() if "{" in line and "=>" not in line else line.rstrip()
    return line[:limit].rstrip(" {")


def _error_bytes(node: Node) -> int:
    if node.type == "ERROR" or node.is_missing:
        return node.end_byte - node.start_byte
    return sum(_error_bytes(c) for c in node.children) if node.has_error else 0


def classify(node: Node) -> tuple[ChunkKind, str, Node] | None:
    """(kind, symbol name, declaration node) for a top-level or class-body statement."""
    decl = node
    if node.type == "export_statement":
        inner = node.child_by_field_name("declaration")
        if inner is None:
            inner = next((c for c in node.named_children if c.type != "comment"), None)
        if inner is None:
            return None
        decl = inner
    if decl.type in _FUNCTIONS | _CLASSES | _TYPES:
        name = _name(decl)
        if not name:
            return None
        kind = ChunkKind.FUNCTION if decl.type in _FUNCTIONS else ChunkKind.CLASS
        return kind, name, decl
    if decl.type in _VARIABLES:
        declarators = [c for c in decl.named_children if c.type == "variable_declarator"]
        if len(declarators) != 1:
            return None
        value = declarators[0].child_by_field_name("value")
        name = _name(declarators[0])
        if value is None or not name:
            return None
        if value.type in _FUNCTION_VALUES:
            return ChunkKind.FUNCTION, name, decl
        if value.type == "call_expression" and _text(value).startswith("z."):
            return ChunkKind.CLASS, name, decl  # Zod schema
    return None


class TypeScriptChunker:
    def __init__(self, max_chars: int) -> None:
        self._max = max_chars

    def drafts(self, path: str, content: str) -> list[Draft] | None:
        data = content.encode()
        tree = _parser(grammar_for(path)).parse(data)
        root = tree.root_node
        if root.has_error and _error_bytes(root) > MAX_ERROR_RATIO * max(len(data), 1):
            return None
        lines = content.splitlines()
        out: list[Draft] = []
        self._scope(list(root.named_children), 1, len(lines), lines, [], None, out)
        return out

    def _scope(
        self,
        nodes: list[Node],
        first: int,
        last: int,
        lines: list[str],
        context: list[str],
        owner: str | None,
        out: list[Draft],
    ) -> None:
        covered: list[tuple[int, int]] = []
        methods: list[str] = []
        for node in nodes:
            if owner is None:
                found = classify(node)
            elif node.type in _METHODS and _name(node):
                found = (ChunkKind.METHOD, _name(node) or "", node)
            else:
                found = None
            if found is None:
                continue
            kind, name, decl = found
            start, end = self._span(node)
            covered.append((start, end))
            qual = f"{owner}.{name}" if owner else name
            label = first_line(decl)
            size = sum(len(line) + 1 for line in lines[start - 1 : end])
            body = decl.child_by_field_name("body")
            if decl.type in _CLASSES and size > self._max and body is not None:
                inner = list(body.named_children)
                self._scope(inner, start, end, lines, [*context, label], qual, out)
                continue
            if kind is ChunkKind.METHOD:
                methods.append(name)
            out.append(Draft(kind, start, end, qual, label, [*context, label], owner or ""))

        for s, e in uncovered_blocks(first, last, covered, lines):
            if owner is None:
                out.append(
                    Draft(ChunkKind.MODULE, s, e, None, None, [*context, MODULE_CONTEXT], "")
                )
            else:
                outline = [f"methods: {', '.join(methods)}"] if methods else []
                out.append(Draft(ChunkKind.CLASS, s, e, owner, None, [*context, *outline], owner))

    @staticmethod
    def _span(node: Node) -> tuple[int, int]:
        """1-based lines, extended upward over directly preceding comments (JSDoc)."""
        start, end = node.start_point[0] + 1, node.end_point[0] + 1
        prev = node.prev_named_sibling
        while prev is not None and prev.type == "comment" and prev.end_point[0] + 1 >= start - 1:
            start = prev.start_point[0] + 1
            prev = prev.prev_named_sibling
        return start, end
