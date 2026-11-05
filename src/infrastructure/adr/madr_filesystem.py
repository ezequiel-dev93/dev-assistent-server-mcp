import re
from pathlib import Path
from typing import Dict, List, Optional
from ...core.models import AdrEntry, AdrStatus
from ...core.ports import IAdrRepository

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_ADR_FILENAME_RE = re.compile(r"^(\d{4})-(.+)\.md$")


def _slugify(title: str) -> str:
    slug = _SLUG_RE.sub("-", title.strip().lower()).strip("-")
    return slug[:60] or "decision"


def _parse_list_value(raw: str) -> List[str]:
    val = raw.strip()
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        return [
            item.strip().strip("'\"")
            for item in inner.split(",")
            if item.strip().strip("'\"")
        ]
    return [x.strip() for x in val.split(",") if x.strip()]


def _parse_optional_int(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    val = raw.strip().lower()
    if val in ("null", "none", ""):
        return None
    try:
        return int(val)
    except ValueError:
        return None


def _render_madr_markdown(adr: AdrEntry) -> str:
    enforced_str = "[" + ", ".join(adr.enforced_by) + "]"
    tags_str = "[" + ", ".join(adr.tags) + "]"
    sup_str = str(adr.supersedes) if adr.supersedes is not None else "null"
    sup_by_str = str(adr.superseded_by) if adr.superseded_by is not None else "null"

    lines = [
        "---",
        f"id: {adr.number:04d}",
        f"title: {adr.title}",
        f"status: {adr.status.value}",
        f"date: {adr.date}",
        f"supersedes: {sup_str}",
        f"superseded_by: {sup_by_str}",
        f"enforced_by: {enforced_str}",
        f"tags: {tags_str}",
        "---",
        "",
        f"# ADR-{adr.number:04d}: {adr.title}",
        "",
        "## Context",
        "",
        adr.context.strip() or "N/A",
        "",
        "## Decision",
        "",
        adr.decision.strip() or "N/A",
        "",
        "## Consequences",
        "",
        adr.consequences.strip() or "N/A",
        "",
    ]
    return "\n".join(lines)


def _parse_madr_markdown(content: str, fallback_number: int, rel_path: str) -> AdrEntry:
    meta: Dict[str, str] = {}
    body = content

    if content.startswith("---\n"):
        end_idx = content.find("\n---", 4)
        if end_idx != -1:
            fm_block = content[4:end_idx]
            body = content[end_idx + 4 :].lstrip("\n")
            for line in fm_block.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip().lower()] = v.strip()

    sections: Dict[str, List[str]] = {"context": [], "decision": [], "consequences": []}
    current_sec: Optional[str] = None
    title_from_h1 = ""

    for line in body.splitlines():
        if line.startswith("# ") and not title_from_h1:
            raw_h1 = line[2:].strip()
            title_from_h1 = re.sub(r"^ADR-\d+\s*:\s*", "", raw_h1)
            continue
        if line.startswith("## "):
            sec_name = line[3:].strip().lower()
            if "context" in sec_name:
                current_sec = "context"
            elif "decision" in sec_name:
                current_sec = "decision"
            elif "consequence" in sec_name:
                current_sec = "consequences"
            else:
                current_sec = None
            continue
        if current_sec is not None:
            sections[current_sec].append(line)

    num = _parse_optional_int(meta.get("id")) or fallback_number
    status_raw = meta.get("status", "proposed").lower()
    try:
        status = AdrStatus(status_raw)
    except ValueError:
        status = AdrStatus.PROPOSED

    return AdrEntry(
        number=num,
        title=meta.get("title") or title_from_h1 or f"ADR {num:04d}",
        status=status,
        date=meta.get("date", ""),
        context="\n".join(sections["context"]).strip(),
        decision="\n".join(sections["decision"]).strip(),
        consequences="\n".join(sections["consequences"]).strip(),
        supersedes=_parse_optional_int(meta.get("supersedes")),
        superseded_by=_parse_optional_int(meta.get("superseded_by")),
        enforced_by=_parse_list_value(meta.get("enforced_by", "[]")),
        tags=_parse_list_value(meta.get("tags", "[]")),
        file_path=rel_path,
    )


class MadrFilesystemAdrRepository(IAdrRepository):
    """Stores MADR-formatted ADRs under `<project_root>/docs/adr/NNNN-slug.md` with an auto-generated index."""

    def _adr_dir(self, project_root: Path) -> Path:
        return project_root / "docs" / "adr"

    def list_adrs(self, project_root: Path) -> List[AdrEntry]:
        adr_dir = self._adr_dir(project_root)
        if not adr_dir.is_dir():
            return []

        entries: List[AdrEntry] = []
        for fpath in sorted(adr_dir.iterdir()):
            if not fpath.is_file():
                continue
            m = _ADR_FILENAME_RE.match(fpath.name)
            if not m:
                continue
            num = int(m.group(1))
            rel = fpath.relative_to(project_root).as_posix()
            text = fpath.read_text(encoding="utf-8", errors="replace")
            entries.append(_parse_madr_markdown(text, num, rel))

        entries.sort(key=lambda a: a.number)
        return entries

    def get_adr(self, project_root: Path, number: int) -> Optional[AdrEntry]:
        for adr in self.list_adrs(project_root):
            if adr.number == number:
                return adr
        return None

    def save_adr(self, project_root: Path, adr: AdrEntry) -> AdrEntry:
        adr_dir = self._adr_dir(project_root)
        adr_dir.mkdir(parents=True, exist_ok=True)

        # If an existing file with the same ADR number exists, reuse its path so updates don't duplicate files
        target_file: Optional[Path] = None
        for existing_file in adr_dir.iterdir():
            if existing_file.is_file():
                m = _ADR_FILENAME_RE.match(existing_file.name)
                if m and int(m.group(1)) == adr.number:
                    target_file = existing_file
                    break

        if target_file is None:
            slug = _slugify(adr.title)
            target_file = adr_dir / f"{adr.number:04d}-{slug}.md"

        adr.file_path = target_file.relative_to(project_root).as_posix()
        target_file.write_text(_render_madr_markdown(adr), encoding="utf-8")
        self._regenerate_index(project_root)
        return adr

    def _regenerate_index(self, project_root: Path) -> None:
        adrs = self.list_adrs(project_root)
        adr_dir = self._adr_dir(project_root)
        lines = [
            f"# Architecture Decision Records (MADR) — `{project_root.name}`",
            "",
            "| ADR | Title | Status | Date | Enforced By |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
        for a in adrs:
            fname = Path(a.file_path).name if a.file_path else f"{a.number:04d}.md"
            enf = ", ".join(f"`{r}`" for r in a.enforced_by) if a.enforced_by else "—"
            lines.append(
                f"| [ADR-{a.number:04d}]({fname}) | {a.title} | `{a.status.value}` | {a.date} | {enf} |"
            )
        lines.append("")
        (adr_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")
