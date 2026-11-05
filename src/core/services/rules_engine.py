from dataclasses import dataclass
from datetime import date
from fnmatch import fnmatch
from typing import Dict, List, Optional, Set
from ..models import (
    ArchitectureViolation,
    ImportRef,
    ProjectRules,
    RuleException,
    Severity,
)
from .cycles import find_cycles


@dataclass(frozen=True)
class ResolvedImportEdge:
    source_file: str
    import_ref: ImportRef
    target_file: Optional[str]
    external_package: Optional[str]


def _glob_matches(rel_path: str, pattern: str) -> bool:
    norm_path = rel_path.replace("\\", "/").strip("/")
    norm_pat = pattern.replace("\\", "/").strip("/")
    if norm_pat.endswith("/**"):
        prefix = norm_pat[:-3].strip("/")
        if norm_path == prefix or norm_path.startswith(prefix + "/"):
            return True
    if "**/" in norm_pat:
        # Handle mid-path ** cleanly across Python versions
        parts = norm_pat.split("**/")
        if len(parts) == 2:
            head, tail = parts[0].strip("/"), parts[1].strip("/")
            if not head or norm_path.startswith(head + "/") or norm_path == head:
                sub = norm_path[len(head) :].strip("/") if head else norm_path
                sub_parts = sub.split("/")
                for idx in range(len(sub_parts)):
                    candidate = "/".join(sub_parts[idx:])
                    if _glob_matches(candidate, tail):
                        return True
    return fnmatch(norm_path, norm_pat)


def classify_layer(rel_path: str, layers: Dict[str, List[str]]) -> Optional[str]:
    """Returns the layer name matching rel_path, or None if unclassified."""
    norm = rel_path.replace("\\", "/")
    for layer_name, patterns in layers.items():
        for pat in patterns:
            if _glob_matches(norm, pat):
                return layer_name
    return None


def extract_top_level_package(module_str: str) -> str:
    """Extracts the exact top-level package name from a Python or JS/TS import specifier."""
    cleaned = module_str.strip()
    if cleaned.startswith("@"):
        parts = cleaned.split("/")
        return "/".join(parts[:2]) if len(parts) >= 2 else cleaned
    return cleaned.split(".")[0].split("/")[0]


def _downgrade_for_type_only(severity: Severity, type_only: bool) -> Severity:
    if not type_only:
        return severity
    if severity == Severity.ERROR:
        return Severity.WARNING
    return Severity.INFO


def _find_matching_exception(
    rule_id: str, rel_file: str, exceptions: List[RuleException]
) -> Optional[RuleException]:
    for exc in exceptions:
        if exc.rule != rule_id:
            continue
        if any(_glob_matches(rel_file, pat) for pat in exc.files):
            return exc
    return None


def _is_expired(expires_str: Optional[str], today_iso: str) -> bool:
    if not expires_str:
        return False
    try:
        exp_date = date.fromisoformat(expires_str.strip())
        cur_date = date.fromisoformat(today_iso.strip())
        return cur_date > exp_date
    except ValueError:
        return True


