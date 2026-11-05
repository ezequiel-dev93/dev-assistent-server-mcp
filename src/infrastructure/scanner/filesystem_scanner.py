import json
import os
import re
from pathlib import Path
from typing import List, Optional, Set, Tuple
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

from ...core.errors import UnparseableFileError
from ...core.models import (
    ArchitectureAuditReport,
    ArchitecturePattern,
    ArchitectureViolation,
    ProjectDetail,
    ProjectStack,
    ProjectSummary,
    Severity,
)
from ...core.ports import (
    IImportExtractor,
    IModuleResolver,
    IProjectConfigLoader,
    IProjectScanner,
)
from ...core.services.rules_engine import (
    ResolvedImportEdge,
    evaluate_project_rules,
)
from ..config.toml_loader import TomlProjectConfigLoader
from ..extractors.python_ast import PythonAstExtractor
from ..extractors.typescript_regex import TypescriptRegexExtractor
from ..resolvers.module_resolver import ProjectModuleResolver

SCAN_IGNORED_DIRS = {
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
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "data",
}

AUDIT_IGNORED_DIRS = SCAN_IGNORED_DIRS - {"data"}

_HTML_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
_REQ_NAME_RE = re.compile(r"^([A-Za-z0-9_\-\.]+)")

PYTHON_TECH_MAP = {
    "fastapi": "fastapi",
    "streamlit": "streamlit",
    "django": "django",
    "sqlalchemy": "sqlalchemy",
    "alembic": "alembic",
    "redis": "redis",
    "pydantic": "pydantic",
    "arq": "arq",
    "celery": "celery",
    "stripe": "stripe",
    "mercadopago": "mercadopago",
    "pgvector": "pgvector",
    "boto3": "boto3",
    "slowapi": "slowapi",
    "python-jose": "jose",
    "jose": "jose",
    "pyjwt": "pyjwt",
    "openai": "openai",
    "anthropic": "anthropic",
    "google-genai": "google-genai",
    "google-generativeai": "google-generativeai",
    "mcp": "mcp",
}


