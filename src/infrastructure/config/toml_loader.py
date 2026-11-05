from pathlib import Path
from typing import Any, Dict, List
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

from ...core.errors import ConfigError
from ...core.models import (
    CycleRule,
    ExternalRule,
    LayerRule,
    ProjectRules,
    RuleException,
    Severity,
)
from ...core.ports import IProjectConfigLoader

DEFAULT_FORBIDDEN_IN_DOMAIN = [
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
    "pydantic_settings",
    "mcp",
]

DEFAULT_FORBIDDEN_IN_UI = [
    "sqlite3",
    "sqlalchemy",
    "psycopg2",
    "pg",
    "prisma",
    "@prisma/client",
    "mongoose",
]


def build_preset_rules(preset_name: str) -> ProjectRules:
    preset = preset_name.lower().strip()

    if preset in ("hexagonal-python", "hexagonal", "clean-layered-python", "clean_layered"):
        return ProjectRules(
            version=1,
            preset=preset,
            layers={
                "domain": [
                    "src/core/**",
                    "src/**/core/**",
                    "core/**",
                    "src/domain/**",
                    "src/**/domain/**",
                    "domain/**",
                    "src/ports/**",
                    "ports/**",
                ],
                "application": [
                    "src/application/**",
                    "src/**/application/**",
                    "application/**",
                    "src/use_cases/**",
                    "src/tools/**",
                    "src/**/tools/**",
                ],
                "infrastructure": [
                    "src/infrastructure/**",
                    "src/**/infrastructure/**",
                    "infrastructure/**",
                    "src/adapters/**",
                    "src/**/adapters/**",
                    "adapters/**",
                ],
                "ui": [
                    "src/components/**",
                    "src/**/components/**",
                    "components/**",
                ],
            },
            layer_rules=[
                LayerRule(
                    id="domain-no-infra",
                    from_layer="domain",
                    disallow_layers=["infrastructure", "application", "ui"],
                    severity=Severity.ERROR,
                    description=(
                        "Hexagonal Architecture Violation: Core/Domain layer cannot depend on "
                        "infrastructure, adapters, or delivery layers. Inject via Ports instead."
                    ),
                )
            ],
            external_rules=[
                ExternalRule(
                    id="domain-no-frameworks",
                    from_layer="domain",
                    disallow_external=list(DEFAULT_FORBIDDEN_IN_DOMAIN),
                    severity=Severity.ERROR,
                ),
                ExternalRule(
                    id="ui-no-db",
                    from_layer="ui",
                    disallow_external=list(DEFAULT_FORBIDDEN_IN_UI),
                    severity=Severity.ERROR,
                    description=(
                        "Screaming/Clean UI Violation: UI Component directly imports persistence/DB "
                        "client. Delegate data access to a Service or Use Case."
                    ),
                ),
            ],
            cycle_rule=CycleRule(id="no-cycles", enabled=True, severity=Severity.WARNING),
        )

    if preset in ("screaming-ts", "screaming"):
        return ProjectRules(
            version=1,
            preset="screaming-ts",
            layers={
                "ui": [
                    "src/components/**",
                    "src/modules/**/components/**",
                    "src/features/**/components/**",
                    "components/**",
                ],
                "services": [
                    "src/services/**",
                    "src/modules/**/services/**",
                    "src/features/**/services/**",
                ],
                "domain": [
                    "src/core/**",
                    "src/domain/**",
                ],
            },
            layer_rules=[],
            external_rules=[
                ExternalRule(
                    id="ui-no-db",
                    from_layer="ui",
                    disallow_external=list(DEFAULT_FORBIDDEN_IN_UI),
                    severity=Severity.ERROR,
                    description=(
                        "Screaming/Clean UI Violation: UI Component directly imports persistence/DB "
                        "client. Delegate data access to a Service or Use Case."
                    ),
                ),
                ExternalRule(
                    id="domain-no-frameworks",
                    from_layer="domain",
                    disallow_external=list(DEFAULT_FORBIDDEN_IN_DOMAIN),
                    severity=Severity.ERROR,
                ),
            ],
            cycle_rule=CycleRule(id="no-cycles", enabled=True, severity=Severity.WARNING),
        )

    if preset == "django":
        return ProjectRules(
            version=1,
            preset="django",
            layers={
                "models": ["**/models.py", "**/models/**"],
                "views": ["**/views.py", "**/views/**"],
            },
            layer_rules=[
                LayerRule(
                    id="models-no-views",
                    from_layer="models",
                    disallow_layers=["views"],
                    severity=Severity.ERROR,
                    description="Django Architecture Violation: Models must not import Views.",
                )
            ],
            external_rules=[],
            cycle_rule=CycleRule(id="no-cycles", enabled=True, severity=Severity.WARNING),
        )

    return build_preset_rules("hexagonal-python")


