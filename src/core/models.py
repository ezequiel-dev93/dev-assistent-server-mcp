from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class ArchitecturePattern(str, Enum):
    HEXAGONAL = "hexagonal"  # Ports & Adapters (core, domain, infrastructure)
    SCREAMING = "screaming"  # Feature-driven (modules/, features/)
    CLEAN_LAYERED = "clean_layered"  # application, domain, infrastructure
    STANDARD_MVC = "mvc"
    FLAT = "flat"


class ProjectStack(str, Enum):
    FASTAPI = "fastapi"
    ASTRO = "astro"
    NEXTJS = "nextjs"
    REACT = "react"
    STREAMLIT = "streamlit"
    PYTHON_GENERIC = "python_generic"
    NODE_GENERIC = "node_generic"
    UNKNOWN = "unknown"


class ProjectSummary(BaseModel):
    name: str = Field(description="Nombre de la carpeta o del paquete")
    path: str = Field(description="Ruta absoluta o relativa del proyecto")
    stack: ProjectStack = Field(description="Stack principal detectado")
    detected_architectures: List[ArchitecturePattern] = Field(
        default_factory=list, description="Patrones arquitectónicos detectados"
    )
    technologies: List[str] = Field(
        default_factory=list, description="Librerías y tecnologías identificadas"
    )
    has_tests: bool = Field(default=False, description="Si tiene suite de tests")
    has_docker: bool = Field(default=False, description="Si cuenta con Dockerfile o Compose")


class ProjectDetail(ProjectSummary):
    key_directories: List[str] = Field(
        default_factory=list, description="Carpetas estructurales clave"
    )
    architecture_guidelines: List[str] = Field(
        default_factory=list,
        description="Reglas y convenciones detectadas para que el LLM las respete",
    )
    summary_description: Optional[str] = Field(
        default=None, description="Resumen extraído de su README si existe"
    )


class MemoryCategory(str, Enum):
    PREFERENCE = "preference"  # Preferencias de código, librerías, tipado
    DECISION = "decision"  # Decisiones de negocio o arquitectura tomadas
    ARCHITECTURE = "architecture"  # Reglas de arquitectura de un proyecto
    CLIENT_CONTEXT = "client_context"  # Información de un cliente específico
    GENERAL = "general"


class MemoryEntry(BaseModel):
    id: Optional[int] = Field(default=None, description="ID autoincremental de la memoria")
    category: MemoryCategory = Field(description="Categoría de la memoria")
    content: str = Field(description="Hecho, preferencia o regla guardada")
    project_name: Optional[str] = Field(
        default=None, description="Proyecto al que aplica (opcional)"
    )
    tags: List[str] = Field(
        default_factory=list, description="Etiquetas de búsqueda (ej. ['fastapi', 'auth'])"
    )
    created_at: Optional[datetime] = Field(
        default=None, description="Fecha de creación ISO"
    )
