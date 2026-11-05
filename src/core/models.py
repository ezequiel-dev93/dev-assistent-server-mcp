from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class ArchitecturePattern(str, Enum):
    HEXAGONAL = "hexagonal"
    SCREAMING = "screaming"
    CLEAN_LAYERED = "clean_layered"
    STANDARD_MVC = "mvc"
    FLAT = "flat"


class ProjectStack(str, Enum):
    FASTAPI = "fastapi"
    ASTRO = "astro"
    NEXTJS = "nextjs"
    REACT = "react"
    STREAMLIT = "streamlit"
    DJANGO = "django"
    NESTJS = "nestjs"
    PYTHON_GENERIC = "python_generic"
    NODE_GENERIC = "node_generic"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class ProjectSummary(BaseModel):
    name: str = Field(description="Nombre de la carpeta o del paquete")
    path: str = Field(description="Ruta del proyecto")
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
        default=None, description="Resumen sanitizado extraído de su README si existe"
    )


class ImportRef(BaseModel):
    module: str = Field(description="Módulo o ruta importada")
    line: int = Field(description="Número de línea (1-based)")
    statement: str = Field(description="Sentencia original de importación")
    is_dynamic: bool = Field(default=False, description="True si usa importlib/__import__/import()")
    type_only: bool = Field(default=False, description="True si está bajo TYPE_CHECKING o import type")


class ArchitectureViolation(BaseModel):
    rule_id: str = Field(default="layer-boundary", description="Identificador de la regla vulnerada")
    file_path: str = Field(description="Ruta relativa del archivo donde se detectó la violación")
    line_number: int = Field(description="Número de línea del import o dependencia prohibida")
    offending_statement: str = Field(description="Sentencia de importación que viola la regla")
    rule_broken: str = Field(description="Explicación de la regla arquitectónica vulnerada")
    severity: Severity = Field(default=Severity.ERROR, description="Nivel de severidad (ERROR, WARNING, INFO)")


class ArchitectureAuditReport(BaseModel):
    project_name: str = Field(description="Nombre del proyecto auditado")
    project_path: str = Field(description="Ruta del proyecto")
    preset_used: str = Field(default="auto", description="Preset o archivo de configuración aplicado")
    detected_architectures: List[ArchitecturePattern] = Field(default_factory=list)
    files_scanned: int = Field(default=0, description="Cantidad de archivos de código analizados")
    violations: List[ArchitectureViolation] = Field(
        default_factory=list, description="Lista de hallazgos detectados"
    )

    @property
    def is_compliant(self) -> bool:
        return not any(v.severity == Severity.ERROR for v in self.violations)

    def fails_on(self, threshold: Severity = Severity.ERROR) -> bool:
        if threshold == Severity.ERROR:
            return any(v.severity == Severity.ERROR for v in self.violations)
        if threshold == Severity.WARNING:
            return any(v.severity in (Severity.ERROR, Severity.WARNING) for v in self.violations)
        return len(self.violations) > 0


class LayerRule(BaseModel):
    id: str = Field(description="ID de la regla de capas")
    from_layer: str = Field(description="Capa origen")
    disallow_layers: List[str] = Field(default_factory=list, description="Capas destino prohibidas")
    severity: Severity = Field(default=Severity.ERROR)
    description: Optional[str] = None


class ExternalRule(BaseModel):
    id: str = Field(description="ID de la regla de paquetes externos")
    from_layer: str = Field(description="Capa origen")
    disallow_external: List[str] = Field(default_factory=list, description="Paquetes externos prohibidos")
    allow_external: List[str] = Field(default_factory=list, description="Lista blanca exclusiva (opcional)")
    severity: Severity = Field(default=Severity.ERROR)
    description: Optional[str] = None


class CycleRule(BaseModel):
    id: str = Field(default="no-cycles")
    enabled: bool = Field(default=True)
    severity: Severity = Field(default=Severity.WARNING)


class RuleException(BaseModel):
    rule: str = Field(description="ID de la regla exceptuada")
    files: List[str] = Field(default_factory=list, description="Patrones glob relativos de archivos")
    reason: str = Field(default="", description="Motivo o ADR de referencia")
    expires: Optional[str] = Field(default=None, description="Fecha ISO YYYY-MM-DD de expiración")


