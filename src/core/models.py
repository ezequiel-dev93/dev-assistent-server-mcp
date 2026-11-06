from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
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


class HttpMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class EndpointRequestSpec(BaseModel):
    name: str = Field(default="", description="Nombre opcional del caso de prueba")
    url: str = Field(description="URL HTTP/HTTPS completa del endpoint")
    method: HttpMethod = Field(default=HttpMethod.GET, description="Método HTTP")
    headers: Dict[str, str] = Field(default_factory=dict, description="Headers HTTP adicionales")
    query_params: Dict[str, str] = Field(
        default_factory=dict, description="Parámetros de query string"
    )
    json_payload: Optional[Any] = Field(
        default=None, description="Cuerpo JSON opcional para POST/PUT/PATCH/DELETE"
    )
    auth_env_var: Optional[str] = Field(
        default=None,
        description="Nombre de variable de entorno local cuyo token se inyecta sin exponerlo al LLM",
    )
    auth_scheme: str = Field(
        default="Bearer",
        description="Prefijo de autorización (ej. Bearer, Basic, Token, o vacío para enviar valor crudo)",
    )
    auth_header: str = Field(
        default="Authorization",
        description="Nombre del header donde inyectar la credencial (ej. Authorization o X-API-Key)",
    )
    expected_status: int = Field(default=200, description="Código HTTP esperado")
    max_response_time_ms: Optional[float] = Field(
        default=None, description="Tiempo máximo de respuesta aceptable en ms"
    )
    expected_json_keys: List[str] = Field(
        default_factory=list,
        description="Claves o rutas dot-notation esperadas en el cuerpo JSON (ej. data.id)",
    )
    expected_body_contains: Optional[str] = Field(
        default=None, description="Texto que debe estar contenido en el cuerpo de respuesta"
    )
    timeout_seconds: float = Field(
        default=10.0, ge=0.5, le=60.0, description="Timeout máximo en segundos"
    )
    allow_private_network: bool = Field(
        default=True,
        description="Permite localhost/LAN para desarrollo local, bloqueando siempre cloud metadata SSRF",
    )


class HttpProbeRawResponse(BaseModel):
    status_code: Optional[int] = None
    response_time_ms: float = 0.0
    headers: Dict[str, str] = Field(default_factory=dict)
    content_type: str = ""
    body_text: str = ""
    size_bytes: int = 0
    transport_used: str = "httpx"
    error: Optional[str] = None


class AssertionCheckResult(BaseModel):
    check: str = Field(description="Tipo de validación ejecutada")
    passed: bool
    expected: str
    actual: str
    message: str


class EndpointTestResult(BaseModel):
    name: str = ""
    url: str
    method: HttpMethod
    passed: bool
    status_code: Optional[int] = None
    expected_status: int = 200
    response_time_ms: float = 0.0
    content_type: str = ""
    size_bytes: int = 0
    json_top_keys: List[str] = Field(default_factory=list)
    checks: List[AssertionCheckResult] = Field(default_factory=list)
    data_preview: str = ""
    redacted_labels: List[str] = Field(default_factory=list)
    auth_injected_from_env: Optional[str] = None
    error: Optional[str] = None


class ApiSuiteReport(BaseModel):
    suite_name: str = Field(default="API QA Suite")
    base_url: Optional[str] = None
    results: List[EndpointTestResult] = Field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def all_passed(self) -> bool:
        return len(self.results) > 0 and all(r.passed for r in self.results)

    @property
    def total_time_ms(self) -> float:
        return round(sum(r.response_time_ms for r in self.results), 2)


class EnvDockerFinding(BaseModel):
    rule_id: str = Field(description="Identificador de la regla de entorno o Docker")
    severity: Severity = Field(default=Severity.WARNING)
    file_path: str = Field(description="Archivo relativo donde se detectó el hallazgo")
    key_or_target: str = Field(description="Variable de entorno, servicio o instrucción afectada")
    message: str = Field(description="Descripción del problema (sin exponer valores secretos)")
    remediation: str = Field(default="", description="Acción recomendada para corregirlo")


class EnvDockerAuditReport(BaseModel):
    project_name: str
    project_path: str
    env_files_found: List[str] = Field(default_factory=list)
    docker_files_found: List[str] = Field(default_factory=list)
    documented_env_keys: List[str] = Field(default_factory=list)
    configured_env_keys: List[str] = Field(default_factory=list)
    compose_referenced_keys: List[str] = Field(default_factory=list)
    missing_in_env: List[str] = Field(default_factory=list)
    empty_in_env: List[str] = Field(default_factory=list)
    placeholder_in_env: List[str] = Field(default_factory=list)
    undocumented_in_example: List[str] = Field(default_factory=list)
    findings: List[EnvDockerFinding] = Field(default_factory=list)

    @property
    def is_compliant(self) -> bool:
        return not any(f.severity == Severity.ERROR for f in self.findings)

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.WARNING)


class DockerServiceStatus(BaseModel):
    name: str = Field(description="Nombre del contenedor")
    service: str = Field(description="Nombre del servicio en docker-compose")
    state: str = Field(description="Estado del contenedor (running, exited, restarting, etc.)")
    health: str = Field(default="", description="Estado de healthcheck (healthy, unhealthy, starting)")
    status_detail: str = Field(default="", description="Detalle de uptime o código de salida")
    ports: List[str] = Field(default_factory=list, description="Mapeos de puertos publicados")
    is_healthy: bool = Field(default=True, description="True si está running y sin fallo de healthcheck")
    recent_logs: str = Field(default="", description="Últimas líneas de logs sanitizadas si falló")
    redacted_labels: List[str] = Field(default_factory=list)


class DockerStackReport(BaseModel):
    project_name: str
    project_path: str
    compose_file: Optional[str] = None
    daemon_available: bool = True
    services: List[DockerServiceStatus] = Field(default_factory=list)
    error: Optional[str] = None

    @property
    def all_healthy(self) -> bool:
        return (
            self.daemon_available
            and self.error is None
            and len(self.services) > 0
            and all(s.is_healthy for s in self.services)
        )

    @property
    def running_count(self) -> int:
        return sum(1 for s in self.services if s.state.lower() == "running")

    @property
    def unhealthy_services(self) -> List[str]:
        return [s.service for s in self.services if not s.is_healthy]


class TestRunReport(BaseModel):
    project_name: str
    project_path: str
    runner_used: str = Field(description="pytest o unittest")
    command_summary: str = Field(description="Comando ejecutado (sin rutas sensibles)")
    passed: bool
    exit_code: int
    duration_ms: float = 0.0
    passed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    output_excerpt: str = ""
    redacted_labels: List[str] = Field(default_factory=list)



