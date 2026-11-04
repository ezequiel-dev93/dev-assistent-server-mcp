import os
import sys
import tempfile
import unittest

# Asegurar que src esté en el path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.models import ArchitecturePattern, MemoryCategory, MemoryEntry, ProjectStack
from src.infrastructure.scanner.filesystem_scanner import FileSystemProjectScanner
from src.infrastructure.storage.sqlite_memory import SqliteMemoryRepository
from src.tools.memory_tools import MemoryTools
from src.tools.project_tools import ProjectTools


class TestSqliteMemoryRepository(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_memory.db")
        self.repo = SqliteMemoryRepository(db_path=self.db_path)
        self.tools = MemoryTools(repository=self.repo)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_save_and_recall_memory(self):
        res = self.tools.remember(
            content="El cliente de Colombia requiere cotizaciones en pesos COP",
            category="client_context",
            project_name="concesionaria",
            tags="colombia, ventas, cop",
        )
        self.assertIn("✅ Recuerdo guardado exitosamente", res)

        search_res = self.tools.recall(query="cotizaciones", project_name="concesionaria")
        self.assertIn("pesos COP", search_res)
        self.assertIn("client_context", search_res)

    def test_multi_term_search_and_upsert_deduplication(self):
        # Guardar dos veces el mismo contenido con diferentes tags -> debe hacer Upsert (mismo ID)
        first = self.repo.save_memory(
            MemoryEntry(
                category=MemoryCategory.ARCHITECTURE,
                content="Usar FastAPI con Pydantic v2 y autenticación JWT en adaptadores",
                project_name="api_core",
                tags=["fastapi", "pydantic"],
            )
        )
        second = self.repo.save_memory(
            MemoryEntry(
                category=MemoryCategory.ARCHITECTURE,
                content="Usar FastAPI con Pydantic v2 y autenticación JWT en adaptadores",
                project_name="api_core",
                tags=["jwt", "security"],
            )
        )
        self.assertEqual(first.id, second.id)
        self.assertIn("fastapi", second.tags)
        self.assertIn("jwt", second.tags)

        # Búsqueda multi-término con palabras separadas ("fastapi jwt")
        results = self.repo.search_memories(query="fastapi jwt", project_name="api_core")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, first.id)

    def test_export_adr_markdown(self):
        self.tools.remember(
            content="El dominio no puede importar SQLAlchemy directamente",
            category="architecture",
            project_name="demo_app",
            tags="hexagonal,domain",
        )
        self.tools.remember(
            content="Se eligió PostgreSQL 16 con pgvector para búsqueda híbrida",
            category="decision",
            project_name="demo_app",
            tags="postgres,rag",
        )
        adr_path = os.path.join(self.temp_dir.name, "docs", "ADR.md")
        adr_output = self.tools.export_adr(project_name="demo_app", output_path=adr_path)
        self.assertTrue(os.path.isfile(adr_path))
        self.assertIn("Architecture Decision Records (ADR)", adr_output)
        self.assertIn("SQLAlchemy", adr_output)
        self.assertIn("pgvector", adr_output)

    def test_delete_memory(self):
        entry = self.repo.save_memory(
            MemoryEntry(
                category=MemoryCategory.PREFERENCE,
                content="Prefiere tipado estricto en TypeScript",
            )
        )
        self.assertIsNotNone(entry.id)

        del_res = self.tools.forget(entry.id)
        self.assertIn("eliminado exitosamente", del_res)

        search_res = self.tools.recall(query="TypeScript")
        self.assertIn("No se encontraron recuerdos", search_res)


class TestProjectScannerAndBlueprints(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.scanner = FileSystemProjectScanner()
        self.tools = ProjectTools(scanner=self.scanner, default_workspace=self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_scaffold_hexagonal_blueprint(self):
        # Simular proyecto con arquitectura hexagonal
        proj_dir = os.path.join(self.temp_dir.name, "demo_fastapi")
        os.makedirs(os.path.join(proj_dir, "core", "domain"), exist_ok=True)
        os.makedirs(os.path.join(proj_dir, "infrastructure", "adapters"), exist_ok=True)

        blueprint = self.tools.scaffold_feature_blueprint("demo_fastapi", "orders")
        self.assertIn("src/core/orders/", blueprint)
        self.assertIn("ports/", blueprint)
        self.assertIn("use_cases/", blueprint)
        self.assertIn("adapters/", blueprint)

    def test_scaffold_screaming_blueprint(self):
        # Simular proyecto con screaming architecture
        proj_dir = os.path.join(self.temp_dir.name, "demo_astro")
        os.makedirs(os.path.join(proj_dir, "src", "modules"), exist_ok=True)

        blueprint = self.tools.scaffold_feature_blueprint("demo_astro", "billing")
        self.assertIn("src/modules/billing/", blueprint)
        self.assertIn("components/", blueprint)
        self.assertIn("services/", blueprint)
        self.assertIn("types/", blueprint)

    def test_audit_architecture_detects_violations_and_compliance(self):
        proj_dir = os.path.join(self.temp_dir.name, "hex_project")
        domain_dir = os.path.join(proj_dir, "src", "core", "domain")
        infra_dir = os.path.join(proj_dir, "src", "infrastructure")
        os.makedirs(domain_dir, exist_ok=True)
        os.makedirs(infra_dir, exist_ok=True)

        # 1. Crear archivo limpio en domain
        clean_file = os.path.join(domain_dir, "order.py")
        with open(clean_file, "w", encoding="utf-8") as f:
            f.write("from dataclasses import dataclass\n\n@dataclass\nclass Order:\n    id: int\n")

        clean_report = self.tools.audit_project_architecture("hex_project")
        self.assertIn("100% COMPLIANT", clean_report)

        # 2. Introducir una violación en domain (importar fastapi y sqlite3)
        bad_file = os.path.join(domain_dir, "bad_service.py")
        with open(bad_file, "w", encoding="utf-8") as f:
            f.write("import sqlite3\nfrom fastapi import HTTPException\n")

        violation_report = self.tools.audit_project_architecture("hex_project")
        self.assertIn("VIOLACIONES DETECTADAS", violation_report)
        self.assertIn("bad_service.py", violation_report)
        self.assertIn("Hexagonal Architecture Violation", violation_report)


if __name__ == "__main__":
    unittest.main()
