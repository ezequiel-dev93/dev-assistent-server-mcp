import json
import re
from typing import Any, Dict, List, Optional, Tuple

from ..errors import ConfigError
from ..models import DockerServiceStatus, TestRunReport
from .redaction import redact

_SAFE_KEYWORD_RE = re.compile(r"^[A-Za-z0-9_.\-\s]{1,80}$")
_SAFE_SUBPATH_RE = re.compile(r"^[A-Za-z0-9_./\\\-]{1,160}$")

_PYTEST_PASSED_RE = re.compile(r"\b(\d+)\s+passed\b")
_PYTEST_FAILED_RE = re.compile(r"\b(\d+)\s+failed\b")
_PYTEST_SKIPPED_RE = re.compile(r"\b(\d+)\s+skipped\b")
_PYTEST_ERROR_RE = re.compile(r"\b(\d+)\s+errors?\b")

_UNITTEST_RAN_RE = re.compile(r"Ran\s+(\d+)\s+tests?\s+in\s+[\d.]+s")
_UNITTEST_FAIL_DETAIL_RE = re.compile(r"failures=(\d+)")
_UNITTEST_ERR_DETAIL_RE = re.compile(r"errors=(\d+)")
_UNITTEST_SKIP_DETAIL_RE = re.compile(r"skipped=(\d+)")


def validate_test_filter_args(
    target_subpath: Optional[str], keyword: Optional[str]
) -> Tuple[Optional[str], Optional[str]]:
    """Validates optional subpath and `-k` keyword to prevent CLI flag injection."""
    clean_sub: Optional[str] = None
    if target_subpath and target_subpath.strip():
        s = target_subpath.strip()
        if s.startswith("-"):
            raise ConfigError(
                f"Invalid target_subpath '{s}': cannot start with '-' (flag injection blocked)."
            )
        if ".." in s.replace("\\", "/").split("/"):
            raise ConfigError(
                f"Invalid target_subpath '{s}': parent directory traversal ('..') is forbidden."
            )
        if not _SAFE_SUBPATH_RE.match(s):
            raise ConfigError(f"Invalid characters in target_subpath '{s}'.")
        clean_sub = s

    clean_kw: Optional[str] = None
    if keyword and keyword.strip():
        k = keyword.strip()
        if k.startswith("-"):
            raise ConfigError(
                f"Invalid keyword '{k}': cannot start with '-' (flag injection blocked)."
            )
        if not _SAFE_KEYWORD_RE.match(k):
            raise ConfigError(
                f"Invalid keyword '{k}'. Only alphanumeric characters, underscores, dots, and spaces are allowed."
            )
        clean_kw = k

    return clean_sub, clean_kw


def _extract_ports_from_compose_item(item: Dict[str, Any]) -> List[str]:
    ports: List[str] = []
    publishers = item.get("Publishers")
    if isinstance(publishers, list):
        for p in publishers:
            if not isinstance(p, dict):
                continue
            pub_port = p.get("PublishedPort")
            target_port = p.get("TargetPort")
            proto = p.get("Protocol", "tcp")
            url_host = p.get("URL") or "0.0.0.0"
            if pub_port and target_port:
                ports.append(f"{url_host}:{pub_port}->{target_port}/{proto}")
            elif target_port:
                ports.append(f"{target_port}/{proto}")
    if not ports and item.get("Ports"):
        raw_ports = str(item.get("Ports", "")).strip()
        if raw_ports:
            ports = [p.strip() for p in raw_ports.split(",") if p.strip()]
    return ports


