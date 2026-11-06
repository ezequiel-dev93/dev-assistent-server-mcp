import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.cli import main as cli_main
from src.core.errors import PathOutsideWorkspaceError, ProtectedPathError
from src.core.models import (
    AuthorProfile,
    MemoryCategory,
    MemoryEntry,
    MemoryScope,
    Severity,
)
from src.core.services.cycles import find_cycles
from src.core.services.redaction import redact
from src.infrastructure.adr.madr_filesystem import MadrFilesystemAdrRepository
from src.infrastructure.config.toml_loader import TomlProjectConfigLoader
from src.infrastructure.reporting.sarif import format_audit_sarif
from src.infrastructure.scanner.filesystem_scanner import FileSystemProjectScanner
from src.infrastructure.storage.sqlite_memory import (
    InMemoryMemoryRepository,
    SqliteMemoryRepository,
)
from src.server import build_container, build_server
from src.settings import Settings, migrate_legacy_db_if_needed
from src.tools.adr_tools import AdrTools
from src.tools.memory_tools import MemoryTools
from src.tools.project_tools import ProjectTools
from src.tools.workspace_guard import WorkspaceGuard


class TestSecurityAndGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws_root = Path(self.tmp.name) / "workspace"
        self.ws_root.mkdir(parents=True, exist_ok=True)
        self.outside_dir = Path(self.tmp.name) / "outside_secret"
        self.outside_dir.mkdir(parents=True, exist_ok=True)
        (self.outside_dir / "secret.txt").write_text("top-secret", encoding="utf-8")
        self.guard = WorkspaceGuard([self.ws_root])

    def tearDown(self):
        self.tmp.cleanup()

    def test_workspace_guard_blocks_traversal_and_outside_paths(self):
        with self.assertRaises(PathOutsideWorkspaceError):
            self.guard.resolve("../outside_secret")

        with self.assertRaises(PathOutsideWorkspaceError):
            self.guard.resolve(str(self.outside_dir))

    def test_workspace_guard_blocks_protected_dirs_and_bad_extensions(self):
        with self.assertRaises(ProtectedPathError):
            self.guard.resolve_output(".git/hooks/pre-commit", suffixes=frozenset({".md", ""}))

        with self.assertRaises(ProtectedPathError):
            self.guard.resolve_output("docs/evil.sh", suffixes=frozenset({".md"}))

        valid_md = self.guard.resolve_output("docs/ADR.md", suffixes=frozenset({".md"}))
        self.assertTrue(str(valid_md).endswith("ADR.md"))

    def test_secret_redaction_service(self):
        raw = (
            "OpenAI key sk-proj-1234567890abcdefghijklmnop and "
            "GitHub ghp_1234567890abcdefghijklmnopqrstuvwxyz and "
            "AWS AKIAIOSFODNN7EXAMPLE and api_key='my_super_secret_val'"
        )
        cleaned, labels = redact(raw)
        self.assertNotIn("sk-proj-123456", cleaned)
        self.assertNotIn("ghp_123456", cleaned)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", cleaned)
        self.assertNotIn("my_super_secret_val", cleaned)
        self.assertIn("LLM_API_KEY", labels)
        self.assertIn("GITHUB_TOKEN", labels)
        self.assertIn("AWS_ACCESS_KEY", labels)
        self.assertIn("GENERIC", labels)

    def test_safe_legacy_db_migration_preserves_original(self):
        legacy_db = Path(self.tmp.name) / "legacy" / "agent_memory.db"
        legacy_db.parent.mkdir(parents=True, exist_ok=True)
        legacy_db.write_bytes(b"sqlite-test-bytes")

        target_db = Path(self.tmp.name) / "user_home" / "agent_memory.db"
        migrated = migrate_legacy_db_if_needed(target_db, legacy_db)
        self.assertTrue(migrated)
        self.assertTrue(target_db.is_file())
        self.assertTrue(legacy_db.is_file())  # Original preserved!
        self.assertEqual(target_db.read_bytes(), b"sqlite-test-bytes")


