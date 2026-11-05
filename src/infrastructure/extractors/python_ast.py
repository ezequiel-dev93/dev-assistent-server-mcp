import ast
from pathlib import Path
from typing import List, Optional, Tuple
from ...core.errors import UnparseableFileError
from ...core.models import ImportRef
from ...core.ports import IImportExtractor


def compute_python_module_and_package(file_path: Path, project_root: Path) -> Tuple[str, str]:
    """Returns (module_name, package_name) for a .py file relative to project_root."""
    rel = file_path.relative_to(project_root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
        pkg = ".".join(parts)
        return pkg, pkg
    return ".".join(parts), ".".join(parts[:-1])


def resolve_relative_python_import(
    module: Optional[str], level: int, current_pkg: str
) -> str:
    if level == 0:
        return module or ""
    parts = current_pkg.split(".") if current_pkg else []
    keep = len(parts) - (level - 1)
    if keep < 0:
        return module or ""
    base = parts[:keep]
    return ".".join([*base, module] if module else base)


class _AstImportVisitor(ast.NodeVisitor):
    def __init__(self, source: str, current_pkg: str) -> None:
        self.source = source
        self.current_pkg = current_pkg
        self.refs: List[ImportRef] = []
        self._in_type_checking = False

    def visit_If(self, node: ast.If) -> None:
        is_tc = (
            isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
        ) or (
            isinstance(node.test, ast.Attribute) and node.test.attr == "TYPE_CHECKING"
        )
        prev = self._in_type_checking
        self._in_type_checking = self._in_type_checking or is_tc
        for child in node.body:
            self.visit(child)
        self._in_type_checking = prev
        for child in node.orelse:
            self.visit(child)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._add(alias.name, node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = resolve_relative_python_import(node.module, node.level, self.current_pkg)
        if node.module is None:
            for alias in node.names:
                full_target = f"{base}.{alias.name}" if base else alias.name
                self._add(full_target, node)
        else:
            self._add(base, node)
            for alias in node.names:
                if alias.name != "*":
                    self._add(f"{base}.{alias.name}" if base else alias.name, node)

    def visit_Call(self, node: ast.Call) -> None:
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
        if name in {"import_module", "__import__"} and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                self._add(arg.value, node, dynamic=True)
        self.generic_visit(node)

    def _add(self, module: str, node: ast.AST, dynamic: bool = False) -> None:
        if not module:
            return
        seg = ast.get_source_segment(self.source, node) or f"import {module}"
        stmt_line = seg.splitlines()[0].strip()
        self.refs.append(
            ImportRef(
                module=module,
                line=getattr(node, "lineno", 1),
                statement=stmt_line,
                is_dynamic=dynamic,
                type_only=self._in_type_checking,
            )
        )


class PythonAstExtractor(IImportExtractor):
    """AST-based import extractor for Python source files."""

    def supports(self, file_path: Path) -> bool:
        return file_path.suffix.lower() == ".py"

    def extract(self, file_path: Path, project_root: Path) -> List[ImportRef]:
        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            raise UnparseableFileError(file_path, exc) from exc

        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError as exc:
            raise UnparseableFileError(file_path, exc) from exc

        _, current_pkg = compute_python_module_and_package(file_path, project_root)
        visitor = _AstImportVisitor(source, current_pkg)
        visitor.visit(tree)
        return visitor.refs
