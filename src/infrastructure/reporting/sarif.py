import json
from typing import Dict, List
from ... import __version__
from ...core.models import ArchitectureAuditReport, ProjectRules, Severity

_SARIF_LEVEL_MAP = {
    Severity.ERROR: "error",
    Severity.WARNING: "warning",
    Severity.INFO: "note",
}


def format_audit_sarif(
    report: ArchitectureAuditReport, rules: ProjectRules | None = None
) -> str:
    """Formats an ArchitectureAuditReport as a valid SARIF 2.1.0 JSON string for GitHub Code Scanning / CI."""
    rule_defs: Dict[str, Dict[str, object]] = {}

    if rules:
        for lr in rules.layer_rules:
            rule_defs[lr.id] = {
                "id": lr.id,
                "shortDescription": {
                    "text": lr.description
                    or f"Layer '{lr.from_layer}' must not depend on {lr.disallow_layers}"
                },
                "defaultConfiguration": {"level": _SARIF_LEVEL_MAP[lr.severity]},
            }
        for er in rules.external_rules:
            rule_defs[er.id] = {
                "id": er.id,
                "shortDescription": {
                    "text": er.description
                    or f"Layer '{er.from_layer}' external package restriction"
                },
                "defaultConfiguration": {"level": _SARIF_LEVEL_MAP[er.severity]},
            }
        if rules.cycle_rule and rules.cycle_rule.enabled:
            cid = rules.cycle_rule.id
            rule_defs[cid] = {
                "id": cid,
                "shortDescription": {"text": "No circular dependencies between internal modules"},
                "defaultConfiguration": {"level": _SARIF_LEVEL_MAP[rules.cycle_rule.severity]},
            }

    results: List[Dict[str, object]] = []
    for v in report.violations:
        if v.rule_id not in rule_defs:
            rule_defs[v.rule_id] = {
                "id": v.rule_id,
                "shortDescription": {"text": v.rule_broken},
                "defaultConfiguration": {"level": _SARIF_LEVEL_MAP[v.severity]},
            }
        results.append(
            {
                "ruleId": v.rule_id,
                "level": _SARIF_LEVEL_MAP[v.severity],
                "message": {"text": f"{v.rule_broken} (statement: `{v.offending_statement}`)"},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": v.file_path.replace("\\", "/"),
                                "uriBaseId": "%SRCROOT%",
                            },
                            "region": {
                                "startLine": max(1, v.line_number),
                            },
                        }
                    }
                ],
            }
        )

    sarif_doc = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "DevAssistant-MCP",
                        "version": __version__,
                        "informationUri": "https://www.agensi.io/r/EZEQUIELSUAREZ",
                        "rules": list(rule_defs.values()),
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(sarif_doc, indent=2, ensure_ascii=False)
