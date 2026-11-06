import ipaddress
import json
import re
from typing import Any, List, Sequence, Tuple

from ..errors import UnsafeTargetUrlError
from ..models import (
    AssertionCheckResult,
    EndpointRequestSpec,
    EndpointTestResult,
    HttpProbeRawResponse,
)
from .redaction import redact

BLOCKED_METADATA_HOSTS = frozenset(
    {
        "metadata.google.internal",
        "metadata.azure.com",
        "metadata",
        "instance-data",
        "169.254.169.254",
        "100.100.100.200",
        "fd00:ec2::254",
    }
)


_AUTHORITY_SPLIT_RE = re.compile(r"[/?#]")


def _parse_url_scheme_and_host(cleaned: str) -> Tuple[str, str, bool]:
    """Pure string URL authority parser (avoids `urllib` imports in pure domain)."""
    if "://" not in cleaned:
        scheme_part = cleaned.split(":", 1)[0] if ":" in cleaned else ""
        return scheme_part, "", False

    scheme_raw, rest = cleaned.split("://", 1)
    authority = _AUTHORITY_SPLIT_RE.split(rest, maxsplit=1)[0]
    has_userinfo = "@" in authority
    host_port = authority.rsplit("@", 1)[-1]

    if host_port.startswith("["):
        end_bracket = host_port.find("]")
        if end_bracket == -1:
            return scheme_raw, "", has_userinfo
        hostname = host_port[1:end_bracket]
    else:
        hostname = host_port.split(":", 1)[0]

    return scheme_raw, hostname, has_userinfo


def validate_probe_url(url: str, allow_private_network: bool = True) -> str:
    """
    Validates target URL scheme and blocks SSRF cloud-metadata/link-local targets.
    Allows localhost/RFC1918 addresses when `allow_private_network=True` for local dev QA.
    """
    cleaned = (url or "").strip()
    if not cleaned:
        raise UnsafeTargetUrlError("Target URL cannot be empty.")

    raw_scheme, raw_hostname, has_userinfo = _parse_url_scheme_and_host(cleaned)
    scheme = raw_scheme.lower()
    if scheme not in ("http", "https"):
        raise UnsafeTargetUrlError(
            f"Unsupported URL scheme '{raw_scheme or '<empty>'}'. Only 'http' and 'https' are allowed."
        )

    if has_userinfo:
        raise UnsafeTargetUrlError(
            "Embedded credentials in URL (user:pass@host) are forbidden. Use `auth_env_var` instead."
        )

    if not raw_hostname:
        raise UnsafeTargetUrlError(f"Invalid URL '{cleaned}': missing hostname.")

    host_low = raw_hostname.lower().strip(".")
    if host_low in BLOCKED_METADATA_HOSTS:
        raise UnsafeTargetUrlError(
            f"Blocked SSRF target: cloud metadata host '{host_low}' is forbidden."
        )

    try:
        ip_obj = ipaddress.ip_address(host_low)
    except ValueError:
        ip_obj = None

    if ip_obj is not None:
        if ip_obj.is_unspecified:
            raise UnsafeTargetUrlError(
                f"Unspecified address '{host_low}' is disallowed. Use 'localhost' or '127.0.0.1' instead."
            )
        if ip_obj.is_link_local or ip_obj.is_multicast:
            raise UnsafeTargetUrlError(
                f"Blocked SSRF target: link-local or multicast IP '{host_low}' is forbidden."
            )
        if not allow_private_network and (
            ip_obj.is_loopback or ip_obj.is_private or ip_obj.is_reserved
        ):
            raise UnsafeTargetUrlError(
                f"Private or loopback IP '{host_low}' is blocked because `allow_private_network=False`."
            )
    elif not allow_private_network:
        if host_low in ("localhost", "localhost.localdomain") or host_low.endswith(".local"):
            raise UnsafeTargetUrlError(
                f"Local hostname '{host_low}' is blocked because `allow_private_network=False`."
            )

    return cleaned


def resolve_json_path(data: Any, path_expr: str) -> Tuple[bool, Any]:
    """Resolves a dot-separated key path (e.g. 'data.user.id' or 'items.0.name') inside parsed JSON."""
    parts = [p for p in path_expr.strip().split(".") if p != ""]
    if not parts:
        return False, None

    current: Any = data
    for segment in parts:
        if isinstance(current, dict):
            if segment not in current:
                return False, None
            current = current[segment]
        elif isinstance(current, list):
            if not segment.isdigit():
                return False, None
            idx = int(segment)
            if idx < 0 or idx >= len(current):
                return False, None
            current = current[idx]
        else:
            return False, None
    return True, current


def mask_sensitive_output(
    text: str, extra_secrets: Sequence[str] = ()
) -> Tuple[str, List[str]]:
    """Masks exact runtime env secrets (preventing echo-server leaks) and runs pattern redaction."""
    current = text
    labels: List[str] = []

    for secret in extra_secrets:
        if secret and len(secret) >= 4 and secret in current:
            current = current.replace(secret, "[REDACTED:ENV_AUTH]")
            if "ENV_AUTH" not in labels:
                labels.append("ENV_AUTH")

    redacted_text, pattern_labels = redact(current)
    for lbl in pattern_labels:
        if lbl not in labels:
            labels.append(lbl)

    return redacted_text, labels


