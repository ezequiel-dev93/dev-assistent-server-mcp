import os
import sys

# Asegurar que el directorio raíz del servidor esté en sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.infrastructure.scanner.filesystem_scanner import FileSystemProjectScanner
from src.infrastructure.storage.sqlite_memory import SqliteMemoryRepository
from src.tools.project_tools import ProjectTools
from src.tools.memory_tools import MemoryTools

# Rutas configurables
DEFAULT_WORKSPACE = os.getenv(
    "WORKSPACE_ROOT",
    os.path.abspath(os.path.join(BASE_DIR, "..")),
)
DEFAULT_DB_PATH = os.getenv(
    "MEMORY_DB_PATH",
    os.path.join(BASE_DIR, "data", "agent_memory.db"),
)

# Inicialización de adaptadores de infraestructura
scanner = FileSystemProjectScanner()
memory_repo = SqliteMemoryRepository(db_path=DEFAULT_DB_PATH)

# Servicios de herramientas
project_tools = ProjectTools(scanner=scanner, default_workspace=DEFAULT_WORKSPACE)
memory_tools = MemoryTools(repository=memory_repo)

mcp = None

# Soporte dual: MCP 2.x (MCPServer) y MCP 1.x (FastMCP)
try:
    from mcp.server import MCPServer

    mcp = MCPServer(
        name="DevAssistant-MCP",
        description="Servidor MCP para inspección de arquitecturas y memoria persistente para el agente.",
    )
except (ImportError, ModuleNotFoundError):
    try:
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP(
            name="DevAssistant-MCP",
            description="Servidor MCP para inspección de arquitecturas y memoria persistente para el agente.",
        )
    except (ImportError, ModuleNotFoundError):
        pass

if mcp is not None:

    @mcp.tool()
    def list_workspace_projects(workspace_path: str = "") -> str:
        """Escanea y lista todos los proyectos detectados en el espacio de trabajo con sus stacks y arquitecturas."""
        return project_tools.list_projects(workspace_path or None)

    @mcp.tool()
    def inspect_project(project_name_or_path: str) -> str:
        """Inspecciona en profundidad un proyecto (FastAPI, Astro, Next.js), identificando patrones (Hexagonal, Screaming) y reglas de código."""
        return project_tools.inspect_project(project_name_or_path)

    @mcp.tool()
    def get_feature_blueprint(project_name: str, feature_name: str) -> str:
        """Genera el plano (blueprint) exacto de archivos y carpetas para crear una nueva feature siguiendo la arquitectura del proyecto."""
        return project_tools.scaffold_feature_blueprint(project_name, feature_name)

    @mcp.tool()
    def get_developer_profile() -> str:
        """Retorna el perfil oficial de Ezequiel (Portfolio, GitHub, LinkedIn, Email) formateado para READMEs o redacciones."""
        return (
            "## 👨‍💻 Autor y Contacto\n"
            "- 🌐 **Portfolio:** https://www.ezequielsuarez-dev.com/\n"
            "- 🐙 **GitHub:** https://github.com/ezequiel-dev93\n"
            "- 💼 **LinkedIn:** https://www.linkedin.com/in/ezequiel-suarez-dev/\n"
            "- ✉️ **Email:** ezequielsuarez.dev@gmail.com\n"
        )

    @mcp.tool()
    def remember_fact(
        content: str, category: str = "general", project_name: str = "", tags: str = ""
    ) -> str:
        """Guarda un hecho, preferencia, regla de arquitectura o contexto de cliente en la memoria persistente del agente."""
        return memory_tools.remember(
            content=content,
            category=category,
            project_name=project_name or None,
            tags=tags or None,
        )

    @mcp.tool()
    def recall_memory(
        query: str = "", category: str = "", project_name: str = ""
    ) -> str:
        """Recupera recuerdos de la memoria permanente por búsqueda de texto, categoría (preference, decision, architecture, client_context) o proyecto."""
        return memory_tools.recall(
            query=query, category=category or None, project_name=project_name or None
        )

    @mcp.tool()
    def list_all_memories(project_name: str = "", limit: int = 25) -> str:
        """Lista los recuerdos más recientes registrados en la base de datos de memoria persistente."""
        return memory_tools.list_all(project_name=project_name or None, limit=limit)

    @mcp.tool()
    def forget_memory(memory_id: int) -> str:
        """Elimina permanentemente un recuerdo usando su ID numérico."""
        return memory_tools.forget(memory_id=memory_id)

    def run_server():
        mcp.run(transport="stdio")

else:

    def run_server():
        print(
            "⚠️ Error: El paquete oficial 'mcp' no está instalado en el entorno Python activo.\n"
            "Por favor ejecuta:\n"
            "  pip install -r requirements.txt\n",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    run_server()