def _validate_glob_patterns(layers: Dict[str, List[str]]) -> None:
    for layer_name, globs in layers.items():
        if not isinstance(globs, list):
            raise ConfigError(f"Layer '{layer_name}' must map to a list of glob strings.")
        for pat in globs:
            norm = pat.replace("\\", "/")
            if norm.startswith("/") or ".." in norm.split("/"):
                raise ConfigError(
                    f"Invalid glob pattern '{pat}' in layer '{layer_name}': "
                    f"patterns must be relative and cannot contain '..'"
                )


class TomlProjectConfigLoader(IProjectConfigLoader):
    """Loads project rules from devassistant.toml (priority) or [tool.devassistant] in pyproject.toml."""

    def load(
        self, project_root: Path, detected_patterns: List[str], stack: str
    ) -> ProjectRules:
        dev_toml = project_root / "devassistant.toml"
        pyproject_toml = project_root / "pyproject.toml"

        raw_cfg: Dict[str, Any] | None = None
        if dev_toml.is_file():
            try:
                raw_cfg = tomllib.loads(dev_toml.read_text(encoding="utf-8"))
            except Exception as exc:
                raise ConfigError(f"Invalid TOML in {dev_toml}: {exc}") from exc
        elif pyproject_toml.is_file():
            try:
                py_data = tomllib.loads(pyproject_toml.read_text(encoding="utf-8"))
                tool_cfg = py_data.get("tool", {}).get("devassistant")
                if isinstance(tool_cfg, dict):
                    raw_cfg = tool_cfg
            except Exception:
                raw_cfg = None

        auto_preset = "hexagonal-python"
        if "screaming" in detected_patterns and "hexagonal" not in detected_patterns:
            auto_preset = "screaming-ts"
        elif stack == "django":
            auto_preset = "django"

        if not raw_cfg:
            return build_preset_rules(auto_preset)

        preset_name = str(raw_cfg.get("preset", auto_preset))
        base_rules = build_preset_rules(preset_name)
        base_rules.preset = preset_name

        if "layers" in raw_cfg and isinstance(raw_cfg["layers"], dict):
            _validate_glob_patterns(raw_cfg["layers"])
            base_rules.layers = {
                str(k): [str(x) for x in v] for k, v in raw_cfg["layers"].items()
            }

        if "rules" in raw_cfg and isinstance(raw_cfg["rules"], list):
            layer_rules: List[LayerRule] = []
            external_rules: List[ExternalRule] = []
            cycle_rule = base_rules.cycle_rule

            for item in raw_cfg["rules"]:
                if not isinstance(item, dict):
                    continue
                r_id = str(item.get("id", "custom-rule"))
                sev_str = str(item.get("severity", "ERROR")).upper()
                try:
                    sev = Severity(sev_str)
                except ValueError:
                    raise ConfigError(f"Invalid severity '{sev_str}' in rule '{r_id}'")

                if item.get("kind") == "cycles" or r_id == "no-cycles":
                    cycle_rule = CycleRule(
                        id=r_id,
                        enabled=bool(item.get("enabled", True)),
                        severity=sev,
                    )
                    continue

                from_layer = str(item.get("from", item.get("from_layer", "")))
                if "disallow_layers" in item:
                    layer_rules.append(
                        LayerRule(
                            id=r_id,
                            from_layer=from_layer,
                            disallow_layers=[str(x) for x in item["disallow_layers"]],
                            severity=sev,
                            description=item.get("description"),
                        )
                    )
                if "disallow_external" in item or "allow_external" in item:
                    external_rules.append(
                        ExternalRule(
                            id=r_id,
                            from_layer=from_layer,
                            disallow_external=[str(x) for x in item.get("disallow_external", [])],
                            allow_external=[str(x) for x in item.get("allow_external", [])],
                            severity=sev,
                            description=item.get("description"),
                        )
                    )

            base_rules.layer_rules = layer_rules
            base_rules.external_rules = external_rules
            base_rules.cycle_rule = cycle_rule

        if "exceptions" in raw_cfg and isinstance(raw_cfg["exceptions"], list):
            excs: List[RuleException] = []
            for exc_item in raw_cfg["exceptions"]:
                if isinstance(exc_item, dict):
                    excs.append(
                        RuleException(
                            rule=str(exc_item.get("rule", "")),
                            files=[str(f) for f in exc_item.get("files", [])],
                            reason=str(exc_item.get("reason", "")),
                            expires=exc_item.get("expires"),
                        )
                    )
            base_rules.exceptions = excs

        return base_rules
