import os
from typing import Optional
from src.core.ports import IProjectScanner


class ProjectTools:
    """Herramientas de inspección y auditoría de proyectos para exponer mediante el protocolo MCP."""

    def __init__(self, scanner: IProjectScanner, default_workspace: str = "../"):
        self.scanner = scanner
        self.default_workspace = default_workspace

    def _resolve_target_path(self, project_path_or_name: str) -> Optional[str]:
        target = project_path_or_name
        if os.path.exists(target):
            return os.path.abspath(target)
        candidate = os.path.join(self.default_workspace, project_path_or_name)
        if os.path.exists(candidate):
            return os.path.abspath(candidate)
        return None

    def list_projects(self, workspace_path: Optional[str] = None) -> str:
        """Escanea y lista todos los proyectos detectados en el espacio de trabajo."""
        target_path = workspace_path or self.default_workspace
        if not os.path.isabs(target_path):
            target_path = os.path.abspath(target_path)

        projects = self.scanner.scan_workspace(target_path)
        if not projects:
            return f"No se detectaron proyectos válidos en: {target_path}"

        lines = [f"📁 Proyectos encontrados en `{target_path}` ({len(projects)}):", ""]
        for p in projects:
            arch_str = ", ".join(a.value for a in p.detected_architectures)
            tech_str = ", ".join(p.technologies[:5]) if p.technologies else "n/a"
            tests_badge = "✅ Tests" if p.has_tests else "❌ Sin tests"
            docker_badge = "🐳 Docker" if p.has_docker else ""

            lines.append(f"### 📦 `{p.name}`")
            lines.append(f"- **Stack:** {p.stack.value}")
            lines.append(f"- **Arquitectura:** {arch_str}")
            lines.append(f"- **Tecnologías:** {tech_str}")
            lines.append(f"- **Infraestructura:** {tests_badge} {docker_badge}".strip())
            lines.append(f"- **Ruta:** `{p.path}`")
            lines.append("")

        return "\n".join(lines)

    def inspect_project(self, project_path_or_name: str) -> str:
        """Inspecciona en profundidad un proyecto específico, detallando sus patrones arquitectónicos y estructura."""
        target = self._resolve_target_path(project_path_or_name)
        if not target:
            return f"Error: No se encontró el proyecto o directorio '{project_path_or_name}'."

        detail = self.scanner.inspect_project(target)
        lines = [
            f"# 🔍 Análisis Arquitectónico: `{detail.name}`",
            "",
            f"- **Ruta:** `{detail.path}`",
            f"- **Stack Principal:** `{detail.stack.value}`",
            f"- **Patrones Detectados:** {', '.join(a.value for a in detail.detected_architectures)}",
            f"- **Tecnologías Clave:** {', '.join(detail.technologies) if detail.technologies else 'Ninguna detectada'}",
            "",
            "## 📂 Carpetas Estructurales Relevantes:",
        ]

        if detail.key_directories:
            for d in detail.key_directories:
                lines.append(f"- `{d}`")
        else:
            lines.append("- No se detectaron carpetas estándar.")

        lines.append("")
        lines.append("## 📐 Directrices de Arquitectura para el Asistente:")
        if detail.architecture_guidelines:
            for g in detail.architecture_guidelines:
                lines.append(f"- ⚠️ {g}")
        else:
            lines.append("- Mantener estructura limpia y modular.")

        if detail.summary_description:
            lines.append("")
            lines.append("## 📄 Resumen del README:")
            lines.append(detail.summary_description)

        return "\n".join(lines)

    def audit_project_architecture(self, project_path_or_name: str) -> str:
        """Audita un proyecto en busca de violaciones a la Arquitectura Hexagonal o Screaming Architecture."""
        target = self._resolve_target_path(project_path_or_name)
        if not target:
            return f"Error: No se encontró el proyecto o directorio '{project_path_or_name}'."

        report = self.scanner.audit_architecture(target)
        arch_str = ", ".join(a.value for a in report.detected_architectures)
        status_badge = (
            "✅ 100% COMPLIANT (Sin violaciones detectadas)"
            if report.is_compliant
            else f"❌ {len(report.violations)} VIOLACIONES DETECTADAS"
        )

        lines = [
            f"# 🛡️ Auditoría de Límites Arquitectónicos: `{report.project_name}`",
            "",
            f"- **Estado:** {status_badge}",
            f"- **Patrones Auditados:** `{arch_str}`",
            f"- **Archivos Escaneados:** {report.files_scanned}",
            "",
        ]

        if report.is_compliant:
            lines.append(
                "🎉 **Excelente:** Ningún archivo de `core/domain/ports` ni componentes UI "
                "importa dependencias prohibidas de infraestructura o base de datos."
            )
        else:
            lines.append("## 🚨 Detalle de Violaciones Encontradas:")
            for idx, v in enumerate(report.violations, start=1):
                lines.append(
                    f"{idx}. **`{v.file_path}` (Línea {v.line_number})** — `[{v.severity}]`\n"
                    f"   - **Sentencia:** `{v.offending_statement}`\n"
                    f"   - **Regla vulnerada:** {v.rule_broken}"
                )

        return "\n".join(lines)

    def scaffold_feature_blueprint(
        self, project_path_or_name: str, feature_name: str
    ) -> str:
        """Genera el plano (blueprint) exacto de archivos y carpetas para crear una nueva feature siguiendo las reglas del proyecto."""
        target = self._resolve_target_path(project_path_or_name)
        if not target:
            return f"Error: No se encontró el proyecto '{project_path_or_name}'."

        detail = self.scanner.inspect_project(target)
        slug = feature_name.lower().replace(" ", "_").replace("-", "_")

        lines = [
            f"# 🏗️ Blueprint para Feature: `{feature_name}` en `{detail.name}`",
            "",
            f"Basado en los patrones detectados: **{', '.join(a.value for a in detail.detected_architectures)}**",
            "",
            "### 📁 Estructura de archivos sugerida:",
            "```text",
        ]

        has_hexagonal = any("hexagonal" in a.value for a in detail.detected_architectures)
        has_screaming = any("screaming" in a.value for a in detail.detected_architectures)

        if has_hexagonal:
            lines.extend(
                [
                    f"src/core/{slug}/",
                    f"├── domain/                  # Entidades de negocio puras",
                    f"│   └── {slug}.py",
                    f"├── ports/                   # Interfaces (I{feature_name.capitalize()}Repository)",
                    f"│   └── {slug}_repository.py",
                    f"└── use_cases/               # Casos de uso de la aplicación",
                    f"    └── get_{slug}.py",
                    f"src/infrastructure/adapters/{slug}/",
                    f"└── postgres_{slug}_repository.py",
                    f"src/api/routers/{slug}.py     # Endpoint FastAPI desacoplado",
                ]
            )
        elif has_screaming:
            lines.extend(
                [
                    f"src/modules/{slug}/",
                    f"├── components/              # Componentes UI de la feature",
                    f"│   └── {feature_name.capitalize()}Card.astro (o .tsx)",
                    f"├── services/                # Llamadas a API o Supabase",
                    f"│   └── {slug}.service.ts",
                    f"├── types/                   # Tipos TypeScript específicos",
                    f"│   └── {slug}.types.ts",
                    f"└── index.ts                 # Exportaciones públicas del módulo",
                ]
            )
        else:
            lines.extend(
                [
                    f"src/{slug}/",
                    f"├── components/",
                    f"├── services/",
                    f"└── types.ts",
                ]
            )

        lines.extend(
            [
                "```",
                "",
                "### 💡 Regla de Oro:",
                "- No mezclar acceso a base de datos con componentes visuales o routers.",
                "- Todo tipado debe ser estricto.",
            ]
        )

        return "\n".join(lines)
