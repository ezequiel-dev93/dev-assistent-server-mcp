import re
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Set, Tuple

from ..models import EnvDockerAuditReport, EnvDockerFinding, Severity
from .redaction import redact

_ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
_COMPOSE_INTERP_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:?[-?+])([^}]*))?\}")
_COMPOSE_SIMPLE_VAR_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)\b")
_SENSITIVE_KEY_NAME_RE = re.compile(
    r"(?i)(?:password|passwd|secret|api[_-]?key|private[_-]?key|access[_-]?token|auth[_-]?token|jwt[_-]?secret|client[_-]?secret)"
)
_PLACEHOLDER_PATTERNS = (
    "changeme",
    "change_me",
    "your_",
    "your-",
    "<your",
    "replace_me",
    "replaceme",
    "todo",
    "xxx",
    "secret_here",
    "key_here",
    "token_here",
    "/path/to/",
    "example.com",
)
_SAFE_PUBLIC_VALUES = frozenset(
    {"true", "false", "0", "1", "development", "production", "staging", "local", "test", "info", "debug"}
)


@dataclass(frozen=True)
class ParsedEnvVar:
    key: str
    is_empty: bool
    is_placeholder: bool
    has_leaked_secret_pattern: bool


def _strip_quotes_and_inline_comment(raw_val: str) -> str:
    val = raw_val.strip()
    if not val:
        return ""
    if (val.startswith('"') and val.endswith('"') and len(val) >= 2) or (
        val.startswith("'") and val.endswith("'") and len(val) >= 2
    ):
        return val[1:-1].strip()
    # Unquoted value: strip trailing inline comment ` # ...`
    if " #" in val:
        val = val.split(" #", 1)[0].strip()
    elif "\t#" in val:
        val = val.split("\t#", 1)[0].strip()
    return val


def _is_placeholder_value(val: str) -> bool:
    if not val:
        return False
    low = val.lower().strip()
    if low in _SAFE_PUBLIC_VALUES:
        return False
    if low.startswith("<") and low.endswith(">"):
        return True
    return any(pat in low for pat in _PLACEHOLDER_PATTERNS)


def parse_dotenv_metadata(content: str) -> Dict[str, ParsedEnvVar]:
    """
    Parses a `.env` or `.env.example` file into sanitized metadata ONLY.
    Never retains or returns raw secret values.
    """
    result: Dict[str, ParsedEnvVar] = {}
    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ENV_LINE_RE.match(stripped)
        if not match:
            continue
        key = match.group(1).strip()
        val = _strip_quotes_and_inline_comment(match.group(2))
        is_empty = val == ""
        is_placeholder = _is_placeholder_value(val)
        _, secret_labels = redact(f"{key}={val}")
        # Ignore GENERIC match on placeholder values in .env.example
        real_secret_labels = [lbl for lbl in secret_labels if lbl != "GENERIC"]
        has_leaked_secret = bool(real_secret_labels) or (
            "GENERIC" in secret_labels and not is_placeholder and len(val) >= 16
        )
        result[key] = ParsedEnvVar(
            key=key,
            is_empty=is_empty,
            is_placeholder=is_placeholder,
            has_leaked_secret_pattern=has_leaked_secret,
        )
    return result


def _extract_compose_interpolations(content: str) -> Tuple[Set[str], Set[str]]:
    """Returns `(all_referenced_vars, required_vars_without_default)` from a Compose YAML."""
    all_vars: Set[str] = set()
    required_vars: Set[str] = set()

    for line in content.splitlines():
        if line.strip().startswith("#"):
            continue
        for match in _COMPOSE_INTERP_RE.finditer(line):
            var_name = match.group(1)
            operator = match.group(2) or ""
            default_val = match.group(3) or ""
            all_vars.add(var_name)
            # `${VAR:-default}` or `${VAR-default}` with non-empty default is optional
            if operator in (":-", "-") and default_val.strip() != "":
                continue
            required_vars.add(var_name)

        # Also check simple $VAR outside ${...}
        cleaned_line = _COMPOSE_INTERP_RE.sub("", line)
        for sm in _COMPOSE_SIMPLE_VAR_RE.finditer(cleaned_line):
            var_name = sm.group(1)
            all_vars.add(var_name)
            required_vars.add(var_name)

    return all_vars, required_vars