class ProjectRules(BaseModel):
    version: int = Field(default=1)
    preset: str = Field(default="auto")
    layers: Dict[str, List[str]] = Field(default_factory=dict)
    layer_rules: List[LayerRule] = Field(default_factory=list)
    external_rules: List[ExternalRule] = Field(default_factory=list)
    cycle_rule: Optional[CycleRule] = Field(default=None)
    exceptions: List[RuleException] = Field(default_factory=list)


class MemoryCategory(str, Enum):
    PREFERENCE = "preference"
    DECISION = "decision"
    ARCHITECTURE = "architecture"
    CLIENT_CONTEXT = "client_context"
    GENERAL = "general"


class MemoryScope(str, Enum):
    PROJECT = "project"
    GLOBAL = "global"
    ALL = "all"


class MemoryEntry(BaseModel):
    id: Optional[int] = Field(default=None, description="ID autoincremental de la memoria")
    category: MemoryCategory = Field(description="Categoría de la memoria")
    content: str = Field(description="Hecho, preferencia o regla guardada")
    project_name: Optional[str] = Field(default=None, description="Proyecto al que aplica (None = global)")
    tags: List[str] = Field(default_factory=list, description="Etiquetas de búsqueda")
    created_at: Optional[datetime] = Field(default=None, description="Fecha de creación ISO")
    updated_at: Optional[datetime] = Field(default=None, description="Fecha de última actualización ISO")
    last_used_at: Optional[datetime] = Field(default=None, description="Fecha de última consulta ISO")
    superseded_by: Optional[int] = Field(default=None, description="ID del recuerdo que reemplaza a este")
    content_hash: Optional[str] = Field(default=None, description="SHA-256 normalizado del contenido")
    redacted_labels: List[str] = Field(default_factory=list, description="Etiquetas de secretos redactados")


class AdrStatus(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEPRECATED = "deprecated"
    SUPERSEDED = "superseded"


class AdrEntry(BaseModel):
    number: int = Field(description="Número secuencial del ADR (ej. 1 -> 0001)")
    title: str = Field(description="Título corto de la decisión")
    status: AdrStatus = Field(default=AdrStatus.PROPOSED)
    date: str = Field(description="Fecha ISO YYYY-MM-DD")
    context: str = Field(description="Contexto y problema a resolver")
    decision: str = Field(description="Decisión tomada")
    consequences: str = Field(default="", description="Consecuencias positivas y trade-offs")
    supersedes: Optional[int] = Field(default=None, description="Número de ADR al que reemplaza")
    superseded_by: Optional[int] = Field(default=None, description="Número de ADR que reemplaza a este")
    enforced_by: List[str] = Field(default_factory=list, description="IDs de reglas en devassistant.toml")
    tags: List[str] = Field(default_factory=list)
    file_path: Optional[str] = Field(default=None, description="Ruta relativa del archivo MADR")


class AdrDriftItem(BaseModel):
    adr_number: int
    adr_title: str
    status: str
    issue_type: str = Field(description="violation | missing_rule | unbacked_adr")
    severity: Severity
    details: str
    violations: List[ArchitectureViolation] = Field(default_factory=list)


class AdrDriftReport(BaseModel):
    project_name: str
    adrs_checked: int = 0
    items: List[AdrDriftItem] = Field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return any(i.severity == Severity.ERROR for i in self.items)


class BlueprintFileItem(BaseModel):
    relative_path: str
    description: str
    layer: str
    action: str = Field(default="create", description="create | skip_existing")
    template_content: str = Field(default="")


class BlueprintPlan(BaseModel):
    project_name: str
    feature_name: str
    slug: str
    detected_architectures: List[ArchitecturePattern] = Field(default_factory=list)
    files: List[BlueprintFileItem] = Field(default_factory=list)
    dry_run: bool = Field(default=True)
    created_files: List[str] = Field(default_factory=list)
    skipped_files: List[str] = Field(default_factory=list)


class AuthorProfile(BaseModel):
    name: Optional[str] = None
    portfolio_url: Optional[str] = None
    github_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    email: Optional[str] = None

    @property
    def is_configured(self) -> bool:
        return any([self.name, self.portfolio_url, self.github_url, self.linkedin_url, self.email])
