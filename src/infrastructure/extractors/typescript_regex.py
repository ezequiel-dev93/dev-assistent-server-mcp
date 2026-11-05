import re
from pathlib import Path
from typing import List
from ...core.errors import UnparseableFileError
from ...core.models import ImportRef
from ...core.ports import IImportExtractor

TS_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".astro"}

_BLOCK_COMMENT_RE = re.compile(r"/\*[\s\S]*?\*/")
_STATIC_IMPORT_RE = re.compile(
    r"^\s*(?:import|export)\s+(?P<type_kw>type\s+)?(?:[\s\S]*?\s+from\s+)?['\"](?P<mod>[^'\"]+)['\"]"
)
_DYNAMIC_IMPORT_RE = re.compile(
    r"\b(?P<fn>import|require)\s*\(\s*['\"](?P<mod>[^'\"]+)['\"]\s*\)"
)


def _strip_block_comments_preserving_lines(source: str) -> str:
    def _repl(match: re.Match[str]) -> str:
        text = match.group(0)
        return "\n" * text.count("\n")

    return _BLOCK_COMMENT_RE.sub(_repl, source)


class TypescriptRegexExtractor(IImportExtractor):
    """Enhanced comment-aware regex import extractor for TypeScript, JavaScript, and Astro files."""

    def supports(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in TS_EXTENSIONS

    def extract(self, file_path: Path, project_root: Path) -> List[ImportRef]:
        try:
            raw_source = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            raise UnparseableFileError(file_path, exc) from exc

        cleaned = _strip_block_comments_preserving_lines(raw_source)
        refs: List[ImportRef] = []

        for idx, line in enumerate(cleaned.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue

            code_part = line.split("//")[0]

            m_static = _STATIC_IMPORT_RE.search(code_part)
            if m_static:
                mod = m_static.group("mod").strip()
                is_type = bool(m_static.group("type_kw"))
                refs.append(
                    ImportRef(
                        module=mod,
                        line=idx,
                        statement=stripped,
                        is_dynamic=False,
                        type_only=is_type,
                    )
                )
                continue

            for m_dyn in _DYNAMIC_IMPORT_RE.finditer(code_part):
                mod = m_dyn.group("mod").strip()
                refs.append(
                    ImportRef(
                        module=mod,
                        line=idx,
                        statement=stripped,
                        is_dynamic=True,
                        type_only=False,
                    )
                )

        return refs