class FileSystemProjectScanner(IProjectScanner):
    """Filesystem adapter for scanning, inspecting, and auditing software projects."""

    def __init__(
        self,
        extractors: Optional[List[IImportExtractor]] = None,
        resolver: Optional[IModuleResolver] = None,
        config_loader: Optional[IProjectConfigLoader] = None,
    ) -> None:
        self.extractors: List[IImportExtractor] = extractors or [
            PythonAstExtractor(),
            TypescriptRegexExtractor(),
        ]
        self.resolver: IModuleResolver = resolver or ProjectModuleResolver()
        self.config_loader: IProjectConfigLoader = config_loader or TomlProjectConfigLoader()

    def scan_workspace(self, root_dir: str) -> List[ProjectSummary]:
        results: List[ProjectSummary] = []
        abs_root = os.path.abspath(root_dir)

        if not os.path.isdir(abs_root):
            return results

        for item in sorted(os.listdir(abs_root)):
            item_path = os.path.join(abs_root, item)
            if not os.path.isdir(item_path) or item in SCAN_IGNORED_DIRS or item.startswith("."):
                continue

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
        abs_path = Path(project_path).resolve()
        name = abs_path.name
        stack, _ = self._detect_stack_and_tech(str(abs_path))
        architectures, _ = self._detect_architecture(str(abs_path))

        pattern_names = [a.value for a in architectures]
        rules = self.config_loader.load(abs_path, pattern_names, stack.value)

        edges: List[ResolvedImportEdge] = []
        parse_findings: List[ArchitectureViolation] = []
        files_scanned = 0

        for root, dirs, files in os.walk(abs_path):
            dirs[:] = [
                d for d in dirs if d not in AUDIT_IGNORED_DIRS and not d.startswith(".")
            ]
            for fname in sorted(files):
                fpath = Path(root) / fname
                extractor = self._find_extractor(fpath)
                if not extractor:
                    continue

                try:
                    if fpath.stat().st_size > 2_000_000:
                        continue
                except OSError:
                    continue

                files_scanned += 1
                rel_source = fpath.relative_to(abs_path).as_posix()

                try:
                    import_refs = extractor.extract(fpath, abs_path)
                except UnparseableFileError as exc:
                    parse_findings.append(
                        ArchitectureViolation(
                            rule_id="unparseable-file",
                            file_path=rel_source,
                            line_number=1,
                            offending_statement="<syntax or encoding error>",
                            rule_broken=f"File could not be parsed: {exc.cause}",
                            severity=Severity.INFO,
                        )
                    )
                    continue

                for ref in import_refs:
                    internal_target = self.resolver.resolve_internal(
                        ref.module, fpath, abs_path
                    )
                    if internal_target is not None:
                        edges.append(
                            ResolvedImportEdge(
                                source_file=rel_source,
                                import_ref=ref,
                                target_file=internal_target.as_posix(),
                                external_package=None,
                            )
                        )
                    elif not self.resolver.is_stdlib(ref.module, fpath):
                        edges.append(
                            ResolvedImportEdge(
                                source_file=rel_source,
                                import_ref=ref,
                                target_file=None,
                                external_package=ref.module,
                            )
                        )

        rule_violations = evaluate_project_rules(edges=edges, rules=rules)
        all_violations = rule_violations + parse_findings

        return ArchitectureAuditReport(
            project_name=name,
            project_path=str(abs_path),
            preset_used=rules.preset,
            detected_architectures=architectures,
            files_scanned=files_scanned,
            violations=all_violations,
        )

    def _find_extractor(self, file_path: Path) -> Optional[IImportExtractor]:
        for ext in self.extractors:
            if ext.supports(file_path):
                return ext
        return None

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
        node_stack: ProjectStack = ProjectStack.UNKNOWN
        py_stack: ProjectStack = ProjectStack.UNKNOWN

        pkg_json_path = os.path.join(dir_path, "package.json")
        if os.path.exists(pkg_json_path):
            try:
                with open(pkg_json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    deps = {
                        **data.get("dependencies", {}),
                        **data.get("devDependencies", {}),
                    }
                    dep_keys = {k.lower() for k in deps.keys()}

                    if "astro" in dep_keys:
                        node_stack = ProjectStack.ASTRO
                        technologies.add("astro")
                    elif "next" in dep_keys:
                        node_stack = ProjectStack.NEXTJS
                        technologies.add("nextjs")
                    elif "@nestjs/core" in dep_keys:
                        node_stack = ProjectStack.NESTJS
                        technologies.add("nestjs")
                    elif "react" in dep_keys:
                        node_stack = ProjectStack.REACT
                        technologies.add("react")
                    else:
                        node_stack = ProjectStack.NODE_GENERIC

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
                        if tech_key in dep_keys:
                            technologies.add(tech_key)
            except Exception:
                pass

        py_deps: Set[str] = set()
        pyproject_path = os.path.join(dir_path, "pyproject.toml")
        if os.path.isfile(pyproject_path):
            py_stack = ProjectStack.PYTHON_GENERIC
            try:
                with open(pyproject_path, "rb") as f:
                    py_data = tomllib.load(f)
                raw_deps: List[str] = list(py_data.get("project", {}).get("dependencies", []))
                opt_deps = py_data.get("project", {}).get("optional-dependencies", {})
                if isinstance(opt_deps, dict):
                    for extra_list in opt_deps.values():
                        if isinstance(extra_list, list):
                            raw_deps.extend(str(x) for x in extra_list)
                poetry_deps = py_data.get("tool", {}).get("poetry", {}).get("dependencies", {})
                if isinstance(poetry_deps, dict):
                    raw_deps.extend(poetry_deps.keys())

                for spec in raw_deps:
                    m = _REQ_NAME_RE.match(spec.strip())
                    if m:
                        py_deps.add(m.group(1).lower().replace("_", "-"))
            except Exception:
                pass

        for req_file in ["requirements.txt", "Pipfile"]:
            req_path = os.path.join(dir_path, req_file)
            if os.path.isfile(req_path):
                if py_stack == ProjectStack.UNKNOWN:
                    py_stack = ProjectStack.PYTHON_GENERIC
                try:
                    with open(req_path, "r", encoding="utf-8") as f:
                        for raw_line in f:
                            line = raw_line.split("#")[0].strip()
                            if not line or line.startswith("-"):
                                continue
                            m = _REQ_NAME_RE.match(line)
                            if m:
                                py_deps.add(m.group(1).lower().replace("_", "-"))
                except Exception:
                    pass

        for dep_name in py_deps:
            if dep_name in PYTHON_TECH_MAP:
                technologies.add(PYTHON_TECH_MAP[dep_name])

        if "fastapi" in py_deps:
            py_stack = ProjectStack.FASTAPI
        elif "django" in py_deps:
            py_stack = ProjectStack.DJANGO
        elif "streamlit" in py_deps:
            py_stack = ProjectStack.STREAMLIT

        if node_stack not in (ProjectStack.UNKNOWN, ProjectStack.NODE_GENERIC):
            primary_stack = node_stack
        elif py_stack not in (ProjectStack.UNKNOWN, ProjectStack.PYTHON_GENERIC):
            primary_stack = py_stack
        elif node_stack != ProjectStack.UNKNOWN:
            primary_stack = node_stack
        else:
            primary_stack = py_stack

        return primary_stack, sorted(list(technologies))

    def _detect_architecture(
        self, dir_path: str
    ) -> Tuple[List[ArchitecturePattern], List[str]]:
        patterns: List[ArchitecturePattern] = []
        found_dirs: Set[str] = set()

        for root, dirs, _ in os.walk(dir_path):
            dirs[:] = [
                d for d in dirs if d not in SCAN_IGNORED_DIRS and not d.startswith(".")
            ]
            rel_root = os.path.relpath(root, dir_path).replace("\\", "/")

            for d in dirs:
                full_rel = d if rel_root == "." else f"{rel_root}/{d}"
                found_dirs.add(full_rel)

        dir_names = {os.path.basename(d).lower() for d in found_dirs}

        has_ports_adapters = ("ports" in dir_names and "adapters" in dir_names) or (
            "core" in dir_names and "infrastructure" in dir_names
        )
        if has_ports_adapters:
            patterns.append(ArchitecturePattern.HEXAGONAL)

        has_screaming = "modules" in dir_names or "features" in dir_names
        if has_screaming:
            patterns.append(ArchitecturePattern.SCREAMING)

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
                    with open(readme_path, "r", encoding="utf-8", errors="replace") as f:
                        raw_text = f.read(4096)
                    cleaned = _HTML_COMMENT_RE.sub("", raw_text)
                    lines = [line.strip() for line in cleaned.splitlines()[:12] if line.strip()]
                    summary = "\n".join(lines[:6])
                    return summary[:600] if summary else None
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
