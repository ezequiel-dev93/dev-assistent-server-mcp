import os
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from ..core.errors import ConfigError, DevAssistantError
from ..core.models import (
    ApiSuiteReport,
    AssertionCheckResult,
    DockerStackReport,
    EndpointRequestSpec,
    EndpointTestResult,
    EnvDockerAuditReport,
    HttpMethod,
    TestRunReport,
)
from ..core.ports import IHttpProbe, IRuntimeQaRunner
from ..core.services.api_qa_evaluator import (
    evaluate_endpoint_response,
    validate_probe_url,
)
from ..core.services.env_docker_auditor import audit_project_env_and_docker
from .markdown_presenter import (
    render_api_suite_report,
    render_docker_stack_report,
    render_endpoint_test_result,
    render_env_docker_audit_report,
    render_test_run_report,
)
from .workspace_guard import WorkspaceGuard

_ENV_VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_SUITE_ENDPOINTS = 30


def _parse_expected_keys(raw_keys: Union[str, Sequence[str], None]) -> List[str]:
    if not raw_keys:
        return []
    if isinstance(raw_keys, str):
        return [k.strip() for k in raw_keys.split(",") if k.strip()]
    return [str(k).strip() for k in raw_keys if str(k).strip()]


def _join_base_and_path(base_url: str, path_or_url: str) -> str:
    cleaned_target = (path_or_url or "").strip()
    cleaned_base = (base_url or "").strip()
    if not cleaned_base or cleaned_target.lower().startswith(("http://", "https://")):
        return cleaned_target
    if not cleaned_target:
        return cleaned_base
    return f"{cleaned_base.rstrip('/')}/{cleaned_target.lstrip('/')}"