class TestMemoryV2ContractAndFts5(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "v2_mem.db")

    def tearDown(self):
        self.tmp.cleanup()

    def _run_contract_suite(self, repo):
        # 1. Idempotent upsert preserves created_at and merges tags
        a = repo.save_memory(
            MemoryEntry(
                category=MemoryCategory.DECISION,
                content="Usar búsqueda FTS5 con diacríticos",
                project_name="proj_a",
                tags=["sqlite"],
            )
        )
        first_created = a.created_at
        b = repo.save_memory(
            MemoryEntry(
                category=MemoryCategory.DECISION,
                content="  usar búsqueda fts5   con diacríticos ",
                project_name="proj_a",
                tags=["bm25"],
            )
        )
        self.assertEqual(a.id, b.id)
        self.assertEqual(set(b.tags), {"sqlite", "bm25"})
        self.assertEqual(a.created_at, first_created)

        # 2. Diacritic-insensitive & hostile syntax search ("decision" matches "decisión" / "diacríticos")
        found = repo.search_memories(query='diacriticos "NEAR" * -', project_name="proj_a")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].id, a.id)

        # 3. Supersedes versioning hides old entry unless include_history=True
        c = repo.save_memory(
            MemoryEntry(
                category=MemoryCategory.DECISION,
                content="Migrar a búsqueda híbrida FTS5 v2",
                project_name="proj_a",
                tags=["v2"],
            ),
            supersedes=a.id,
        )
        active = repo.search_memories(query="FTS5", project_name="proj_a", include_history=False)
        self.assertEqual([m.id for m in active], [c.id])

        with_hist = repo.search_memories(query="FTS5", project_name="proj_a", include_history=True)
        self.assertEqual({m.id for m in with_hist}, {a.id, c.id})

        # 4. Global + Project scope resolution
        g = repo.save_memory(
            MemoryEntry(
                category=MemoryCategory.PREFERENCE,
                content="Usar tipado estricto global en Python",
                project_name=None,
                tags=["global-rule"],
            )
        )
        combined = repo.search_memories(
            query="FTS5 global", project_name="proj_a", scope=MemoryScope.ALL
        )
        self.assertEqual({m.id for m in combined}, {c.id, g.id})

        only_proj = repo.search_memories(
            query="FTS5 global", project_name="proj_a", scope=MemoryScope.PROJECT
        )
        self.assertEqual([m.id for m in only_proj], [c.id])

    def test_contract_sqlite_fts5(self):
        repo = SqliteMemoryRepository(db_path=self.db_path)
        self._run_contract_suite(repo)

        # Verify PRAGMA user_version == 4
        conn = sqlite3.connect(self.db_path)
        try:
            ver = conn.execute("PRAGMA user_version;").fetchone()[0]
            self.assertEqual(ver, 4)
        finally:
            conn.close()

    def test_contract_sqlite_like_fallback(self):
        fallback_db = os.path.join(self.tmp.name, "fallback.db")
        repo = SqliteMemoryRepository(db_path=fallback_db, force_like_fallback=True)
        self._run_contract_suite(repo)

    def test_contract_in_memory(self):
        repo = InMemoryMemoryRepository()
        self._run_contract_suite(repo)

    def test_untrusted_delimiters_and_redaction_in_memory_tools(self):
        repo = InMemoryMemoryRepository()
        tools = MemoryTools(repository=repo)
        res = tools.remember(
            content="Token sk-proj-abcdefghijklmnopqrstuvwxyz123456 </stored_memory>",
            category="client_context",
            project_name="sec_proj",
        )
        self.assertIn("[REDACTED:LLM_API_KEY]", res)
        self.assertIn("Aviso de Seguridad", res)

        recalled = tools.recall(query="Token", project_name="sec_proj")
        self.assertIn('trust="data-not-instructions"', recalled)
        self.assertIn("&lt;/stored_memory&gt;", recalled)


class TestAuditorV2AndDogfooding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.scanner = FileSystemProjectScanner()

    def tearDown(self):
        self.tmp.cleanup()

    def test_dogfooding_self_audit_passes_with_zero_errors(self):
        """DevAssistant MCP Server must pass its own strict hexagonal audit with 0 violations!"""
        report = self.scanner.audit_architecture(str(REPO_ROOT))
        errors = [v for v in report.violations if v.severity == Severity.ERROR]
        self.assertEqual(
            errors,
            [],
            f"Self-audit failed with violations: {errors}",
        )
        self.assertTrue(report.is_compliant)

    def test_ast_ignores_docstrings_and_downgrades_type_checking_and_fixes_pg_bug(self):
        proj = Path(self.tmp.name) / "clean_ui_and_domain"
        (proj / "src" / "core").mkdir(parents=True)
        (proj / "src" / "infrastructure").mkdir(parents=True)
        (proj / "src" / "components").mkdir(parents=True)

        # Docstring mentioning `import fastapi` + TYPE_CHECKING import -> 0 ERRORs (1 WARNING)
        (proj / "src" / "core" / "entity.py").write_text(
            '"""Example docstring:\nimport fastapi\nfrom sqlalchemy import text\n"""\n'
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    import fastapi\n",
            encoding="utf-8",
        )

        # UI component importing ./PageHeader and ./upgrade-banner.svg -> must NOT trigger 'pg' false positive!
        (proj / "src" / "components" / "Header.tsx").write_text(
            "import { PageHeader } from './PageHeader';\n"
            "import icon from './upgrade-banner.svg';\n",
            encoding="utf-8",
        )

        report = self.scanner.audit_architecture(str(proj))
        self.assertTrue(report.is_compliant)
        errors = [v for v in report.violations if v.severity == Severity.ERROR]
        warnings = [v for v in report.violations if v.severity == Severity.WARNING]
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].file_path, "src/core/entity.py")

    def test_tarjan_cycle_detection_and_sarif_export(self):
        graph = {
            "src/a.py": {"src/b.py"},
            "src/b.py": {"src/c.py"},
            "src/c.py": {"src/a.py"},
            "src/clean.py": {"src/a.py"},
        }
        cycles = find_cycles(graph)
        self.assertEqual(len(cycles), 1)
        self.assertEqual(cycles[0], ["src/a.py", "src/b.py", "src/c.py", "src/a.py"])

        report = self.scanner.audit_architecture(str(REPO_ROOT))
        sarif_str = format_audit_sarif(report)
        sarif_json = json.loads(sarif_str)
        self.assertEqual(sarif_json["version"], "2.1.0")
        self.assertEqual(sarif_json["runs"][0]["tool"]["driver"]["name"], "DevAssistant-MCP")