def _extract_json_metadata(body_text: str) -> Tuple[bool, Any, List[str]]:
    stripped = body_text.strip()
    if not stripped:
        return False, None, []
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        return False, None, []

    if isinstance(parsed, dict):
        top_keys = [str(k) for k in list(parsed.keys())[:15]]
    elif isinstance(parsed, list):
        top_keys = [f"[array len={len(parsed)}]"]
    else:
        top_keys = [f"[{type(parsed).__name__}]"]
    return True, parsed, top_keys


def evaluate_endpoint_response(
    spec: EndpointRequestSpec,
    raw: HttpProbeRawResponse,
    extra_secrets: Sequence[str] = (),
    preview_limit: int = 500,
) -> EndpointTestResult:
    """Pure domain evaluator that checks status, latency, JSON keys, body substrings, and redacts secrets."""
    label_name = spec.name.strip() or f"{spec.method.value} {spec.url}"

    if raw.error:
        safe_err, err_labels = mask_sensitive_output(raw.error, extra_secrets=extra_secrets)
        return EndpointTestResult(
            name=label_name,
            url=spec.url,
            method=spec.method,
            passed=False,
            status_code=raw.status_code,
            expected_status=spec.expected_status,
            response_time_ms=round(raw.response_time_ms, 2),
            checks=[
                AssertionCheckResult(
                    check="transport",
                    passed=False,
                    expected="HTTP response",
                    actual="Connection/Request Error",
                    message=safe_err,
                )
            ],
            redacted_labels=err_labels,
            auth_injected_from_env=spec.auth_env_var,
            error=safe_err,
        )

    checks: List[AssertionCheckResult] = []

    # 1. Status code assertion
    status_ok = raw.status_code == spec.expected_status
    checks.append(
        AssertionCheckResult(
            check="status_code",
            passed=status_ok,
            expected=str(spec.expected_status),
            actual=str(raw.status_code),
            message=(
                f"HTTP {raw.status_code} coincide con lo esperado"
                if status_ok
                else f"Se esperaba HTTP {spec.expected_status}, pero respondió {raw.status_code}"
            ),
        )
    )

    # 2. Latency threshold assertion (optional)
    rounded_ms = round(raw.response_time_ms, 2)
    if spec.max_response_time_ms is not None:
        latency_ok = rounded_ms <= spec.max_response_time_ms
        checks.append(
            AssertionCheckResult(
                check="max_response_time_ms",
                passed=latency_ok,
                expected=f"<= {spec.max_response_time_ms} ms",
                actual=f"{rounded_ms} ms",
                message=(
                    f"Latencia dentro de umbral ({rounded_ms} ms <= {spec.max_response_time_ms} ms)"
                    if latency_ok
                    else f"Latencia excedida ({rounded_ms} ms > {spec.max_response_time_ms} ms)"
                ),
            )
        )

    # 3. JSON structure & expected keys assertions
    is_json, parsed_json, json_top_keys = _extract_json_metadata(raw.body_text)
    if spec.expected_json_keys:
        if not is_json:
            checks.append(
                AssertionCheckResult(
                    check="json_parse",
                    passed=False,
                    expected="Valid JSON body",
                    actual=raw.content_type or "non-JSON text",
                    message="El cuerpo de respuesta no es un JSON válido; no se pudieron verificar las claves.",
                )
            )
        else:
            for key_path in spec.expected_json_keys:
                found, _ = resolve_json_path(parsed_json, key_path)
                checks.append(
                    AssertionCheckResult(
                        check=f"json_key:{key_path}",
                        passed=found,
                        expected=f"key '{key_path}' present",
                        actual="present" if found else "missing",
                        message=(
                            f"Clave JSON `{key_path}` presente"
                            if found
                            else f"Falta la clave JSON esperada `{key_path}`"
                        ),
                    )
                )

    # 4. Expected substring in body (optional)
    if spec.expected_body_contains:
        contains_ok = spec.expected_body_contains in raw.body_text
        checks.append(
            AssertionCheckResult(
                check="body_contains",
                passed=contains_ok,
                expected=f"contains '{spec.expected_body_contains}'",
                actual="found" if contains_ok else "not found",
                message=(
                    f"Texto esperado `{spec.expected_body_contains}` encontrado en la respuesta"
                    if contains_ok
                    else f"No se encontró `{spec.expected_body_contains}` en el cuerpo de respuesta"
                ),
            )
        )

    # 5. Sanitized preview
    raw_preview = raw.body_text.strip()
    truncated = len(raw_preview) > preview_limit
    preview_slice = raw_preview[:preview_limit]
    safe_preview, red_labels = mask_sensitive_output(
        preview_slice, extra_secrets=extra_secrets
    )
    if truncated:
        safe_preview = f"{safe_preview}... [truncado, total {raw.size_bytes} bytes]"

    all_passed = all(c.passed for c in checks)
    return EndpointTestResult(
        name=label_name,
        url=spec.url,
        method=spec.method,
        passed=all_passed,
        status_code=raw.status_code,
        expected_status=spec.expected_status,
        response_time_ms=rounded_ms,
        content_type=raw.content_type,
        size_bytes=raw.size_bytes,
        json_top_keys=json_top_keys,
        checks=checks,
        data_preview=safe_preview,
        redacted_labels=red_labels,
        auth_injected_from_env=spec.auth_env_var,
        error=None,
    )
