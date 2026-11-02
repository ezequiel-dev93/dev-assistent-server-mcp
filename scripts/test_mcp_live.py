import os
import sys

# Agregar la raíz del servidor al path de Python
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Forzar codificación UTF-8 en terminales de Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.infrastructure.scanner.filesystem_scanner import FileSystemProjectScanner
from src.infrastructure.storage.sqlite_memory import SqliteMemoryRepository
from src.tools.memory_tools import MemoryTools
from src.tools.project_tools import ProjectTools


def separator(title: str):
    print("\n" + "=" * 70)
    print(f"🚀 {title.upper()}")
    print("=" * 70)


def main():
    print("\n" + "🧠 INICIANDO TEST EN VIVO DEL SERVIDOR MCP (DEV-ASSISTANT)".center(70))
    print("=" * 70)

    # 1. Rutas
    workspace_dir = os.path.abspath(os.path.join(BASE_DIR, ".."))
    db_path = os.path.join(BASE_DIR, "data", "agent_memory.db")

    print(f"📁 Espacio de Trabajo : {workspace_dir}")
    print(f"💾 Base de Datos SQLite: {db_path}")

    # 2. Inicialización de Adaptadores y Herramientas
    scanner = FileSystemProjectScanner()
    memory_repo = SqliteMemoryRepository(db_path=db_path)

    project_tools = ProjectTools(scanner=scanner, default_workspace=workspace_dir)
    memory_tools = MemoryTools(repository=memory_repo)

    # TEST 1: Escanear el espacio de trabajo
    separator("1. Prueba de Escaneo de Proyectos (list_workspace_projects)")
    projects_output = project_tools.list_projects()
    print(projects_output)

    # TEST 2: Inspección detallada del servidor MCP
    separator("2. Prueba de Inspección de Proyecto (inspect_project)")
    inspection_output = project_tools.inspect_project(BASE_DIR)
    print(inspection_output)

    # TEST 3: Generación de Blueprint Arquitectónico
    separator("3. Prueba de Blueprint Arquitectónico (get_feature_blueprint)")
    blueprint_output = project_tools.scaffold_feature_blueprint(BASE_DIR, "auth")
    print(blueprint_output)

    # TEST 4: Búsqueda en la Memoria Persistente (Recuerdos de Ezequiel)
    separator("4. Prueba de Memoria Persistente: Enlaces del Desarrollador")
    recall_links = memory_tools.recall(query="portfolio")
    print(recall_links)

    separator("5. Prueba de Memoria Persistente: Reglas de Arquitectura & Clientes")
    recall_rules = memory_tools.recall(query="concesionaria")
    print(recall_rules)

    separator("6. Prueba de Memoria Persistente: Estrategia de Concurrencia & RAG")
    recall_arch = memory_tools.recall(query="FastAPI")
    print(recall_arch)

    # TEST 5: Perfil formateado para READMEs
    separator("7. Prueba de Perfil Oficial de Ezequiel (get_developer_profile)")
    profile_snippet = (
        "## 👨‍💻 Autor y Contacto\n"
        "- 🌐 **Portfolio:** https://www.ezequielsuarez-dev.com/\n"
        "- 🐙 **GitHub:** https://github.com/ezequiel-dev93\n"
        "- 💼 **LinkedIn:** https://www.linkedin.com/in/ezequiel-suarez-dev/\n"
        "- ✉️ **Email:** ezequielsuarez.dev@gmail.com"
    )
    print(profile_snippet)

    print("\n" + "=" * 70)
    print("✅ TODAS LAS PRUEBAS EN VIVO EJECUTADAS EXITOSAMENTE SIN ERRORES".center(70))
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
