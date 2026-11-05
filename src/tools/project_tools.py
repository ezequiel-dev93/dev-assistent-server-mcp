from pathlib import Path
from typing import Optional
from ..core.errors import DevAssistantError
from ..core.models import ArchitectureAuditReport, BlueprintPlan
from ..core.ports import IProjectScanner
from ..core.services.blueprint_planner import plan_feature_blueprint
from .markdown_presenter import (
    render_audit_report,
    render_blueprint_plan,
    render_project_detail,
    render_project_list,
)
from .workspace_guard import WorkspaceGuard


class ProjectTools:
    """Application tools for workspace scanning, architecture auditing, and feature blueprinting."""

    def __init__(
        self,
        scanner: IProjectScanner,
        default_workspace: str = "../",
        guard: Optional[WorkspaceGuard] = None,
    ) -> None:
        self.scanner = scanner
        self.guard = guard or WorkspaceGuard([default_workspace])
        self.default_workspace = str(self.guard.primary_root)

    def _resolve_target_dir(self, path_or_name: Optional[str]) -> Path:
        target = self.guard.resolve(path_or_name or "", must_exist=True)
        if not target.is_dir():
            raise FileNotFoundError(f"'{path_or_name}' is not a valid directory.")
        return target

    def list_projects(self, workspace_path: Optional[str] = None) -> str:
        try:
            target = self._resolve_target_dir(workspace_path)
        except (DevAssistantError, FileNotFoundError, ValueError) as exc:
            return f"Error: {exc}"

        projects = self.scanner.scan_workspace(str(target))
        return render_project_list(str(target), projects)

    def inspect_project(self, project_path_or_name: str) -> str:
        try:
            target = self._resolve_target_dir(project_path_or_name)
        except (DevAssistantError, FileNotFoundError, ValueError) as exc:
            return f"Error: {exc}"

        detail = self.scanner.inspect_project(str(target))
        return render_project_detail(detail)

    def run_audit(self, project_path_or_name: str) -> ArchitectureAuditReport:
        target = self._resolve_target_dir(project_path_or_name)
        return self.scanner.audit_architecture(str(target))

    def audit_project_architecture(self, project_path_or_name: str) -> str:
        try:
            report = self.run_audit(project_path_or_name)
        except (DevAssistantError, FileNotFoundError, ValueError) as exc:
            return f"Error: {exc}"

        return render_audit_report(report)

    def build_blueprint_plan(
        self, project_path_or_name: str, feature_name: str
    ) -> tuple[Path, BlueprintPlan]:
        target = self._resolve_target_dir(project_path_or_name)
        detail = self.scanner.inspect_project(str(target))
        plan = plan_feature_blueprint(
            project_name=detail.name,
            feature_name=feature_name,
            stack=detail.stack,
            architectures=detail.detected_architectures,
            technologies=detail.technologies,
        )
        return target, plan

    def scaffold_feature_blueprint(
        self, project_path_or_name: str, feature_name: str
    ) -> str:
        try:
            _, plan = self.build_blueprint_plan(project_path_or_name, feature_name)
        except (DevAssistantError, FileNotFoundError, ValueError) as exc:
            return f"Error: {exc}"

        return render_blueprint_plan(plan)

    def apply_feature_blueprint(
        self,
        project_path_or_name: str,
        feature_name: str,
        dry_run: bool = True,
    ) -> str:
        """Applies (or previews when dry_run=True) a feature blueprint inside the guarded workspace without overwriting existing files."""
        try:
            project_root, plan = self.build_blueprint_plan(project_path_or_name, feature_name)
            plan.dry_run = dry_run

            allowed_exts = frozenset({".py", ".ts", ".tsx", ".js", ".jsx", ".astro", ".md"})
            for item in plan.files:
                dest = self.guard.resolve_output(
                    item.relative_path,
                    base_dir=project_root,
                    suffixes=allowed_exts,
                )
                if dest.exists():
                    item.action = "skip_existing"
                    plan.skipped_files.append(item.relative_path)
                else:
                    item.action = "create"
                    plan.created_files.append(item.relative_path)
                    if not dry_run:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_text(item.template_content, encoding="utf-8")

            return render_blueprint_plan(plan)
        except (DevAssistantError, FileNotFoundError, ValueError) as exc:
            return f"Error: {exc}"