def evaluate_project_rules(
    edges: List[ResolvedImportEdge],
    rules: ProjectRules,
    today_iso: Optional[str] = None,
) -> List[ArchitectureViolation]:
    """Pure rules engine evaluating layer boundaries, external dependencies, cycles, and exceptions."""
    current_date = today_iso or date.today().isoformat()
    violations: List[ArchitectureViolation] = []
    dep_graph: Dict[str, Set[str]] = {}
    seen_keys: Set[tuple] = set()

    for edge in edges:
        src_layer = classify_layer(edge.source_file, rules.layers)

        if edge.target_file:
            if edge.target_file != edge.source_file:
                dep_graph.setdefault(edge.source_file, set()).add(edge.target_file)
            dst_layer = classify_layer(edge.target_file, rules.layers)

            if src_layer and dst_layer and src_layer != dst_layer:
                for l_rule in rules.layer_rules:
                    if l_rule.from_layer == src_layer and dst_layer in l_rule.disallow_layers:
                        dedup_key = (l_rule.id, edge.source_file, edge.import_ref.line)
                        if dedup_key in seen_keys:
                            continue
                        seen_keys.add(dedup_key)

                        matched_exc = _find_matching_exception(
                            l_rule.id, edge.source_file, rules.exceptions
                        )
                        if matched_exc:
                            if _is_expired(matched_exc.expires, current_date):
                                violations.append(
                                    ArchitectureViolation(
                                        rule_id=l_rule.id,
                                        file_path=edge.source_file,
                                        line_number=edge.import_ref.line,
                                        offending_statement=edge.import_ref.statement,
                                        rule_broken=(
                                            f"Expired exception ({matched_exc.expires}) for rule '{l_rule.id}': "
                                            f"Layer '{src_layer}' cannot import from layer '{dst_layer}' "
                                            f"('{edge.target_file}'). Reason: {matched_exc.reason}"
                                        ),
                                        severity=Severity.ERROR,
                                    )
                                )
                            continue

                        eff_sev = _downgrade_for_type_only(
                            l_rule.severity, edge.import_ref.type_only
                        )
                        desc = l_rule.description or (
                            f"Hexagonal Architecture Violation [{l_rule.id}]: Core/Domain layer '{src_layer}' "
                            f"cannot depend on '{dst_layer}' module '{edge.import_ref.module}' ('{edge.target_file}'). "
                            f"Inject via Ports instead."
                        )
                        violations.append(
                            ArchitectureViolation(
                                rule_id=l_rule.id,
                                file_path=edge.source_file,
                                line_number=edge.import_ref.line,
                                offending_statement=edge.import_ref.statement,
                                rule_broken=desc,
                                severity=eff_sev,
                            )
                        )

        elif edge.external_package and src_layer:
            top_pkg = extract_top_level_package(edge.external_package).lower()
            full_ext = edge.external_package.lower()

            for e_rule in rules.external_rules:
                if e_rule.from_layer != src_layer:
                    continue

                disallow_set = {p.lower() for p in e_rule.disallow_external}
                allow_set = {p.lower() for p in e_rule.allow_external}

                is_forbidden = False
                if allow_set:
                    if top_pkg not in allow_set and full_ext not in allow_set:
                        is_forbidden = True
                if top_pkg in disallow_set or full_ext in disallow_set:
                    is_forbidden = True

                if not is_forbidden:
                    continue

                dedup_key = (e_rule.id, edge.source_file, edge.import_ref.line)
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)

                matched_exc = _find_matching_exception(
                    e_rule.id, edge.source_file, rules.exceptions
                )
                if matched_exc:
                    if _is_expired(matched_exc.expires, current_date):
                        violations.append(
                            ArchitectureViolation(
                                rule_id=e_rule.id,
                                file_path=edge.source_file,
                                line_number=edge.import_ref.line,
                                offending_statement=edge.import_ref.statement,
                                rule_broken=(
                                    f"Expired exception ({matched_exc.expires}) for rule '{e_rule.id}': "
                                    f"Layer '{src_layer}' cannot import external package '{edge.external_package}'."
                                ),
                                severity=Severity.ERROR,
                            )
                        )
                    continue

                eff_sev = _downgrade_for_type_only(
                    e_rule.severity, edge.import_ref.type_only
                )
                desc = e_rule.description or (
                    f"Hexagonal Architecture Violation [{e_rule.id}]: Core/Domain layer '{src_layer}' "
                    f"cannot depend on external framework or infrastructure module '{edge.external_package}'. "
                    f"Inject via Ports instead."
                )
                violations.append(
                    ArchitectureViolation(
                        rule_id=e_rule.id,
                        file_path=edge.source_file,
                        line_number=edge.import_ref.line,
                        offending_statement=edge.import_ref.statement,
                        rule_broken=desc,
                        severity=eff_sev,
                    )
                )

    if rules.cycle_rule and rules.cycle_rule.enabled:
        detected_cycles = find_cycles(dep_graph)
        for cyc in detected_cycles:
            first_file = cyc[0]
            matched_exc = _find_matching_exception(
                rules.cycle_rule.id, first_file, rules.exceptions
            )
            if matched_exc and not _is_expired(matched_exc.expires, current_date):
                continue

            cycle_str = " -> ".join(cyc)
            violations.append(
                ArchitectureViolation(
                    rule_id=rules.cycle_rule.id,
                    file_path=first_file,
                    line_number=1,
                    offending_statement=f"circular dependency: {cycle_str}",
                    rule_broken=f"Circular dependency detected [{rules.cycle_rule.id}]: {cycle_str}",
                    severity=rules.cycle_rule.severity,
                )
            )

    return violations
