from pathlib import Path
from typing import FrozenSet, List, Sequence, Union
from ..core.errors import PathOutsideWorkspaceError, ProtectedPathError

PROTECTED_DIR_NAMES = frozenset({".git", ".github", ".vscode", ".idea"})


class WorkspaceGuard:
    """
    Security boundary ensuring all filesystem reads and writes remain strictly
    inside configured workspace roots (preventing path traversal and symlink escapes).
    """

    def __init__(self, roots: Sequence[Union[str, Path]]) -> None:
        resolved_roots: List[Path] = []
        for r in roots:
            p = Path(r).expanduser().resolve()
            if p not in resolved_roots:
                resolved_roots.append(p)
        if not resolved_roots:
            raise ValueError("WorkspaceGuard requires at least one workspace root.")
        self.roots: List[Path] = resolved_roots

    @property
    def primary_root(self) -> Path:
        return self.roots[0]

    def add_root(self, root: Union[str, Path]) -> None:
        p = Path(root).expanduser().resolve()
        if p not in self.roots:
            self.roots.append(p)

    def _is_within_any_root(self, resolved_path: Path) -> bool:
        for root in self.roots:
            try:
                # Case-normalized check on Windows while preserving Path.is_relative_to semantics
                if resolved_path.is_relative_to(root):
                    return True
                if (
                    Path(str(resolved_path).lower()).is_relative_to(
                        Path(str(root).lower())
                    )
                    and resolved_path.drive.lower() == root.drive.lower()
                    and resolved_path.drive != ""
                ):
                    return True
            except ValueError:
                continue
        return False

    def resolve(self, user_path: str, *, must_exist: bool = True) -> Path:
        cleaned = user_path.strip() if user_path else ""
        if not cleaned:
            target = self.primary_root
            if must_exist and not target.exists():
                raise FileNotFoundError("Primary workspace root does not exist.")
            return target

        raw = Path(cleaned)
        candidates: List[Path] = []
        if raw.is_absolute():
            candidates.append(raw)
        else:
            for root in self.roots:
                candidates.append(root / raw)

        for cand in candidates:
            resolved = cand.resolve(strict=False)
            if not self._is_within_any_root(resolved):
                continue
            if must_exist and not resolved.exists():
                continue
            return resolved

        # Distinguish outside-workspace attack from non-existent inside-workspace path
        first_resolved = candidates[0].resolve(strict=False)
        if not self._is_within_any_root(first_resolved):
            raise PathOutsideWorkspaceError(
                f"Access denied: path '{cleaned}' resolves outside configured WORKSPACE_ROOTS."
            )
        raise FileNotFoundError(f"Path or project '{cleaned}' was not found inside workspace.")

    def resolve_output(
        self,
        user_path: str,
        *,
        base_dir: Path | None = None,
        suffixes: FrozenSet[str] = frozenset({".md"}),
    ) -> Path:
        cleaned = user_path.strip()
        if not cleaned:
            raise ValueError("Output file path cannot be empty.")

        raw = Path(cleaned)
        anchor = base_dir.resolve() if base_dir is not None else self.primary_root
        candidate = raw if raw.is_absolute() else (anchor / raw)
        resolved = candidate.resolve(strict=False)

        if not self._is_within_any_root(resolved):
            raise PathOutsideWorkspaceError(
                f"Access denied: output path '{cleaned}' resolves outside configured WORKSPACE_ROOTS."
            )

        if suffixes and resolved.suffix.lower() not in suffixes:
            allowed = ", ".join(sorted(suffixes))
            raise ProtectedPathError(
                f"Disallowed output extension '{resolved.suffix}'. Allowed extensions: {allowed}"
            )

        # Check relative parts from workspace root for protected directories (case-safe on Windows)
        res_parts_low = [p.lower() for p in resolved.parts]
        for root in self.roots:
            root_parts_low = [p.lower() for p in root.parts]
            if res_parts_low[: len(root_parts_low)] == root_parts_low:
                rel_parts = res_parts_low[len(root_parts_low) :]
                if any(part in PROTECTED_DIR_NAMES for part in rel_parts):
                    raise ProtectedPathError(
                        "Cannot write files inside protected directories (.git, .github, .vscode)."
                    )

        return resolved
