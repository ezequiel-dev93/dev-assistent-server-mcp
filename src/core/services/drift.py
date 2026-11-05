from typing import List
from ..models import (
    AdrDriftItem,
    AdrDriftReport,
    AdrEntry,
    AdrStatus,
    ArchitectureAuditReport,
    ProjectRules,
    Severity,
)


def evaluate_adr_drift(
    project_name: str,
    adrs: List[AdrEntry],
    rules: ProjectRules,
    audit_report: ArchitectureAuditReport,
) -> AdrDriftReport:
    """
    Evaluates architectural drift between accepted ADRs and active rules/findings.
    """
    defined_rule_ids = {r.id for r in rules.layer_rules} | {r.id for r in rules.external_rules}
    if rules.cycle_rule and rules.cycle_rule.enabled:
        defined_rule_ids.add(rules.cycle_rule.id)

    items: List[AdrDriftItem] = []
    accepted_adrs = [a for a in adrs if a.status == AdrStatus.ACCEPTED]

    for adr in accepted_adrs:
        if not adr.enforced_by:
            items.append(
                AdrDriftItem(
                    adr_number=adr.number,
                    adr_title=adr.title,
                    status=adr.status.value,
                    issue_type="unbacked_adr",
                    severity=Severity.INFO,
                    details=(
                        f"ADR-{adr.number:04d} ('{adr.title}') is accepted but has no automated "
                        f"rules linked in `enforced_by`."
                    ),
                )
            )
            continue

        for rule_id in adr.enforced_by:
            if rule_id not in defined_rule_ids:
                items.append(
                    AdrDriftItem(
                        adr_number=adr.number,
                        adr_title=adr.title,
                        status=adr.status.value,
                        issue_type="missing_rule",
                        severity=Severity.WARNING,
                        details=(
                            f"ADR-{adr.number:04d} references rule '{rule_id}' in `enforced_by`, "
                            f"but '{rule_id}' is not defined in the active project rules."
                        ),
                    )
                )
                continue

            matching_violations = [
                v for v in audit_report.violations if v.rule_id == rule_id
            ]
            if matching_violations:
                items.append(
                    AdrDriftItem(
                        adr_number=adr.number,
                        adr_title=adr.title,
                        status=adr.status.value,
                        issue_type="violation",
                        severity=Severity.ERROR,
                        details=(
                            f"ADR-{adr.number:04d} ('{adr.title}') is violated by "
                            f"{len(matching_violations)} finding(s) under rule '{rule_id}'."
                        ),
                        violations=matching_violations,
                    )
                )

    return AdrDriftReport(
        project_name=project_name,
        adrs_checked=len(accepted_adrs),
        items=items,
    )
