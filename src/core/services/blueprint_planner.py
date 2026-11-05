import re
from typing import List
from ..models import (
    ArchitecturePattern,
    BlueprintFileItem,
    BlueprintPlan,
    ProjectStack,
)


def plan_feature_blueprint(
    project_name: str,
    feature_name: str,
    stack: ProjectStack,
    architectures: List[ArchitecturePattern],
    technologies: List[str],
) -> BlueprintPlan:
    """Generates a deterministic, architecture-compliant file plan for a new feature."""
    slug = re.sub(r"[^a-z0-9_]+", "_", feature_name.strip().lower().replace("-", "_")).strip("_") or "feature"
    pascal = "".join(part.capitalize() for part in slug.split("_"))

    has_hexagonal = ArchitecturePattern.HEXAGONAL in architectures
    has_screaming = ArchitecturePattern.SCREAMING in architectures
    files: List[BlueprintFileItem] = []

    if has_hexagonal:
        files.extend(
            [
                BlueprintFileItem(
                    relative_path=f"src/core/{slug}/domain/{slug}.py",
                    description="Entidades de negocio puras",
                    layer="domain",
                    template_content=(
                        f"from dataclasses import dataclass\n\n\n"
                        f"@dataclass(frozen=True)\n"
                        f"class {pascal}Entity:\n"
                        f"    id: str\n"
                    ),
                ),
                BlueprintFileItem(
                    relative_path=f"src/core/{slug}/ports/{slug}_repository.py",
                    description=f"Interfaces (I{pascal}Repository)",
                    layer="ports",
                    template_content=(
                        f"from abc import ABC, abstractmethod\n"
                        f"from typing import Optional\n"
                        f"from src.core.{slug}.domain.{slug} import {pascal}Entity\n\n\n"
                        f"class I{pascal}Repository(ABC):\n"
                        f"    @abstractmethod\n"
                        f"    def get_by_id(self, entity_id: str) -> Optional[{pascal}Entity]:\n"
                        f"        pass\n"
                    ),
                ),
                BlueprintFileItem(
                    relative_path=f"src/core/{slug}/use_cases/get_{slug}.py",
                    description="Casos de uso de la aplicación",
                    layer="application",
                    template_content=(
                        f"from typing import Optional\n"
                        f"from src.core.{slug}.domain.{slug} import {pascal}Entity\n"
                        f"from src.core.{slug}.ports.{slug}_repository import I{pascal}Repository\n\n\n"
                        f"class Get{pascal}UseCase:\n"
                        f"    def __init__(self, repository: I{pascal}Repository) -> None:\n"
                        f"        self.repository = repository\n\n"
                        f"    def execute(self, entity_id: str) -> Optional[{pascal}Entity]:\n"
                        f"        return self.repository.get_by_id(entity_id)\n"
                    ),
                ),
                BlueprintFileItem(
                    relative_path=f"src/infrastructure/adapters/{slug}/sqlite_{slug}_repository.py",
                    description="Adaptador concreto de persistencia",
                    layer="infrastructure",
                    template_content=(
                        f"from typing import Optional\n"
                        f"from src.core.{slug}.domain.{slug} import {pascal}Entity\n"
                        f"from src.core.{slug}.ports.{slug}_repository import I{pascal}Repository\n\n\n"
                        f"class Sqlite{pascal}Repository(I{pascal}Repository):\n"
                        f"    def get_by_id(self, entity_id: str) -> Optional[{pascal}Entity]:\n"
                        f"        return None\n"
                    ),
                ),
            ]
        )
        if stack == ProjectStack.FASTAPI or "fastapi" in technologies:
            files.append(
                BlueprintFileItem(
                    relative_path=f"src/api/routers/{slug}.py",
                    description="Endpoint FastAPI desacoplado",
                    layer="entrypoint",
                    template_content=(
                        f"from fastapi import APIRouter\n\n"
                        f"router = APIRouter(prefix='/{slug}', tags=['{slug}'])\n"
                    ),
                )
            )
    elif has_screaming:
        ext = "astro" if stack == ProjectStack.ASTRO else "tsx"
        files.extend(
            [
                BlueprintFileItem(
                    relative_path=f"src/modules/{slug}/components/{pascal}Card.{ext}",
                    description="Componentes UI de la feature",
                    layer="ui",
                    template_content=f"<!-- {pascal}Card component -->\n" if ext == "astro" else f"export function {pascal}Card() {{\n  return null;\n}}\n",
                ),
                BlueprintFileItem(
                    relative_path=f"src/modules/{slug}/services/{slug}.service.ts",
                    description="Llamadas a API o servicios de dominio",
                    layer="services",
                    template_content=f"export async function fetch{pascal}() {{\n  return [];\n}}\n",
                ),
                BlueprintFileItem(
                    relative_path=f"src/modules/{slug}/types/{slug}.types.ts",
                    description="Tipos TypeScript específicos",
                    layer="types",
                    template_content=f"export interface {pascal}Item {{\n  id: string;\n}}\n",
                ),
                BlueprintFileItem(
                    relative_path=f"src/modules/{slug}/index.ts",
                    description="Exportaciones públicas del módulo",
                    layer="module_index",
                    template_content=f"export * from './types/{slug}.types';\nexport * from './services/{slug}.service';\n",
                ),
            ]
        )
    else:
        files.extend(
            [
                BlueprintFileItem(
                    relative_path=f"src/{slug}/__init__.py",
                    description="Inicializador del módulo",
                    layer="module",
                    template_content="",
                ),
                BlueprintFileItem(
                    relative_path=f"src/{slug}/service.py",
                    description="Lógica del servicio",
                    layer="service",
                    template_content=f"class {pascal}Service:\n    pass\n",
                ),
            ]
        )

    return BlueprintPlan(
        project_name=project_name,
        feature_name=feature_name,
        slug=slug,
        detected_architectures=architectures,
        files=files,
        dry_run=True,
    )