class QaTools:
    """Application tools for automated HTTP endpoint testing & freelance QA suites."""

    def __init__(
        self,
        http_probe: IHttpProbe,
        guard: Optional[WorkspaceGuard] = None,
        env: Optional[Mapping[str, str]] = None,
        runtime_runner: Optional[IRuntimeQaRunner] = None,
    ) -> None:
        self.http_probe = http_probe
        self.guard = guard
        self._env = env
        self.runtime_runner = runtime_runner

    def _get_env_value(self, var_name: str) -> str:
        cleaned = var_name.strip()
        if not _ENV_VAR_NAME_RE.match(cleaned):
            raise ConfigError(
                f"Invalid environment variable name '{var_name}'. Expected alphanumeric/underscore identifier."
            )
        source = self._env if self._env is not None else os.environ
        val = source.get(cleaned, "").strip()
        if not val:
            raise ConfigError(
                f"Environment variable '{cleaned}' is not defined or is empty in the local environment."
            )
        return val

    def _build_headers_and_secrets(
        self, spec: EndpointRequestSpec
    ) -> tuple[Dict[str, str], List[str]]:
        headers = {str(k): str(v) for k, v in spec.headers.items()}
        extra_secrets: List[str] = []

        if spec.auth_env_var and spec.auth_env_var.strip():
            secret_val = self._get_env_value(spec.auth_env_var)
            extra_secrets.append(secret_val)
            scheme = spec.auth_scheme.strip()
            header_name = spec.auth_header.strip() or "Authorization"
            if not scheme or scheme.lower() == "raw":
                headers[header_name] = secret_val
            else:
                headers[header_name] = f"{scheme} {secret_val}"

        return headers, extra_secrets

    def run_endpoint_test(
        self,
        url: str,
        method: str = "GET",
        expected_status: int = 200,
        payload: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        query_params: Optional[Dict[str, str]] = None,
        expected_json_keys: Union[str, Sequence[str], None] = None,
        expected_body_contains: Optional[str] = None,
        max_response_time_ms: Optional[float] = None,
        auth_env_var: Optional[str] = None,
        auth_scheme: str = "Bearer",
        auth_header: str = "Authorization",
        timeout_seconds: float = 10.0,
        allow_private_network: bool = True,
        name: str = "",
    ) -> EndpointTestResult:
        method_norm = (method or "GET").strip().upper()
        try:
            method_enum = HttpMethod(method_norm)
        except ValueError as exc:
            allowed = ", ".join(m.value for m in HttpMethod)
            raise ConfigError(
                f"Unsupported HTTP method '{method}'. Allowed methods: {allowed}."
            ) from exc

        validated_url = validate_probe_url(url, allow_private_network=allow_private_network)
        clean_auth_env = auth_env_var.strip() if auth_env_var and auth_env_var.strip() else None
        clean_body_contains = (
            expected_body_contains
            if expected_body_contains and expected_body_contains != ""
            else None
        )

        spec = EndpointRequestSpec(
            name=name.strip(),
            url=validated_url,
            method=method_enum,
            headers=headers or {},
            query_params={str(k): str(v) for k, v in (query_params or {}).items()},
            json_payload=payload,
            auth_env_var=clean_auth_env,
            auth_scheme=auth_scheme,
            auth_header=auth_header,
            expected_status=expected_status,
            max_response_time_ms=max_response_time_ms,
            expected_json_keys=_parse_expected_keys(expected_json_keys),
            expected_body_contains=clean_body_contains,
            timeout_seconds=timeout_seconds,
            allow_private_network=allow_private_network,
        )

        resolved_headers, extra_secrets = self._build_headers_and_secrets(spec)
        raw_response = self.http_probe.send(spec, resolved_headers=resolved_headers)
        return evaluate_endpoint_response(
            spec=spec,
            raw=raw_response,
            extra_secrets=extra_secrets,
        )

    def test_endpoint(
        self,
        url: str,
        method: str = "GET",
        expected_status: int = 200,
        payload: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        query_params: Optional[Dict[str, str]] = None,
        expected_json_keys: str = "",
        expected_body_contains: str = "",
        max_response_time_ms: Optional[float] = None,
        auth_env_var: str = "",
        auth_scheme: str = "Bearer",
        auth_header: str = "Authorization",
        timeout_seconds: float = 10.0,
        allow_private_network: bool = True,
    ) -> str:
        try:
            result = self.run_endpoint_test(
                url=url,
                method=method,
                expected_status=expected_status,
                payload=payload,
                headers=headers,
                query_params=query_params,
                expected_json_keys=expected_json_keys,
                expected_body_contains=expected_body_contains or None,
                max_response_time_ms=max_response_time_ms,
                auth_env_var=auth_env_var or None,
                auth_scheme=auth_scheme,
                auth_header=auth_header,
                timeout_seconds=timeout_seconds,
                allow_private_network=allow_private_network,
            )
            return render_endpoint_test_result(result)
        except (DevAssistantError, ValueError) as exc:
            return f"Error: {exc}"

    def run_suite(
        self,
        endpoints: Sequence[Mapping[str, Any]],
        base_url: str = "",
        suite_name: str = "API QA Suite",
        auth_env_var: str = "",
        auth_scheme: str = "Bearer",
        auth_header: str = "Authorization",
        timeout_seconds: float = 10.0,
        allow_private_network: bool = True,
    ) -> ApiSuiteReport:
        if not endpoints:
            raise ConfigError("Endpoint suite cannot be empty.")
        if len(endpoints) > MAX_SUITE_ENDPOINTS:
            raise ConfigError(
                f"Suite exceeds maximum of {MAX_SUITE_ENDPOINTS} endpoints per run ({len(endpoints)} given)."
            )

        results: List[EndpointTestResult] = []
        for idx, item in enumerate(endpoints, start=1):
            raw_url = str(item.get("url") or item.get("path") or "").strip()
            full_url = _join_base_and_path(base_url, raw_url)
            method_str = str(item.get("method", "GET")).strip().upper()
            case_name = str(item.get("name") or f"#{idx} {method_str} {raw_url or full_url}")
            skip_auth = bool(item.get("skip_auth", False))
            item_auth_env = (
                None
                if skip_auth
                else str(item.get("auth_env_var") or auth_env_var or "").strip() or None
            )

            try:
                res = self.run_endpoint_test(
                    url=full_url,
                    method=method_str,
                    expected_status=int(item.get("expected_status", 200)),
                    payload=item.get("payload"),
                    headers=item.get("headers"),
                    query_params=item.get("query_params"),
                    expected_json_keys=item.get("expected_json_keys"),
                    expected_body_contains=item.get("expected_body_contains"),
                    max_response_time_ms=(
                        float(item["max_response_time_ms"])
                        if item.get("max_response_time_ms") is not None
                        else None
                    ),
                    auth_env_var=item_auth_env,
                    auth_scheme=str(item.get("auth_scheme", auth_scheme)),
                    auth_header=str(item.get("auth_header", auth_header)),
                    timeout_seconds=float(item.get("timeout_seconds", timeout_seconds)),
                    allow_private_network=bool(
                        item.get("allow_private_network", allow_private_network)
                    ),
                    name=case_name,
                )
            except (DevAssistantError, ValueError) as exc:
                safe_method = (
                    HttpMethod(method_str)
                    if method_str in HttpMethod._value2member_map_
                    else HttpMethod.GET
                )
                res = EndpointTestResult(
                    name=case_name,
                    url=full_url or "<empty>",
                    method=safe_method,
                    passed=False,
                    expected_status=int(item.get("expected_status", 200)),
                    checks=[
                        AssertionCheckResult(
                            check="configuration",
                            passed=False,
                            expected="Valid request specification",
                            actual="Configuration/Security Error",
                            message=str(exc),
                        )
                    ],
                    error=str(exc),
                )
            results.append(res)

        return ApiSuiteReport(
            suite_name=suite_name.strip() or "API QA Suite",
            base_url=base_url.strip() or None,
            results=results,
        )

    def test_endpoint_suite(
        self,
        endpoints: Sequence[Mapping[str, Any]],
        base_url: str = "",
        suite_name: str = "API QA Suite",
        auth_env_var: str = "",
        auth_scheme: str = "Bearer",
        auth_header: str = "Authorization",
        timeout_seconds: float = 10.0,
        allow_private_network: bool = True,
    ) -> str:
        try:
            report = self.run_suite(
                endpoints=endpoints,
                base_url=base_url,
                suite_name=suite_name,
                auth_env_var=auth_env_var,
                auth_scheme=auth_scheme,
                auth_header=auth_header,
                timeout_seconds=timeout_seconds,
                allow_private_network=allow_private_network,
            )
            return render_api_suite_report(report)
        except (DevAssistantError, ValueError) as exc:
            return f"Error: {exc}"

    def _resolve_project_dir(self, project_name_or_path: str) -> Path:
        if self.guard is not None:
            target = self.guard.resolve(project_name_or_path, must_exist=True)
        else:
            target = Path(project_name_or_path).resolve()
            if not target.exists():
                raise FileNotFoundError(f"Path '{project_name_or_path}' does not exist.")
        if not target.is_dir():
            raise FileNotFoundError(f"'{project_name_or_path}' is not a valid project directory.")
        return target

    def run_env_docker_audit(self, project_name_or_path: str) -> EnvDockerAuditReport:
        project_dir = self._resolve_project_dir(project_name_or_path)

        env_file = project_dir / ".env"
        env_content = (
            env_file.read_text(encoding="utf-8", errors="replace")
            if env_file.is_file()
            else None
        )

        env_example_content: Optional[str] = None
        env_example_name = ".env.example"
        for cand_name in (".env.example", ".env.template", ".env.sample"):
            cand_path = project_dir / cand_name
            if cand_path.is_file():
                env_example_content = cand_path.read_text(encoding="utf-8", errors="replace")
                env_example_name = cand_name
                break

        compose_files: Dict[str, str] = {}
        for comp_name in (
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
        ):
            comp_path = project_dir / comp_name
            if comp_path.is_file():
                compose_files[comp_name] = comp_path.read_text(
                    encoding="utf-8", errors="replace"
                )

        dockerfiles: Dict[str, str] = {}
        for item in sorted(project_dir.iterdir()):
            if item.is_file() and (
                item.name == "Dockerfile" or item.name.startswith("Dockerfile.")
            ):
                dockerfiles[item.name] = item.read_text(encoding="utf-8", errors="replace")

        dockerignore_file = project_dir / ".dockerignore"
        dockerignore_content = (
            dockerignore_file.read_text(encoding="utf-8", errors="replace")
            if dockerignore_file.is_file()
            else None
        )

        return audit_project_env_and_docker(
            project_name=project_dir.name,
            project_path=str(project_dir),
            env_content=env_content,
            env_example_content=env_example_content,
            env_example_name=env_example_name,
            compose_files=compose_files,
            dockerfiles=dockerfiles,
            dockerignore_content=dockerignore_content,
        )

    def audit_env_and_docker(self, project_name_or_path: str) -> str:
        try:
            report = self.run_env_docker_audit(project_name_or_path)
            return render_env_docker_audit_report(report)
        except (DevAssistantError, FileNotFoundError, ValueError, OSError) as exc:
            return f"Error: {exc}"

    def run_docker_stack_inspection(
        self, project_name_or_path: str, tail_logs: int = 30
    ) -> DockerStackReport:
        if self.runtime_runner is None:
            raise ConfigError("Runtime QA runner is not configured.")
        project_dir = self._resolve_project_dir(project_name_or_path)
        return self.runtime_runner.inspect_docker_compose(project_dir, tail_logs=tail_logs)

    def inspect_docker_stack(
        self, project_name_or_path: str, tail_logs: int = 30
    ) -> str:
        try:
            report = self.run_docker_stack_inspection(project_name_or_path, tail_logs=tail_logs)
            return render_docker_stack_report(report)
        except (DevAssistantError, FileNotFoundError, ValueError, OSError) as exc:
            return f"Error: {exc}"

    def run_tests(
        self,
        project_name_or_path: str,
        target_subpath: Optional[str] = None,
        keyword: Optional[str] = None,
        timeout_seconds: float = 60.0,
    ) -> TestRunReport:
        if self.runtime_runner is None:
            raise ConfigError("Runtime QA runner is not configured.")
        project_dir = self._resolve_project_dir(project_name_or_path)
        return self.runtime_runner.run_test_suite(
            project_dir=project_dir,
            target_subpath=target_subpath,
            keyword=keyword,
            timeout_seconds=timeout_seconds,
        )

    def run_project_tests(
        self,
        project_name_or_path: str,
        target_subpath: str = "",
        keyword: str = "",
        timeout_seconds: float = 60.0,
    ) -> str:
        try:
            report = self.run_tests(
                project_name_or_path,
                target_subpath=target_subpath or None,
                keyword=keyword or None,
                timeout_seconds=timeout_seconds,
            )
            return render_test_run_report(report)
        except (DevAssistantError, FileNotFoundError, ValueError, OSError) as exc:
            return f"Error: {exc}"


