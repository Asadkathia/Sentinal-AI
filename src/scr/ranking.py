from __future__ import annotations

from collections import defaultdict

from scr.models import Finding, SEVERITY_RANK, Severity


def dedupe_and_rank(findings: list[Finding], max_total: int, max_per_file: int) -> list[Finding]:
    by_id: dict[str, Finding] = {}
    for f in findings:
        existing = by_id.get(f.id)
        if existing is None or _score(f) > _score(existing):
            by_id[f.id] = f

    ordered = sorted(
        by_id.values(),
        key=lambda f: (
            -SEVERITY_RANK[f.severity],
            -f.confidence,
            f.file,
            f.location.start_line or 0,
            f.id,
        ),
    )

    per_file_count = defaultdict(int)
    final: list[Finding] = []
    for finding in ordered:
        if len(final) >= max_total:
            break
        if per_file_count[finding.file] >= max_per_file:
            continue
        final.append(finding)
        per_file_count[finding.file] += 1

    return final


def _score(finding: Finding) -> float:
    return SEVERITY_RANK[finding.severity] + finding.confidence


def exceeds_threshold(findings: list[Finding], threshold: str) -> bool:
    try:
        sev = threshold if isinstance(threshold, Severity) else Severity(str(threshold).upper())
    except ValueError:
        sev = Severity.HIGH
    threshold_rank = SEVERITY_RANK[sev]
    return any(SEVERITY_RANK[f.severity] >= threshold_rank for f in findings)
