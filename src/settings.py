import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

from .core.models import AuthorProfile

# Configure logger exclusively on stderr so stdout remains clean for MCP stdio JSON-RPC
logger = logging.getLogger("dev_assistant_mcp")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("[DevAssistant-MCP] %(levelname)s: %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


def default_user_dir() -> Path:
    return Path.home() / ".dev-assistant"


def _load_user_config_toml(config_path: Path) -> Dict[str, Any]:
    if not config_path.is_file():
        return {}
    try:
        return tomllib.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not parse user config '%s': %s", config_path, exc)
        return {}


def migrate_legacy_db_if_needed(target_db: Path, legacy_db: Optional[Path]) -> bool:
    """
    Copies (never moves/deletes) the legacy `<repo>/data/agent_memory.db` into the user-scoped
    default `~/.dev-assistant/agent_memory.db` if the new DB does not exist yet.
    """
    if target_db.exists() or legacy_db is None or not legacy_db.is_file():
        return False
    try:
        if legacy_db.resolve() == target_db.resolve():
            return False
    except OSError:
        pass

    target_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy_db, target_db)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(legacy_db) + suffix)
        if sidecar.is_file():
            shutil.copy2(sidecar, Path(str(target_db) + suffix))

    logger.info(
        "Migrated legacy SQLite memory DB from '%s' to '%s' (original preserved).",
        legacy_db,
        target_db,
    )
    return True


@dataclass
class Settings:
    workspace_roots: List[Path] = field(default_factory=list)
    db_path: Path = field(default_factory=lambda: default_user_dir() / "agent_memory.db")
    log_level: str = "INFO"
    author_profile: AuthorProfile = field(default_factory=AuthorProfile)

    @classmethod
    def from_env(
        cls,
        user_config_path: Optional[Path] = None,
        legacy_repo_dir: Optional[Path] = None,
    ) -> "Settings":
        cfg_file = user_config_path or (default_user_dir() / "config.toml")
        user_cfg = _load_user_config_toml(cfg_file)

        log_lvl = (
            os.getenv("DEVASSISTANT_LOG_LEVEL")
            or os.getenv("LOG_LEVEL")
            or str(user_cfg.get("log_level", "INFO"))
        ).upper()
        logger.setLevel(getattr(logging, log_lvl, logging.INFO))

        # 1. Resolve Workspace Roots
        roots: List[Path] = []
        env_roots = os.getenv("DEVASSISTANT_WORKSPACE_ROOTS") or os.getenv(
            "DEVASSISTANT_WORKSPACE_ROOT"
        )
        legacy_root = os.getenv("WORKSPACE_ROOT")

        if env_roots:
            for part in env_roots.split(os.pathsep):
                if part.strip():
                    roots.append(Path(part.strip()).expanduser().resolve())
        elif legacy_root and legacy_root.strip():
            roots.append(Path(legacy_root.strip()).expanduser().resolve())
        else:
            cfg_roots = user_cfg.get("workspace", {}).get("roots", [])
            if isinstance(cfg_roots, list):
                for r in cfg_roots:
                    if str(r).strip():
                        roots.append(Path(str(r).strip()).expanduser().resolve())

        if not roots:
            if legacy_repo_dir is not None and legacy_repo_dir.parent.is_dir():
                roots.append(legacy_repo_dir.parent.resolve())
            else:
                roots.append(Path.cwd().resolve())

        # 2. Resolve Database Path + Safe Legacy Auto-Migration
        env_db = os.getenv("DEVASSISTANT_DB_PATH")
        legacy_env_db = os.getenv("MEMORY_DB_PATH")
        cfg_db = user_cfg.get("storage", {}).get("db_path")

        if env_db and env_db.strip():
            db_path = Path(env_db.strip()).expanduser().resolve()
        elif legacy_env_db and legacy_env_db.strip():
            db_path = Path(legacy_env_db.strip()).expanduser().resolve()
        elif cfg_db and str(cfg_db).strip():
            db_path = Path(str(cfg_db).strip()).expanduser().resolve()
        else:
            db_path = (default_user_dir() / "agent_memory.db").resolve()
            legacy_candidate = (
                (legacy_repo_dir / "data" / "agent_memory.db")
                if legacy_repo_dir is not None
                else None
            )
            migrate_legacy_db_if_needed(db_path, legacy_candidate)

        # 3. Resolve Author Profile (User-scoped, never committed to project repos)
        prof_cfg = user_cfg.get("profile", {}) if isinstance(user_cfg.get("profile"), dict) else {}
        profile = AuthorProfile(
            name=os.getenv("DEVASSISTANT_AUTHOR_NAME") or prof_cfg.get("name"),
            portfolio_url=os.getenv("DEVASSISTANT_AUTHOR_URL") or prof_cfg.get("url"),
            github_url=os.getenv("DEVASSISTANT_AUTHOR_GITHUB") or prof_cfg.get("github"),
            linkedin_url=os.getenv("DEVASSISTANT_AUTHOR_LINKEDIN") or prof_cfg.get("linkedin"),
            email=os.getenv("DEVASSISTANT_AUTHOR_EMAIL") or prof_cfg.get("email"),
        )

        return cls(
            workspace_roots=roots,
            db_path=db_path,
            log_level=log_lvl,
            author_profile=profile,
        )
