import json
import os
import re
from typing import List, Optional, Set, Tuple
from src.core.models import (
    ArchitectureAuditReport,
    ArchitecturePattern,
    ArchitectureViolation,
    ProjectDetail,
    ProjectStack,
    ProjectSummary,
)
from src.core.ports import IProjectScanner

IGNORED_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    "dist",
    "build",
    ".astro",
    ".next",
    ".turbo",
    "data",
}

FORBIDDEN_IN_DOMAIN_OR_CORE = {
    "infrastructure",
    "adapters",
    "fastapi",
    "streamlit",
    "flask",
    "django",
    "sqlalchemy",
    "sqlite3",
    "psycopg2",
    "asyncpg",
    "boto3",
    "requests",
    "httpx",
    "redis",
    "celery",
}

FORBIDDEN_IN_UI_COMPONENTS = {
    "sqlite3",
    "sqlalchemy",
    "psycopg2",
    "pg",
    "prisma",
    "@prisma/client",
    "mongoose",
}


class FileSystemProjectScanner(IProjectScanner):
    """Adaptador de infraestructura que analiza proyectos reales en el sistema de archivos."""

    def scan_workspace(self, root_dir: str) -> List[ProjectSummary]:
        results: List[ProjectSummary] = []
        abs_root = os.path.abspath(root_dir)

        if not os.path.isdir(abs_root):
            return results

        # Escanear subdirectorios inmediatos
        for item in os.listdir(abs_root):
            item_path = os.path.join(abs_root, item)
            if not os.path.isdir(item_path) or item in IGNORED_DIRS:
                continue

            # Verificar si este subdirectorio es un proyecto
            if self._is_project_dir(item_path):
                detail = self.inspect_project(item_path)
                results.append(
                    ProjectSummary(
                        name=detail.name,
                        path=detail.path,
                        stack=detail.stack,
                        detected_architectures=detail.detected_architectures,
                        technologies=detail.technologies,
                        has_tests=detail.has_tests,
                        has_docker=detail.has_docker,
                    )
                )

        return results

    def inspect_project(self, project_path: str) -> ProjectDetail:
        abs_path = os.path.abspath(project_path)
        name = os.path.basename(abs_path)

        stack, technologies = self._detect_stack_and_tech(abs_path)
        architectures, key_dirs = self._detect_architecture(abs_path)
        has_tests = self._check_tests(abs_path)
        has_docker = self._check_docker(abs_path)
        summary_desc = self._extract_readme_summary(abs_path)
        guidelines = self._generate_guidelines(stack, architectures)

        return ProjectDetail(
            name=name,
            path=abs_path,
            stack=stack,
            detected_architectures=architectures,
            technologies=technologies,
            has_tests=has_tests,
            has_docker=has_docker,
            key_directories=key_dirs,
            architecture_guidelines=guidelines,
            summary_description=summary_desc,
        )

    def audit_architecture(self, project_path: str) -> ArchitectureAuditReport:
        abs_path = os.path.abspath(project_path)
        name = os.path.basename(abs_path)
        architectures, _ = self._detect_architecture(abs_path)

        violations: List[ArchitectureViolation] = []
        files_scanned = 0
        code_extensions = {".py", ".ts", ".tsx", ".js", ".jsx", ".astro"}

        for root, dirs, files in os.walk(abs_path):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            rel_root = os.path.relpath(root, abs_path).replace("\\", "/")
            path_parts = [p.lower() for p in rel_root.split("/") if p and p != "."]

            in_core_or_domain = any(p in ("core", "domain", "ports", "entities") for p in path_parts)
            in_ui_components = "components" in path_parts

            for fname in files:
                _, ext = os.path.splitext(fname)
                if ext.lower() not in code_extensions:
                    continue

                files_scanned += 1
                if not (in_core_or_domain or in_ui_components):
                    continue

                full_file_path = os.path.join(root, fname)
                rel_file_path = os.path.relpath(full_file_path, abs_path).replace("\\", "/")

                try:
                    with open(full_file_path, "r", encoding="utf-8", errors="ignore") as f:
                        for line_idx, raw_line in enumerate(f, start=1):
                            line = raw_line.strip()
                            if not line or line.startswith("#") or line.startswith("//"):
                                continue

                            imported_targets = self._extract_imported_modules(line)
                            if not imported_targets:
                                continue

                            if in_core_or_domain:
                                for target in imported_targets:
                                    root_pkg = target.split(".")[0].split("/")[0].lower()
                                    if (
                                        root_pkg in FORBIDDEN_IN_DOMAIN_OR_CORE
                                        or "infrastructure" in target.lower()
                                        or "adapters" in target.lower()
                                    ):
                                        violations.append(
                                            ArchitectureViolation(
                                                file_path=rel_file_path,
                                                line_number=line_idx,
                                                offending_statement=line,
                                                rule_broken=(
                                                    f"Hexagonal Architecture Violation: Core/Domain layer cannot depend on "
                                                    f"external framework or infrastructure module '{target}'. Inject via Ports instead."
                                                ),
                                                severity="ERROR",
                                            )
                                        )
                                        break

                            if in_ui_components:
                                for target in imported_targets:
                                    target_low = target.lower()
                                    if any(
                                        forbidden in target_low
                                        for forbidden in FORBIDDEN_IN_UI_COMPONENTS
                                    ):
                                        violations.append(
                                            ArchitectureViolation(
                                                file_path=rel_file_path,
                                                line_number=line_idx,
                                                offending_statement=line,
                                                rule_broken=(
                                                    f"Screaming/Clean UI Violation: UI Component directly imports persistence/DB "
                                                    f"client '{target}'. Delegate data access to a Service or Use Case."
                                                ),
                                                severity="ERROR",
                                            )
                                        )
                                        break
                except Exception:
                    pass

        return ArchitectureAuditReport(
            project_name=name,
            project_path=abs_path,
            detected_architectures=architectures,
            files_scanned=files_scanned,
            is_compliant=len(violations) == 0,
            violations=violations,
        )

    def _extract_imported_modules(self, line: str) -> List[str]:
        targets: List[str] = []
        # Python: from X import Y  |  import X
        py_from = re.match(r"^from\s+([a-zA-Z0-9_\.]+)\s+import\s+", line)
        if py_from:
            targets.append(py_from.group(1))
            return targets

        py_import = re.match(r"^import\s+([a-zA-Z0-9_\.,\s]+)", line)
        if py_import:
            raw_mods = py_import.group(1).split(",")
            for m in raw_mods:
                clean_m = m.strip().split(" ")[0]
                if clean_m:
                    targets.append(clean_m)
            return targets

        # TypeScript / JS: import ... from 'X' or "X"
        ts_from = re.search(r"(?:import|from)\s+['\"]([^'\"]+)['\"]", line)
        if ts_from:
            targets.append(ts_from.group(1))

        return targets

    def _is_project_dir(self, dir_path: str) -> bool:
        project_indicators = [
            "package.json",
            "pyproject.toml",
            "requirements.txt",
            "Pipfile",
            "astro.config.mjs",
            "next.config.js",
            "next.config.mjs",
            "next.config.ts",
            "Dockerfile",
            "src",
        ]
        return any(os.path.exists(os.path.join(dir_path, ind)) for ind in project_indicators)

    def _detect_stack_and_tech(self, dir_path: str) -> Tuple[ProjectStack, List[str]]:
        technologies: Set[str] = set()
        stack = ProjectStack.UNKNOWN

        # 1. Analizar package.json si existe
        pkg_json_path = os.path.join(dir_path, "package.json")
        if os.path.exists(pkg_json_path):
            try:
                with open(pkg_json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    deps = {
                        **data.get("dependencies", {}),
                        **data.get("devDependencies", {}),
                    }

                    if "astro" in deps:
                        stack = ProjectStack.ASTRO
                        technologies.add("astro")
                    elif "next" in deps:
                        stack = ProjectStack.NEXTJS
                        technologies.add("nextjs")
                    elif "react" in deps:
                        if stack == ProjectStack.UNKNOWN:
                            stack = ProjectStack.REACT
                        technologies.add("react")
                    else:
                        if stack == ProjectStack.UNKNOWN:
                            stack = ProjectStack.NODE_GENERIC

                    # Detectar tecnologías comunes en Node
                    for tech_key in [
                        "supabase",
                        "@supabase/supabase-js",
                        "@supabase/ssr",
                        "stripe",
                        "mercadopago",
                        "tailwindcss",
                        "typescript",
                        "zod",
                        "@modelcontextprotocol/sdk",
                    ]:
                        if any(tech_key in dep for dep in deps):
                            technologies.add(tech_key)
            except Exception:
                pass

        # 2. Analizar Python (pyproject.toml o requirements.txt)
        py_files = ["requirements.txt", "pyproject.toml", "Pipfile"]
        for py_file in py_files:
            file_path = os.path.join(dir_path, py_file)
            if os.path.exists(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read().lower()

                        if "fastapi" in content:
                            stack = ProjectStack.FASTAPI
                            technologies.add("fastapi")
                        elif "streamlit" in content:
                            stack = ProjectStack.STREAMLIT
                            technologies.add("streamlit")
                        elif stack == ProjectStack.UNKNOWN:
                            stack = ProjectStack.PYTHON_GENERIC

                        for tech_key in [
                            "sqlalchemy",
                            "alembic",
                            "redis",
                            "pydantic",
                            "arq",
                            "celery",
                            "stripe",
                            "mercadopago",
                            "pgvector",
                            "boto3",
                            "cognito",
                            "slowapi",
                            "jose",
                            "pyjwt",
                            "openai",
                            "anthropic",
                            "google-genai",
                            "google-generativeai",
                            "mcp",
                        ]:
                            if tech_key in content:
                                technologies.add(tech_key)
                except Exception:
                    pass

        return stack, sorted(list(technologies))

    def _detect_architecture(
        self, dir_path: str
    ) -> Tuple[List[ArchitecturePattern], List[str]]:
        patterns: List[ArchitecturePattern] = []
        found_dirs: Set[str] = set()

        for root, dirs, _ in os.walk(dir_path):
            rel_root = os.path.relpath(root, dir_path).replace("\\", "/")
            if any(part in IGNORED_DIRS for part in rel_root.split("/")):
                continue

            for d in dirs:
                if d in IGNORED_DIRS:
                    continue
                full_rel = os.path.normpath(os.path.join(rel_root, d)).replace("\\", "/")
                if full_rel.startswith("."):
                    continue
                found_dirs.add(full_rel)

        dir_names = {os.path.basename(d).lower() for d in found_dirs}

        # Detección de Hexagonal (Ports & Adapters)
        has_ports_adapters = ("ports" in dir_names and "adapters" in dir_names) or (
            "core" in dir_names and "infrastructure" in dir_names
        )
        if has_ports_adapters:
            patterns.append(ArchitecturePattern.HEXAGONAL)

        # Detección de Screaming Architecture (Feature-driven / Modules)
        has_screaming = "modules" in dir_names or "features" in dir_names
        if has_screaming:
            patterns.append(ArchitecturePattern.SCREAMING)

        # Detección de Clean / Layered tradicional
        if "domain" in dir_names and "application" in dir_names:
            if ArchitecturePattern.HEXAGONAL not in patterns:
                patterns.append(ArchitecturePattern.CLEAN_LAYERED)

        if not patterns:
            patterns.append(ArchitecturePattern.FLAT)

        key_structural_dirs = [
            d
            for d in sorted(list(found_dirs))
            if any(
                k in d.split("/")
                for k in [
                    "core",
                    "domain",
                    "infrastructure",
                    "application",
                    "modules",
                    "features",
                    "components",
                    "api",
                    "routes",
                    "pages",
                    "services",
                    "adapters",
                    "ports",
                ]
            )
        ]

        return patterns, key_structural_dirs[:15]

    def _check_tests(self, dir_path: str) -> bool:
        test_indicators = ["tests", "test", "__tests__"]
        return any(os.path.isdir(os.path.join(dir_path, ind)) for ind in test_indicators)

    def _check_docker(self, dir_path: str) -> bool:
        docker_files = ["Dockerfile", "docker-compose.yml", "compose.yaml", "compose.yml"]
        return any(os.path.isfile(os.path.join(dir_path, f)) for f in docker_files)

    def _extract_readme_summary(self, dir_path: str) -> Optional[str]:
        for candidate in ["README.md", "Readme.md", "README.es.md"]:
            readme_path = os.path.join(dir_path, candidate)
            if os.path.isfile(readme_path):
                try:
                    with open(readme_path, "r", encoding="utf-8") as f:
                        lines = [line.strip() for line in f.readlines()[:12] if line.strip()]
                        return "\n".join(lines[:6])
                except Exception:
                    pass
        return None

    def _generate_guidelines(
        self, stack: ProjectStack, architectures: List[ArchitecturePattern]
    ) -> List[str]:
        guidelines = []

        if ArchitecturePattern.HEXAGONAL in architectures:
            guidelines.append(
                "Arquitectura Hexagonal (Backend): Mantener la lógica de negocio pura en core/domain. "
                "Definir contratos (interfaces/puertos) y colocar dependencias externas en infrastructure/adapters."
            )

        if ArchitecturePattern.SCREAMING in architectures:
            guidelines.append(
                "Screaming Architecture (Frontend/Módulos): Organizar por dominio/feature en modules/ o features/. "
                "Cada módulo encapsula sus componentes, tipos, servicios y llamadas a API."
            )

        if stack == ProjectStack.ASTRO:
            guidelines.append(
                "Astro: Priorizar renderizado estático/islas. Cargar componentes interactivos con client:load o client:idle solo cuando sea indispensable."
            )
        elif stack == ProjectStack.FASTAPI:
            guidelines.append(
                "FastAPI: Usar tipado estricto con Pydantic v2, inyección de dependencias (Depends) y SQLAlchemy 2.0 moderno."
            )

        return guidelines