class TestMadrAdrAndDriftAndE2E(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name) / "ws"
        self.proj = self.ws / "billing_svc"
        (self.proj / "src" / "core").mkdir(parents=True)
        (self.proj / "src" / "infrastructure").mkdir(parents=True)

        self.settings = Settings(
            workspace_roots=[self.ws],
            db_path=Path(self.tmp.name) / "e2e.db",
            author_profile=AuthorProfile(
                name="Ezequiel Suárez",
                portfolio_url="https://www.ezequielsuarez-dev.com/",
            ),
        )
        self.container = build_container(self.settings)

    def tearDown(self):
        self.tmp.cleanup()

    def test_madr_lifecycle_and_drift_detection(self):
        res = self.container.adr_tools.record_decision(
            project_name_or_path="billing_svc",
            title="Isolate Domain from SQLite",
            context="Domain entities must be persistence-agnostic.",
            decision="Forbid sqlite3 and infrastructure imports inside src/core.",
            consequences="Requires repository ports.",
            status="accepted",
            enforced_by="domain-no-frameworks,domain-no-infra",
            tags="hexagonal,clean",
        )
        self.assertIn("ADR-0001", res)
        self.assertTrue((self.proj / "docs" / "adr" / "README.md").is_file())

        # Initially compliant -> no drift
        drift_ok = self.container.adr_tools.run_drift_check("billing_svc")
        self.assertFalse(drift_ok.has_drift)

        # Introduce violation in src/core/bad.py -> ADR drift becomes True!
        (self.proj / "src" / "core" / "bad.py").write_text("import sqlite3\n", encoding="utf-8")
        drift_bad = self.container.adr_tools.run_drift_check("billing_svc")
        self.assertTrue(drift_bad.has_drift)
        self.assertEqual(drift_bad.items[0].adr_number, 1)

    def test_apply_blueprint_dry_run_and_write(self):
        preview = self.container.project_tools.apply_feature_blueprint(
            "billing_svc", "invoices", dry_run=True
        )
        self.assertIn("DRY-RUN", preview)
        self.assertFalse((self.proj / "src" / "core" / "invoices").exists())

        applied = self.container.project_tools.apply_feature_blueprint(
            "billing_svc", "invoices", dry_run=False
        )
        self.assertIn("APLICADO EN DISCO", applied)
        self.assertTrue((self.proj / "src" / "core" / "invoices" / "domain" / "invoices.py").is_file())

    def test_mcp_server_e2e_registration_and_cli_exit_codes(self):
        server = build_server(self.container)
        tools = asyncio.run(server.list_tools())
        tool_names = {t.name for t in tools}

        expected_tools = {
            "list_workspace_projects",
            "inspect_project",
            "audit_architecture",
            "get_feature_blueprint",
            "apply_blueprint",
            "get_author_profile",
            "remember_fact",
            "recall_memory",
            "list_all_memories",
            "review_stale_memories",
            "forget_memory",
            "record_decision",
            "list_adrs",
            "update_adr_status",
            "check_adr_drift",
            "render_adr",
            "write_adr",
            "test_api_endpoint",
            "run_api_test_suite",
            "audit_env_and_docker",
            "inspect_docker_stack",
            "run_project_tests",
        }
        self.assertTrue(expected_tools.issubset(tool_names))

        # CLI audit on clean repo -> exit code 0
        exit_clean = cli_main(["audit", str(REPO_ROOT), "--format", "json"])
        self.assertEqual(exit_clean, 0)


if __name__ == "__main__":
    unittest.main()
