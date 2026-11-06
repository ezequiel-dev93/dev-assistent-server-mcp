from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional
from .models import (
    AdrEntry,
    ArchitectureAuditReport,
    DockerStackReport,
    EndpointRequestSpec,
    HttpProbeRawResponse,
    ImportRef,
    MemoryCategory,
    MemoryEntry,
    MemoryScope,
    ProjectDetail,
    ProjectRules,
    ProjectSummary,
    TestRunReport,
)


class IProjectScanner(ABC):
    """Puerto para escanear y analizar proyectos en el sistema de archivos."""

    @abstractmethod
    def scan_workspace(self, root_dir: str) -> List[ProjectSummary]:
        pass

    @abstractmethod
    def inspect_project(self, project_path: str) -> ProjectDetail:
        pass

    @abstractmethod
    def audit_architecture(self, project_path: str) -> ArchitectureAuditReport:
        pass


class IImportExtractor(ABC):
    """Puerto para extraer importaciones desde archivos de código fuente."""

    @abstractmethod
    def supports(self, file_path: Path) -> bool:
        pass

    @abstractmethod
    def extract(self, file_path: Path, project_root: Path) -> List[ImportRef]:
        pass


class IModuleResolver(ABC):
    """Puerto para clasificar un módulo importado como archivo interno, stdlib o paquete externo."""

    @abstractmethod
    def resolve_internal(
        self,
        imported_module: str,
        source_file: Path,
        project_root: Path,
    ) -> Optional[Path]:
        pass

    @abstractmethod
    def is_stdlib(self, imported_module: str, source_file: Path) -> bool:
        pass


class IProjectConfigLoader(ABC):
    """Puerto para cargar la configuración arquitectónica (devassistant.toml / pyproject.toml / presets)."""

    @abstractmethod
    def load(self, project_root: Path, detected_patterns: List[str], stack: str) -> ProjectRules:
        pass


class IMemoryRepository(ABC):
    """Puerto para persistencia de memoria episódica y semántica del agente."""

    @abstractmethod
    def save_memory(
        self, memory: MemoryEntry, supersedes: Optional[int] = None
    ) -> MemoryEntry:
        pass

    @abstractmethod
    def search_memories(
        self,
        query: str,
        category: Optional[MemoryCategory] = None,
        project_name: Optional[str] = None,
        scope: MemoryScope = MemoryScope.ALL,
        include_history: bool = False,
        limit: int = 50,
    ) -> List[MemoryEntry]:
        pass

    @abstractmethod
    def list_memories(
        self,
        project_name: Optional[str] = None,
        scope: MemoryScope = MemoryScope.ALL,
        include_history: bool = False,
        limit: int = 50,
    ) -> List[MemoryEntry]:
        pass

    @abstractmethod
    def list_stale_memories(self, days: int = 180) -> List[MemoryEntry]:
        pass

    @abstractmethod
    def delete_memory(self, memory_id: int) -> bool:
        pass


class IAdrRepository(ABC):
    """Puerto para gestión de Architecture Decision Records (MADR) en el sistema de archivos."""

    @abstractmethod
    def list_adrs(self, project_root: Path) -> List[AdrEntry]:
        pass

    @abstractmethod
    def get_adr(self, project_root: Path, number: int) -> Optional[AdrEntry]:
        pass

    @abstractmethod
    def save_adr(self, project_root: Path, adr: AdrEntry) -> AdrEntry:
        pass


class IHttpProbe(ABC):
    """Puerto de salida para ejecutar peticiones HTTP de QA desacopladas del cliente de transporte."""

    @abstractmethod
    def send(
        self,
        spec: EndpointRequestSpec,
        resolved_headers: Dict[str, str],
    ) -> HttpProbeRawResponse:
        pass


class IRuntimeQaRunner(ABC):
    """Puerto de salida para diagnóstico dinámico de contenedores Docker y ejecución aislada de tests."""

    @abstractmethod
    def inspect_docker_compose(
        self, project_dir: Path, tail_logs: int = 30
    ) -> DockerStackReport:
        pass

    @abstractmethod
    def run_test_suite(
        self,
        project_dir: Path,
        target_subpath: Optional[str] = None,
        keyword: Optional[str] = None,
        timeout_seconds: float = 60.0,
    ) -> TestRunReport:
        pass


