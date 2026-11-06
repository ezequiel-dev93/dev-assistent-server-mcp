import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

from ...core.models import DockerServiceStatus, DockerStackReport, TestRunReport
from ...core.ports import IRuntimeQaRunner
from ...core.services.runtime_qa_parser import (
    attach_sanitized_logs,
    parse_docker_compose_ps_json,
    parse_test_runner_output,
    validate_test_filter_args,
)

COMPOSE_CANDIDATE_FILENAMES = (
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
)


def _find_project_python(project_dir: Path) -> Path:
    """Finds project virtual environment python or falls back to sys.executable."""
    candidates = [
        project_dir / ".venv" / "Scripts" / "python.exe",
        project_dir / ".venv" / "bin" / "python",
        project_dir / "venv" / "Scripts" / "python.exe",
        project_dir / "venv" / "bin" / "python",
    ]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK | os.R_OK):
            return c
    return Path(sys.executable)


class ProcessRuntimeQaRunner(IRuntimeQaRunner):
    """
    Driven runtime adapter that executes `docker compose` inspections
    and isolated test suite runs using bounded subprocesses.
    """

    def inspect_docker_compose(
        self, project_dir: Path, tail_logs: int = 30
    ) -> DockerStackReport:
        compose_file: Optional[str] = None
        for cand in COMPOSE_CANDIDATE_FILENAMES:
            if (project_dir / cand).is_file():
                compose_file = cand
                break

        if compose_file is None:
            return DockerStackReport(
                project_name=project_dir.name,
                project_path=str(project_dir),
                compose_file=None,
                daemon_available=False,
                error="No se encontró ningún archivo docker-compose.yml o compose.yaml en el proyecto.",
            )

        cmd = ["docker", "compose", "-f", compose_file, "ps", "--format", "json"]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(project_dir),
                capture_output=True,
                text=True,
                timeout=12.0,
                errors="replace",
            )
        except FileNotFoundError:
            return DockerStackReport(
                project_name=project_dir.name,
                project_path=str(project_dir),
                compose_file=compose_file,
                daemon_available=False,
                error="El ejecutable 'docker' no está disponible en el PATH del sistema.",
            )
        except subprocess.TimeoutExpired:
            return DockerStackReport(
                project_name=project_dir.name,
                project_path=str(project_dir),
                compose_file=compose_file,
                daemon_available=False,
                error="Tiempo de espera agotado al consultar 'docker compose ps' (timeout 12s).",
            )

        if proc.returncode != 0:
            err_msg = proc.stderr.strip() or proc.stdout.strip() or f"Exit code {proc.returncode}"
            daemon_down = any(
                phrase in err_msg.lower()
                for phrase in (
                    "cannot connect to the docker daemon",
                    "is the docker daemon running",
                    "daemon is not running",
                    "error during connect",
                )
            )
            return DockerStackReport(
                project_name=project_dir.name,
                project_path=str(project_dir),
                compose_file=compose_file,
                daemon_available=not daemon_down,
                error=f"Error al inspeccionar docker compose: {err_msg}",
            )

        services = parse_docker_compose_ps_json(proc.stdout)
        bounded_tail = max(5, min(tail_logs, 200))

        # For any service that is exited, restarting or unhealthy, retrieve bounded logs
        for s in services:
            if not s.is_healthy:
                try:
                    log_cmd = [
                        "docker",
                        "compose",
                        "-f",
                        compose_file,
                        "logs",
                        "--tail",
                        str(bounded_tail),
                        "--no-color",
                        s.service,
                    ]
                    log_proc = subprocess.run(
                        log_cmd,
                        cwd=str(project_dir),
                        capture_output=True,
                        text=True,
                        timeout=8.0,
                        errors="replace",
                    )
                    raw_logs = log_proc.stdout if log_proc.returncode == 0 else log_proc.stderr
                    attach_sanitized_logs(s, raw_logs)
                except Exception:
                    pass

        return DockerStackReport(
            project_name=project_dir.name,
            project_path=str(project_dir),
            compose_file=compose_file,
            daemon_available=True,
            services=services,
            error=None,
        )

    def run_test_suite(
        self,
        project_dir: Path,
        target_subpath: Optional[str] = None,
        keyword: Optional[str] = None,
        timeout_seconds: float = 60.0,
    ) -> TestRunReport:
        clean_subpath, clean_keyword = validate_test_filter_args(target_subpath, keyword)
        py_bin = _find_project_python(project_dir)

        # Check if pytest is available in the selected python
        has_pytest = False
        try:
            probe = subprocess.run(
                [str(py_bin), "-c", "import pytest"],
                cwd=str(project_dir),
                capture_output=True,
                timeout=5.0,
            )
            has_pytest = probe.returncode == 0
        except Exception:
            has_pytest = False

        runner = "pytest" if has_pytest else "unittest"
        cmd: List[str] = [str(py_bin), "-m", runner]

        if runner == "pytest":
            cmd.append("-v")
            if clean_subpath:
                cmd.append(clean_subpath)
            if clean_keyword:
                cmd.extend(["-k", clean_keyword])
        else:
            if clean_subpath and (project_dir / clean_subpath).is_file():
                cmd.append(clean_subpath)
            else:
                test_dir = clean_subpath or ("tests" if (project_dir / "tests").is_dir() else ".")
                cmd.extend(["discover", "-s", test_dir, "-p", "test_*.py", "-v"])
            if clean_keyword:
                cmd.extend(["-k", clean_keyword])

        start_time = time.perf_counter()
        bounded_timeout = max(5.0, min(timeout_seconds, 300.0))

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(project_dir),
                capture_output=True,
                text=True,
                timeout=bounded_timeout,
                errors="replace",
            )
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            raw_output = f"{proc.stdout}\n{proc.stderr}".strip()
            exit_code = proc.returncode
        except subprocess.TimeoutExpired as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            raw_output = (
                f"TIMEOUT: La suite de tests superó el límite de {bounded_timeout} segundos.\n"
                f"{exc.stdout or ''}\n{exc.stderr or ''}"
            ).strip()
            exit_code = 124

        cmd_summary = f"{runner} {' '.join(cmd[3:])}".strip()
        return parse_test_runner_output(
            project_name=project_dir.name,
            project_path=str(project_dir),
            runner_used=runner,
            command_summary=cmd_summary,
            exit_code=exit_code,
            raw_output=raw_output,
            duration_ms=duration_ms,
        )
