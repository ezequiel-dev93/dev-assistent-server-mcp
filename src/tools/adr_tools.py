from datetime import date
from pathlib import Path
from typing import List, Optional
from ..core.errors import AdrNotFoundError, DevAssistantError
from ..core.models import (
    AdrDriftReport,
    AdrEntry,
    AdrStatus,
    MemoryCategory,
    MemoryScope,
)
from ..core.ports import (
    IAdrRepository,
    IMemoryRepository,
    IProjectConfigLoader,
    IProjectScanner,
)
from ..core.services.drift import evaluate_adr_drift
from ..core.services.redaction import redact
from .markdown_presenter import render_adr_drift_report, render_adr_list
from .workspace_guard import WorkspaceGuard


class AdrTools:
    """Application tools for managing MADR files (`docs/adr/NNNN-slug.md`) and auditing ADR drift."""

    def __init__(
        self,
        adr_repo: IAdrRepository,
        scanner: IProjectScanner,
        config_loader: IProjectConfigLoader,
        guard: WorkspaceGuard,
        memory_repo: Optional[IMemoryRepository] = None,
    ) -> None:
        self.adr_repo = adr_repo
        self.scanner = scanner
        self.config_loader = config_loader
        self.guard = guard
        self.memory_repo = memory_repo

    def _resolve_project(self, project_name_or_path: str) -> Path:
        target = self.guard.resolve(project_name_or_path, must_exist=True)
        if not target.is_dir():
            raise FileNotFoundError(f"'{project_name_or_path}' is not a valid project directory.")
        return target

    def record_decision(
        self,
        project_name_or_path: str,
        title: str,
        context: str,
        decision: str,
        consequences: str = "",
        status: str = "accepted",
        supersedes: Optional[int] = None,
        enforced_by: Optional[str] = None,
        tags: Optional[str] = None,
    ) -> str:
        try:
            proj_root = self._resolve_project(project_name_or_path)
            existing = self.adr_repo.list_adrs(proj_root)
            next_num = (max((a.number for a in existing), default=0)) + 1

            try:
                status_enum = AdrStatus(status.lower().strip())
            except ValueError:
                status_enum = AdrStatus.PROPOSED

            enforced_list = (
                [r.strip() for r in enforced_by.split(",") if r.strip()]
                if enforced_by
                else []
            )
            tag_list = (
                [t.strip() for t in tags.split(",") if t.strip()]
                if tags
                else []
            )

            clean_title, _ = redact(title.strip())
            clean_ctx, _ = redact(context.strip())
            clean_dec, _ = redact(decision.strip())
            clean_cons, _ = redact(consequences.strip())

            new_adr = AdrEntry(
                number=next_num,
                title=clean_title,
                status=status_enum,
                date=date.today().isoformat(),
                context=clean_ctx,
                decision=clean_dec,
                consequences=clean_cons,
                supersedes=supersedes,
                enforced_by=enforced_list,
                tags=tag_list,
            )

            saved = self.adr_repo.save_adr(proj_root, new_adr)

            if supersedes is not None:
                old_adr = self.adr_repo.get_adr(proj_root, supersedes)
                if old_adr is not None:
                    old_adr.status = AdrStatus.SUPERSEDED
                    old_adr.superseded_by = saved.number
                    self.adr_repo.save_adr(proj_root, old_adr)

            return (
                f"✅ **ADR-{saved.number:04d}** creado exitosamente en `{saved.file_path}`\n"
                f"- **Título:** {saved.title}\n"
                f"- **Estado:** `{saved.status.value}`\n"
                f"- **Reglas vinculadas (`enforced_by`):** {', '.join(saved.enforced_by) if saved.enforced_by else 'ninguna'}"
            )
        except (DevAssistantError, FileNotFoundError, ValueError) as exc:
            return f"Error: {exc}"

    def list_project_adrs(self, project_name_or_path: str) -> str:
        try:
            proj_root = self._resolve_project(project_name_or_path)
            adrs = self.adr_repo.list_adrs(proj_root)
            return render_adr_list(proj_root.name, adrs)
        except (DevAssistantError, FileNotFoundError, ValueError) as exc:
            return f"Error: {exc}"

    def update_status(
        self,
        project_name_or_path: str,
        adr_number: int,
        new_status: str,
        superseded_by: Optional[int] = None,
    ) -> str:
        try:
            proj_root = self._resolve_project(project_name_or_path)
            target = self.adr_repo.get_adr(proj_root, adr_number)
            if target is None:
                raise AdrNotFoundError(f"ADR-{adr_number:04d} not found in '{proj_root.name}'.")

            try:
                status_enum = AdrStatus(new_status.lower().strip())
            except ValueError as exc:
                raise ValueError(f"Invalid ADR status '{new_status}'.") from exc

            target.status = status_enum
            if superseded_by is not None:
                target.superseded_by = superseded_by
            self.adr_repo.save_adr(proj_root, target)

            if superseded_by is not None:
                newer = self.adr_repo.get_adr(proj_root, superseded_by)
                if newer is not None and newer.supersedes != adr_number:
                    newer.supersedes = adr_number
                    self.adr_repo.save_adr(proj_root, newer)

            return f"✅ Estado de **ADR-{adr_number:04d}** actualizado a `{status_enum.value}`."
        except (DevAssistantError, FileNotFoundError, ValueError) as exc:
            return f"Error: {exc}"

    def run_drift_check(self, project_name_or_path: str) -> AdrDriftReport:
        proj_root = self._resolve_project(project_name_or_path)
        adrs = self.adr_repo.list_adrs(proj_root)
        detail = self.scanner.inspect_project(str(proj_root))
        rules = self.config_loader.load(
            proj_root,
            [a.value for a in detail.detected_architectures],
            detail.stack.value,
        )
        audit_report = self.scanner.audit_architecture(str(proj_root))
        return evaluate_adr_drift(
            project_name=proj_root.name,
            adrs=adrs,
            rules=rules,
            audit_report=audit_report,
        )

    def check_adr_drift(self, project_name_or_path: str) -> str:
        try:
            report = self.run_drift_check(project_name_or_path)
            return render_adr_drift_report(report)
        except (DevAssistantError, FileNotFoundError, ValueError) as exc:
            return f"Error: {exc}"

    def import_candidates_from_memory(
        self, project_name_or_path: str, dry_run: bool = True
    ) -> str:
        """CLI helper to promote `architecture` and `decision` SQLite memories into MADR files."""
        if self.memory_repo is None:
            return "Error: Memory repository is not attached."
        proj_root = self._resolve_project(project_name_or_path)
        memories = self.memory_repo.list_memories(
            project_name=proj_root.name,
            scope=MemoryScope.PROJECT,
            include_history=False,
            limit=200,
        )
        candidates = [
            m
            for m in reversed(memories)
            if m.category in (MemoryCategory.ARCHITECTURE, MemoryCategory.DECISION)
        ]
        if not candidates:
            return f"No memory candidates found for project '{proj_root.name}'."

        existing = self.adr_repo.list_adrs(proj_root)
        existing_decisions = {a.decision.strip().lower() for a in existing}
        next_num = max((a.number for a in existing), default=0) + 1
        created_titles: List[str] = []

        for mem in candidates:
            if mem.content.strip().lower() in existing_decisions:
                continue
            title_preview = mem.content.strip().split(".")[0][:70]
            if not dry_run:
                adr = AdrEntry(
                    number=next_num,
                    title=title_preview,
                    status=AdrStatus.PROPOSED,
                    date=(mem.created_at.date() if mem.created_at else date.today()).isoformat(),
                    context=f"Promoted from persistent SQLite memory #{mem.id} ({mem.category.value}).",
                    decision=mem.content.strip(),
                    consequences="Pending team review.",
                    tags=list(mem.tags),
                )
                self.adr_repo.save_adr(proj_root, adr)
            created_titles.append(f"ADR-{next_num:04d}: {title_preview}")
            next_num += 1

        mode = "DRY-RUN" if dry_run else "IMPORTED"
        return f"[{mode}] {len(created_titles)} ADR(s) processed:\n" + "\n".join(
            f"- {t}" for t in created_titles
        )
