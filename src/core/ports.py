from abc import ABC, abstractmethod
from typing import List, Optional
from src.core.models import (
    ArchitectureAuditReport,
    MemoryCategory,
    MemoryEntry,
    ProjectDetail,
    ProjectSummary,
)


class IProjectScanner(ABC):
    """Puerto para escanear y analizar proyectos en el sistema de archivos."""

    @abstractmethod
    def scan_workspace(self, root_dir: str) -> List[ProjectSummary]:
        """Escanea un directorio raíz en busca de proyectos y retorna sus resúmenes."""
        pass

    @abstractmethod
    def inspect_project(self, project_path: str) -> ProjectDetail:
        """Analiza en profundidad un proyecto específico y extrae sus patrones."""
        pass

    @abstractmethod
    def audit_architecture(self, project_path: str) -> ArchitectureAuditReport:
        """Audita los archivos de código de un proyecto para detectar violaciones de arquitectura."""
        pass


class IMemoryRepository(ABC):
    """Puerto para persistencia de memoria episódica y semántica del agente."""

    @abstractmethod
    def save_memory(self, memory: MemoryEntry) -> MemoryEntry:
        """Guarda o actualiza un hecho o preferencia en la memoria persistente."""
        pass

    @abstractmethod
    def search_memories(
        self,
        query: str,
        category: Optional[MemoryCategory] = None,
        project_name: Optional[str] = None,
    ) -> List[MemoryEntry]:
        """Busca recuerdos semánticamente o por coincidencia de texto y tags."""
        pass

    @abstractmethod
    def list_memories(
        self, project_name: Optional[str] = None, limit: int = 50
    ) -> List[MemoryEntry]:
        """Lista los recuerdos más recientes filtrando opcionalmente por proyecto."""
        pass

    @abstractmethod
    def delete_memory(self, memory_id: int) -> bool:
        """Elimina un recuerdo por su identificador."""
        pass
