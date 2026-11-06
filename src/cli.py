import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .core.errors import ConfigError, DevAssistantError
from .core.models import Severity
from .infrastructure.reporting.sarif import format_audit_sarif
from .server import build_container, run_server
from .settings import Settings


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dev-assistant-mcp",
        description="DevAssistant MCP Server & Architectural Governance CLI (v2.0).",
    )
    parser.add_argument(
        "--version", action="version", version=f"dev-assistant-mcp {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", required=False)

    # 1. serve (default when no subcommand is given)
    subparsers.add_parser("serve", help="Start the MCP server over stdio (default).")

    # 2. audit
    audit_p = subparsers.add_parser(
        "audit", help="Run static architectural boundary & cycle audit (CI-ready)."
    )
    audit_p.add_argument("path", nargs="?", default=".", help="Project path to audit.")
    audit_p.add_argument(
        "--format",
        choices=["text", "json", "sarif"],
        default="text",
        help="Output format (default: text).",
    )
    audit_p.add_argument(
        "--fail-on",
        choices=["error", "warning", "never"],
        default="error",
        help="Minimum severity that triggers exit code 1 (default: error).",
    )
    audit_p.add_argument("--output", "-o", default="", help="Optional file path to write report.")

    # 3. memory
    mem_p = subparsers.add_parser("memory", help="Export, import, or redact local SQLite memories.")
    mem_sub = mem_p.add_subparsers(dest="memory_cmd", required=True)

    exp_p = mem_sub.add_parser("export", help="Export memories to versioned JSON.")
    exp_p.add_argument("--project", default="", help="Filter by project name.")
    exp_p.add_argument("--output", "-o", default="", help="Output JSON file path.")

    imp_p = mem_sub.add_parser("import", help="Idempotently import memories from JSON file.")
    imp_p.add_argument("file", help="Input JSON file path.")

    # 4. adr
    adr_p = subparsers.add_parser("adr", help="Check ADR drift or promote memories to MADR files.")
    adr_sub = adr_p.add_subparsers(dest="adr_cmd", required=True)

    drift_p = adr_sub.add_parser("drift", help="Verify accepted ADRs against live architecture rules.")
    drift_p.add_argument("path", nargs="?", default=".", help="Project path.")
    drift_p.add_argument(
        "--fail-on",
        choices=["error", "warning", "never"],
        default="error",
    )

    prom_p = adr_sub.add_parser(
        "import-from-memory", help="Promote decision/architecture memories into MADR files."
    )
    prom_p.add_argument("path", nargs="?", default=".", help="Project path.")
    prom_p.add_argument(
        "--apply",
        action="store_true",
        help="Write files to disk (defaults to dry-run preview).",
    )

    # 5. qa
    qa_p = subparsers.add_parser("qa", help="Run automated API endpoint QA checks.")
    qa_sub = qa_p.add_subparsers(dest="qa_cmd", required=True)

    ep_p = qa_sub.add_parser("endpoint", help="Probe a single HTTP endpoint and verify assertions.")
    ep_p.add_argument("url", help="Target HTTP/HTTPS URL.")
    ep_p.add_argument("--method", "-X", default="GET", help="HTTP method (default: GET).")
    ep_p.add_argument(
        "--expect-status", type=int, default=200, help="Expected HTTP status code (default: 200)."
    )
    ep_p.add_argument(
        "--expect-keys", default="", help="Comma-separated expected JSON dot-paths."
    )
    ep_p.add_argument(
        "--max-ms", type=float, default=None, help="Maximum allowed response time in milliseconds."
    )
    ep_p.add_argument(
        "--auth-env", default="", help="Environment variable holding auth token."
    )
    ep_p.add_argument(
        "--payload", default="", help="Optional JSON request payload string."
    )
    ep_p.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format."
    )

    ed_p = qa_sub.add_parser(
        "env-docker",
        help="Statically audit .env, .env.example, docker-compose.yml, Dockerfile, and .dockerignore.",
    )
    ed_p.add_argument("path", nargs="?", default=".", help="Project path.")
    ed_p.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format."
    )
    ed_p.add_argument(
        "--fail-on",
        choices=["error", "warning", "never"],
        default="error",
        help="Minimum severity that triggers exit code 1 (default: error).",
    )

    dk_p = qa_sub.add_parser("docker", help="Inspect docker compose stack status, health, and logs.")
    dk_p.add_argument("path", nargs="?", default=".", help="Project path.")
    dk_p.add_argument(
        "--tail",
        type=int,
        default=30,
        help="Number of log lines for unhealthy containers (default: 30).",
    )
    dk_p.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format."
    )

    t_p = qa_sub.add_parser(
        "test", help="Run project test suite (pytest or unittest) in an isolated process."
    )
    t_p.add_argument("path", nargs="?", default=".", help="Project path.")
    t_p.add_argument("--target", default="", help="Subpath or file to test.")
    t_p.add_argument("-k", "--keyword", default="", help="Filter tests by keyword expression.")
    t_p.add_argument(
        "--timeout", type=float, default=60.0, help="Timeout in seconds (default: 60.0)."
    )
    t_p.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format."
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command in (None, "serve"):
        run_server()
        return 0

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    if args.command == "audit":
        target_path = Path(args.path).resolve()
        if not target_path.is_dir():
            print(f"Error: Directory not found: {target_path}", file=sys.stderr)
            return 2

        settings = Settings.from_env()
        if target_path not in settings.workspace_roots:
            settings.workspace_roots.insert(0, target_path)
        container = build_container(settings=settings)

        try:
            report = container.project_tools.run_audit(str(target_path))
            detail = container.scanner.inspect_project(str(target_path))
            rules = container.config_loader.load(
                target_path,
                [a.value for a in detail.detected_architectures],
                detail.stack.value,
            )
        except ConfigError as exc:
            print(f"Configuration error: {exc}", file=sys.stderr)
            return 2
        except DevAssistantError as exc:
            print(f"Audit error: {exc}", file=sys.stderr)
            return 2

        if args.format == "sarif":
            rendered = format_audit_sarif(report, rules=rules)
        elif args.format == "json":
            rendered = json.dumps(
                {
                    **report.model_dump(mode="json"),
                    "is_compliant": report.is_compliant,
                },
                indent=2,
                ensure_ascii=False,
            )
        else:
            rendered = container.project_tools.audit_project_architecture(str(target_path))

        if args.output:
            out_file = Path(args.output)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(rendered, encoding="utf-8")
        else:
            print(rendered)

        if args.fail_on == "never":
            return 0
        threshold = Severity.ERROR if args.fail_on == "error" else Severity.WARNING
        return 1 if report.fails_on(threshold) else 0

    if args.command == "memory":
        container = build_container()
        if args.memory_cmd == "export":
            payload = container.memory_tools.export_json_payload(
                project_name=args.project or None
            )
            if args.output:
                Path(args.output).write_text(payload, encoding="utf-8")
                print(f"Exported memories to {args.output}")
            else:
                print(payload)
            return 0

        if args.memory_cmd == "import":
            in_path = Path(args.file)
            if not in_path.is_file():
                print(f"Error: File not found: {in_path}", file=sys.stderr)
                return 2
            stats = container.memory_tools.import_json_payload(
                in_path.read_text(encoding="utf-8")
            )
            print(
                f"Imported {stats['imported']} memories ({stats['redacted_entries']} had secrets redacted)."
            )
            return 0

    if args.command == "adr":
        target_path = Path(args.path).resolve()
        settings = Settings.from_env()
        if target_path not in settings.workspace_roots:
            settings.workspace_roots.insert(0, target_path)
        container = build_container(settings=settings)

        if args.adr_cmd == "drift":
            try:
                drift_report = container.adr_tools.run_drift_check(str(target_path))
            except ConfigError as exc:
                print(f"Configuration error: {exc}", file=sys.stderr)
                return 2
            print(container.adr_tools.check_adr_drift(str(target_path)))
            if args.fail_on == "never":
                return 0
            if args.fail_on == "error" and drift_report.has_drift:
                return 1
            if args.fail_on == "warning" and any(
                i.severity in (Severity.ERROR, Severity.WARNING) for i in drift_report.items
            ):
                return 1
            return 0

        if args.adr_cmd == "import-from-memory":
            res = container.adr_tools.import_candidates_from_memory(
                str(target_path), dry_run=not args.apply
            )
            print(res)
            return 0

    if args.command == "qa":
        container = build_container()
        if args.qa_cmd == "endpoint":
            parsed_payload = None
            if args.payload:
                try:
                    parsed_payload = json.loads(args.payload)
                except json.JSONDecodeError as exc:
                    print(f"Invalid --payload JSON: {exc}", file=sys.stderr)
                    return 2

            try:
                result = container.qa_tools.run_endpoint_test(
                    url=args.url,
                    method=args.method,
                    expected_status=args.expect_status,
                    payload=parsed_payload,
                    expected_json_keys=args.expect_keys,
                    max_response_time_ms=args.max_ms,
                    auth_env_var=args.auth_env or None,
                )
            except DevAssistantError as exc:
                print(f"QA error: {exc}", file=sys.stderr)
                return 2

            if args.format == "json":
                print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
            else:
                from .tools.markdown_presenter import render_endpoint_test_result

                print(render_endpoint_test_result(result))
            return 0 if result.passed else 1

        if args.qa_cmd == "env-docker":
            target_path = Path(args.path).resolve()
            if not target_path.is_dir():
                print(f"Error: Directory not found: {target_path}", file=sys.stderr)
                return 2

            settings = Settings.from_env()
            if target_path not in settings.workspace_roots:
                settings.workspace_roots.insert(0, target_path)
            container = build_container(settings=settings)

            try:
                report = container.qa_tools.run_env_docker_audit(str(target_path))
            except (DevAssistantError, FileNotFoundError, ValueError) as exc:
                print(f"QA error: {exc}", file=sys.stderr)
                return 2

            if args.format == "json":
                print(
                    json.dumps(
                        {
                            **report.model_dump(mode="json"),
                            "is_compliant": report.is_compliant,
                        },
                        indent=2,
                        ensure_ascii=False,
                    )
                )
            else:
                from .tools.markdown_presenter import render_env_docker_audit_report

                print(render_env_docker_audit_report(report))

            if args.fail_on == "never":
                return 0
            if args.fail_on == "error":
                return 1 if report.error_count > 0 else 0
            return 1 if (report.error_count + report.warning_count) > 0 else 0

        if args.qa_cmd == "docker":
            target_path = Path(args.path).resolve()
            if not target_path.is_dir():
                print(f"Error: Directory not found: {target_path}", file=sys.stderr)
                return 2

            settings = Settings.from_env()
            if target_path not in settings.workspace_roots:
                settings.workspace_roots.insert(0, target_path)
            container = build_container(settings=settings)

            try:
                report = container.qa_tools.run_docker_stack_inspection(
                    str(target_path), tail_logs=args.tail
                )
            except (DevAssistantError, FileNotFoundError, ValueError) as exc:
                print(f"QA error: {exc}", file=sys.stderr)
                return 2

            if args.format == "json":
                print(json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False))
            else:
                from .tools.markdown_presenter import render_docker_stack_report

                print(render_docker_stack_report(report))
            return 0 if (report.all_healthy or not report.services) and not report.error else 1

        if args.qa_cmd == "test":
            target_path = Path(args.path).resolve()
            if not target_path.is_dir():
                print(f"Error: Directory not found: {target_path}", file=sys.stderr)
                return 2

            settings = Settings.from_env()
            if target_path not in settings.workspace_roots:
                settings.workspace_roots.insert(0, target_path)
            container = build_container(settings=settings)

            try:
                report = container.qa_tools.run_tests(
                    str(target_path),
                    target_subpath=args.target or None,
                    keyword=args.keyword or None,
                    timeout_seconds=args.timeout,
                )
            except (DevAssistantError, FileNotFoundError, ValueError) as exc:
                print(f"QA error: {exc}", file=sys.stderr)
                return 2

            if args.format == "json":
                print(json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False))
            else:
                from .tools.markdown_presenter import render_test_run_report

                print(render_test_run_report(report))
            return 0 if report.passed else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
