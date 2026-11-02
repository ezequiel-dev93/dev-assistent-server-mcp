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


if __name__ == "__main__":
    unittest.main()
