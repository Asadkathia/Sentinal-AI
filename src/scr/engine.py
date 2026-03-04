from __future__ import annotations

import json
from pathlib import Path

from scr.analyzers.llm import run_llm_analyzer
from scr.analyzers.static import run_static_analyzer
from scr.analyzers.tool_runner import run_tool_analyzer
from scr.config import llm_enabled, load_config
from scr.context import build_context_map
from scr.inputs import collect_changes_from_git, collect_changes_from_paths, collect_changes_from_unified_diff
from scr.models import Report, ReportMetadata, ReviewRequest, ReviewSummary, SEVERITY_RANK, Severity, now_iso
from scr.ranking import dedupe_and_rank


class EngineError(Exception):
    pass


def run_review(request: ReviewRequest, cwd: str | None = None) -> tuple[Report, ReviewSummary]:
    try:
        config = load_config(cwd)
        max_total = request.max_findings or int(config.get("max_findings_total", 12))
        max_per_file = request.max_per_file or int(config.get("max_findings_per_file", 3))

        changes = _collect_changes(request)
        context_map = build_context_map(changes)

        findings = run_static_analyzer(changes, context_map, config)
        tool_findings, tool_results = run_tool_analyzer(config)
        findings.extend(tool_findings)

        use_llm = llm_enabled(config, request.no_llm)
        if use_llm:
            llm_findings = run_llm_analyzer(changes, context_map, config, max_total)
            findings.extend(llm_findings)

        ranked = dedupe_and_rank(findings, max_total=max_total, max_per_file=max_per_file)
        ranked = _attach_missing_context(ranked, context_map)

        report = Report(
            metadata=ReportMetadata(
                timestamp=now_iso(),
                repo_root=str(Path.cwd()),
                input_mode=changes.mode,
                base_ref=changes.base_ref,
                llm_used=use_llm,
                tools=tool_results,
                config={
                    "fail_on": request.fail_on.value,
                    "max_findings_total": max_total,
                    "max_findings_per_file": max_per_file,
                },
            ),
            findings=ranked,
        )

        summary = _build_summary(report, request.fail_on.value)
        return report, summary
    except Exception as exc:  # noqa: BLE001
        raise EngineError(str(exc)) from exc


def _collect_changes(request: ReviewRequest):
    if request.mode == "git":
        return collect_changes_from_git(request.base)
    if request.mode == "diff":
        if request.diff_text is not None and "\n" in request.diff_text:
            return collect_changes_from_unified_diff(diff_text=request.diff_text)
        return collect_changes_from_unified_diff(diff_path=request.diff_text)
    if request.mode == "paths":
        return collect_changes_from_paths(request.paths or [])
    raise EngineError(f"Unsupported mode: {request.mode}")


def _build_summary(report: Report, threshold: str) -> ReviewSummary:
    counts: dict[str, int] = {}
    for finding in report.findings:
        sev = finding.severity.value
        counts[sev] = counts.get(sev, 0) + 1

    try:
        sev = threshold if isinstance(threshold, Severity) else Severity(str(threshold).upper())
    except ValueError:
        sev = Severity.HIGH
    threshold_rank = SEVERITY_RANK[sev]
    threshold_exceeded = any(SEVERITY_RANK[f.severity] >= threshold_rank for f in report.findings)

    return ReviewSummary(
        total_findings=len(report.findings),
        by_severity=dict(sorted(counts.items())),
        threshold_exceeded=threshold_exceeded,
        llm_used=report.metadata.llm_used,
    )


def dump_report_json(report: Report) -> dict:
    return json.loads(report.model_dump_json())


def _attach_missing_context(findings, context_map: dict):
    for finding in findings:
        if finding.context:
            continue
        file_data = context_map.get(finding.file)
        if not file_data:
            continue
        hunks = file_data.get("hunks", [])
        if hunks:
            finding.context = str(hunks[0])[:2000]
    return findings