def _detect_compose_hardcoded_secrets(file_name: str, content: str) -> List[EnvDockerFinding]:
    """Detects sensitive environment variables hardcoded in `docker-compose.yml` instead of using `${VAR}`."""
    findings: List[EnvDockerFinding] = []
    # Matches YAML key: value (`POSTGRES_PASSWORD: mypassword`) or list item (`- POSTGRES_PASSWORD=mypassword`)
    kv_re = re.compile(
        r"^\s*(?:-\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*(.+?)\s*$"
    )
    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = kv_re.match(raw_line)
        if not m:
            continue
        key = m.group(1)
        raw_val = _strip_quotes_and_inline_comment(m.group(2))
        if not _SENSITIVE_KEY_NAME_RE.search(key):
            continue
        if not raw_val or raw_val.startswith("$") or "${" in raw_val:
            continue
        if raw_val.lower() in ("null", "~", "''", '""'):
            continue

        findings.append(
            EnvDockerFinding(
                rule_id="compose-hardcoded-secret",
                severity=Severity.WARNING,
                file_path=file_name,
                key_or_target=key,
                message=(
                    f"La credencial `{key}` tiene un valor literal hardcodeado en `{file_name}` "
                    "(valor omitido por seguridad)."
                ),
                remediation=f"Reemplazar el valor literal por interpolación `${{{key}}}` y definirlo en `.env`.",
            )
        )
    return findings


def _audit_dockerfile(
    file_name: str,
    content: str,
    dockerignore_content: Optional[str],
) -> List[EnvDockerFinding]:
    findings: List[EnvDockerFinding] = []
    stage_aliases: Set[str] = set()
    has_user = False
    last_user = ""
    has_healthcheck = False
    copies_context = False

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        upper = line.upper()

        if upper.startswith("FROM "):
            parts = line.split()
            # Handle `FROM [--platform=...] image [AS alias]`
            img_idx = 1
            while img_idx < len(parts) and parts[img_idx].startswith("--"):
                img_idx += 1
            if img_idx < len(parts):
                image_ref = parts[img_idx]
                if " AS " in upper:
                    alias = parts[-1].lower()
                    stage_aliases.add(alias)

                img_low = image_ref.lower()
                if img_low not in stage_aliases and img_low != "scratch" and "$" not in image_ref:
                    if ":" not in image_ref and "@" not in image_ref:
                        findings.append(
                            EnvDockerFinding(
                                rule_id="dockerfile-unpinned-base-image",
                                severity=Severity.WARNING,
                                file_path=file_name,
                                key_or_target=image_ref,
                                message=f"Imagen base `{image_ref}` sin tag de versión explícito (equivale a `:latest`).",
                                remediation="Fijar una versión específica (ej. `python:3.11-slim`) para builds reproducibles.",
                            )
                        )
                    elif img_low.endswith(":latest"):
                        findings.append(
                            EnvDockerFinding(
                                rule_id="dockerfile-unpinned-base-image",
                                severity=Severity.WARNING,
                                file_path=file_name,
                                key_or_target=image_ref,
                                message=f"Imagen base `{image_ref}` utiliza el tag mutable `:latest`.",
                                remediation="Fijar una versión inmutable o digest para evitar roturas inesperadas en CI/CD.",
                            )
                        )

        elif upper.startswith("USER "):
            parts = line.split()
            if len(parts) >= 2:
                has_user = True
                last_user = parts[1].strip().lower()

        elif upper.startswith("HEALTHCHECK "):
            if "NONE" not in upper:
                has_healthcheck = True

        elif upper.startswith(("COPY ", "ADD ")):
            if re.search(r"(?i)\b(?:COPY|ADD)\s+(?:--\S+\s+)*\.env\b", line):
                findings.append(
                    EnvDockerFinding(
                        rule_id="dockerfile-copies-dotenv",
                        severity=Severity.ERROR,
                        file_path=file_name,
                        key_or_target="COPY .env",
                        message=f"`{file_name}` copia explícitamente el archivo `.env` dentro de la imagen.",
                        remediation="Eliminar `COPY .env` del Dockerfile e inyectar variables en runtime (`env_file` o variables del orquestador).",
                    )
                )
            if re.search(r"(?i)\b(?:COPY|ADD)\s+(?:--\S+\s+)*\.\s+", line):
                copies_context = True

    if not has_user or last_user in ("root", "0", "0:0"):
        findings.append(
            EnvDockerFinding(
                rule_id="dockerfile-missing-user",
                severity=Severity.WARNING,
                file_path=file_name,
                key_or_target="USER",
                message=f"`{file_name}` no define un usuario sin privilegios (`USER`); el contenedor correrá como `root`.",
                remediation="Crear un usuario de aplicación (ej. `RUN useradd -m appuser` y `USER appuser`).",
            )
        )

    if not has_healthcheck:
        findings.append(
            EnvDockerFinding(
                rule_id="dockerfile-missing-healthcheck",
                severity=Severity.INFO,
                file_path=file_name,
                key_or_target="HEALTHCHECK",
                message=f"`{file_name}` no declara directiva `HEALTHCHECK`.",
                remediation="Agregar `HEALTHCHECK` en el Dockerfile o verificar que esté definido en `docker-compose.yml`.",
            )
        )

    if copies_context:
        if dockerignore_content is None:
            findings.append(
                EnvDockerFinding(
                    rule_id="dockerignore-missing",
                    severity=Severity.WARNING,
                    file_path=".dockerignore",
                    key_or_target="COPY . .",
                    message=(
                        f"`{file_name}` ejecuta `COPY . .` pero el proyecto no tiene `.dockerignore` "
                        "(riesgo de empaquetar `.env`, `.git`, `venv` o `node_modules` en la imagen)."
                    ),
                    remediation="Crear un archivo `.dockerignore` que excluya `.env*`, `.git`, `.venv`, `node_modules` y `__pycache__`.",
                )
            )
        else:
            ignore_lines = [
                ln.strip()
                for ln in dockerignore_content.splitlines()
                if ln.strip() and not ln.strip().startswith("#")
            ]
            ignores_env = any(
                pat in (".env", ".env*", "*.env", "**/.env", "**/.env*") for pat in ignore_lines
            )
            if not ignores_env:
                findings.append(
                    EnvDockerFinding(
                        rule_id="dockerignore-exposes-env",
                        severity=Severity.ERROR,
                        file_path=".dockerignore",
                        key_or_target=".env",
                        message=(
                            f"`{file_name}` usa `COPY . .` y `.dockerignore` NO excluye `.env`, "
                            "exponiendo secretos locales dentro de las capas de la imagen Docker."
                        ),
                        remediation="Agregar `.env` y `.env.*` (con excepción `!.env.example` si fuera necesario) en `.dockerignore`.",
                    )
                )

    return findings