def parse_docker_compose_ps_json(raw_stdout: str) -> List[DockerServiceStatus]:
    """
    Parses `docker compose ps --format json` output (supports both NDJSON and JSON arrays).
    """
    text = (raw_stdout or "").strip()
    if not text:
        return []

    items: List[Dict[str, Any]] = []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                items = [x for x in parsed if isinstance(x, dict)]
        except json.JSONDecodeError:
            pass
    else:
        for line in text.splitlines():
            ln = line.strip()
            if not ln or not ln.startswith("{"):
                continue
            try:
                obj = json.loads(ln)
                if isinstance(obj, dict):
                    items.append(obj)
            except json.JSONDecodeError:
                continue

    services: List[DockerServiceStatus] = []
    for item in items:
        name = str(item.get("Name") or item.get("ID") or "unknown")
        service = str(item.get("Service") or name)
        state = str(item.get("State") or "unknown").lower()
        health = str(item.get("Health") or "").lower()
        status_detail = str(item.get("Status") or "")
        ports = _extract_ports_from_compose_item(item)

        is_healthy = (
            state == "running"
            and health != "unhealthy"
            and "unhealthy" not in status_detail.lower()
            and "restarting" not in status_detail.lower()
        )

        services.append(
            DockerServiceStatus(
                name=name,
                service=service,
                state=state,
                health=health,
                status_detail=status_detail,
                ports=ports,
                is_healthy=is_healthy,
            )
        )
    return services


def attach_sanitized_logs(
    service: DockerServiceStatus, raw_logs: str, max_chars: int = 2000
) -> DockerServiceStatus:
    """Redacts secrets and attaches bounded log tail to a DockerServiceStatus."""
    cleaned = (raw_logs or "").strip()
    if not cleaned:
        return service
    if len(cleaned) > max_chars:
        cleaned = "... [logs anteriores truncados]\n" + cleaned[-max_chars:]
    safe_logs, labels = redact(cleaned)
    service.recent_logs = safe_logs
    service.redacted_labels = labels
    return service


def parse_test_runner_output(
    project_name: str,
    project_path: str,
    runner_used: str,
    command_summary: str,
    exit_code: int,
    raw_output: str,
    duration_ms: float,
    max_chars: int = 3000,
) -> TestRunReport:
    """Parses pytest or unittest output into a structured TestRunReport with redacted logs."""
    text = (raw_output or "").strip()
    passed_count = 0
    failed_count = 0
    skipped_count = 0
    error_count = 0

    if runner_used == "pytest":
        m_pass = _PYTEST_PASSED_RE.search(text)
        m_fail = _PYTEST_FAILED_RE.search(text)
        m_skip = _PYTEST_SKIPPED_RE.search(text)
        m_err = _PYTEST_ERROR_RE.search(text)
        if m_pass:
            passed_count = int(m_pass.group(1))
        if m_fail:
            failed_count = int(m_fail.group(1))
        if m_skip:
            skipped_count = int(m_skip.group(1))
        if m_err:
            error_count = int(m_err.group(1))
    else:
        m_ran = _UNITTEST_RAN_RE.search(text)
        total_ran = int(m_ran.group(1)) if m_ran else 0
        m_fail = _UNITTEST_FAIL_DETAIL_RE.search(text)
        m_err = _UNITTEST_ERR_DETAIL_RE.search(text)
        m_skip = _UNITTEST_SKIP_DETAIL_RE.search(text)
        if m_fail:
            failed_count = int(m_fail.group(1))
        if m_err:
            error_count = int(m_err.group(1))
        if m_skip:
            skipped_count = int(m_skip.group(1))
        passed_count = max(0, total_ran - failed_count - error_count - skipped_count)

    excerpt = text
    if len(excerpt) > max_chars:
        excerpt = "... [salida inicial truncada]\n" + excerpt[-max_chars:]
    safe_excerpt, labels = redact(excerpt)

    passed = exit_code == 0 and failed_count == 0 and error_count == 0
    return TestRunReport(
        project_name=project_name,
        project_path=project_path,
        runner_used=runner_used,
        command_summary=command_summary,
        passed=passed,
        exit_code=exit_code,
        duration_ms=round(duration_ms, 2),
        passed_count=passed_count,
        failed_count=failed_count,
        skipped_count=skipped_count,
        error_count=error_count,
        output_excerpt=safe_excerpt,
        redacted_labels=labels,
    )