def audit_project_env_and_docker(
    project_name: str,
    project_path: str,
    env_content: Optional[str] = None,
    env_example_content: Optional[str] = None,
    env_example_name: str = ".env.example",
    compose_files: Optional[Mapping[str, str]] = None,
    dockerfiles: Optional[Mapping[str, str]] = None,
    dockerignore_content: Optional[str] = None,
) -> EnvDockerAuditReport:
    """
    Pure domain auditor for `.env`, `.env.example`, `docker-compose.yml`, `Dockerfile`, and `.dockerignore`.
    Zero filesystem I/O and zero exposure of secret values.
    """
    compose_map = dict(compose_files or {})
    dockerfile_map = dict(dockerfiles or {})

    env_files_found: List[str] = []
    if env_content is not None:
        env_files_found.append(".env")
    if env_example_content is not None:
        env_files_found.append(env_example_name)

    docker_files_found: List[str] = [
        *sorted(dockerfile_map.keys()),
        *sorted(compose_map.keys()),
    ]
    if dockerignore_content is not None:
        docker_files_found.append(".dockerignore")

    env_vars = parse_dotenv_metadata(env_content) if env_content is not None else {}
    example_vars = (
        parse_dotenv_metadata(env_example_content) if env_example_content is not None else {}
    )

    documented_keys = sorted(example_vars.keys())
    configured_keys = sorted(env_vars.keys())

    findings: List[EnvDockerFinding] = []
    missing_in_env: List[str] = []
    empty_in_env: List[str] = []
    placeholder_in_env: List[str] = []
    undocumented_in_example: List[str] = []

    # 1. Check if .env.example leaked a real secret
    for k, meta in example_vars.items():
        if meta.has_leaked_secret_pattern:
            findings.append(
                EnvDockerFinding(
                    rule_id="env-example-leaked-secret",
                    severity=Severity.ERROR,
                    file_path=env_example_name,
                    key_or_target=k,
                    message=(
                        f"Posible credencial real detectada en `{env_example_name}` para la clave `{k}` "
                        "(valor redactado por seguridad)."
                    ),
                    remediation=f"Reemplazar el valor de `{k}` en `{env_example_name}` por un placeholder seguro y rotar la clave si fue versionada en Git.",
                )
            )

    # 2. Cross-check .env vs .env.example
    if env_example_content is not None and env_content is None:
        findings.append(
            EnvDockerFinding(
                rule_id="env-file-missing",
                severity=Severity.WARNING,
                file_path=".env",
                key_or_target=".env",
                message=f"Existe `{env_example_name}` ({len(documented_keys)} variables), pero no existe archivo `.env` local.",
                remediation=f"Copiar `{env_example_name}` a `.env` y completar los valores del entorno local.",
            )
        )
    elif env_content is not None:
        for k in documented_keys:
            if k not in env_vars:
                missing_in_env.append(k)
                findings.append(
                    EnvDockerFinding(
                        rule_id="env-missing-key",
                        severity=Severity.ERROR,
                        file_path=".env",
                        key_or_target=k,
                        message=f"La variable `{k}` está declarada en `{env_example_name}` pero falta en `.env`.",
                        remediation=f"Definir `{k}=...` en el archivo `.env` local.",
                    )
                )

        for k, meta in env_vars.items():
            if meta.is_empty:
                empty_in_env.append(k)
                findings.append(
                    EnvDockerFinding(
                        rule_id="env-empty-value",
                        severity=Severity.WARNING,
                        file_path=".env",
                        key_or_target=k,
                        message=f"La variable `{k}` está declarada en `.env` pero su valor está vacío.",
                        remediation=f"Asignar un valor válido a `{k}` en `.env` o confirmar si es opcional.",
                    )
                )
            elif meta.is_placeholder:
                placeholder_in_env.append(k)
                findings.append(
                    EnvDockerFinding(
                        rule_id="env-placeholder-value",
                        severity=Severity.WARNING,
                        file_path=".env",
                        key_or_target=k,
                        message=f"La variable `{k}` en `.env` conserva un valor de plantilla/placeholder sin configurar.",
                        remediation=f"Reemplazar el placeholder de `{k}` en `.env` por el valor real del entorno.",
                    )
                )

            if env_example_content is not None and k not in example_vars:
                undocumented_in_example.append(k)
                findings.append(
                    EnvDockerFinding(
                        rule_id="env-undocumented-key",
                        severity=Severity.INFO,
                        file_path=env_example_name,
                        key_or_target=k,
                        message=f"La variable `{k}` existe en `.env` pero no está documentada en `{env_example_name}`.",
                        remediation=f"Agregar `{k}=<placeholder>` en `{env_example_name}` para mantener sincronizado al equipo.",
                    )
                )

    # 3. Audit docker-compose files
    all_compose_vars: Set[str] = set()
    known_keys = set(env_vars.keys()) if env_content is not None else set(example_vars.keys())

    for compose_name, compose_text in sorted(compose_map.items()):
        ref_vars, req_vars = _extract_compose_interpolations(compose_text)
        all_compose_vars.update(ref_vars)
        for req_key in sorted(req_vars):
            if req_key not in known_keys or (
                req_key in env_vars and env_vars[req_key].is_empty
            ):
                findings.append(
                    EnvDockerFinding(
                        rule_id="compose-missing-env",
                        severity=Severity.ERROR,
                        file_path=compose_name,
                        key_or_target=req_key,
                        message=(
                            f"`{compose_name}` interpola `${{{req_key}}}` sin valor por defecto y la variable "
                            "no está definida (o está vacía) en `.env`."
                        ),
                        remediation=f"Definir `{req_key}` en `.env` o agregar un fallback `${{{req_key}:-default}}` en `{compose_name}`.",
                    )
                )
        findings.extend(_detect_compose_hardcoded_secrets(compose_name, compose_text))

    # 4. Audit Dockerfiles & .dockerignore
    for df_name, df_text in sorted(dockerfile_map.items()):
        findings.extend(_audit_dockerfile(df_name, df_text, dockerignore_content))

    return EnvDockerAuditReport(
        project_name=project_name,
        project_path=project_path,
        env_files_found=env_files_found,
        docker_files_found=docker_files_found,
        documented_env_keys=documented_keys,
        configured_env_keys=configured_keys,
        compose_referenced_keys=sorted(all_compose_vars),
        missing_in_env=sorted(missing_in_env),
        empty_in_env=sorted(empty_in_env),
        placeholder_in_env=sorted(placeholder_in_env),
        undocumented_in_example=sorted(undocumented_in_example),
        findings=findings,
    )
