from __future__ import annotations

import json
from collections import Counter

from scr.models import Report


def render_markdown(report: Report) -> str:
    meta = report.metadata
    lines = [
        "# Smart Code Reviewer Report",
        "",
        "## Run Metadata",
        f"- Input mode: `{meta.input_mode}`",
        f"- Base ref: `{meta.base_ref or 'n/a'}`",
        f"- LLM used: `{meta.llm_used}`",
        f"- Timestamp: `{meta.timestamp}`",
        f"- Repo root: `{meta.repo_root}`",
        "- Tools:",
    ]
    if meta.tools:
        for t in meta.tools:
            lines.append(f"  - `{t.name}`: {t.status} ({t.summary})")
    else:
        lines.append("  - not run")

    severity_counts = Counter(f.severity.value for f in report.findings)
    lines.extend([
        "",
        "## Summary",
        f"- Findings: **{len(report.findings)}**",
        f"- By severity: `{dict(sorted(severity_counts.items()))}`",
        "",
        "## Findings",
    ])

    if not report.findings:
        lines.append("No findings.")
        return "\n".join(lines)

    for idx, f in enumerate(report.findings, start=1):
        loc = f"{f.location.start_line or '?'}-{f.location.end_line or f.location.start_line or '?'}"
        lines.extend(
            [
                f"### {idx}. {f.title}",
                f"- Severity: `{f.severity.value}`",
                f"- Confidence: `{f.confidence:.2f}`",
                f"- Category: `{f.category.value}`",
                f"- File: `{f.file}`",
                f"- Location: `{loc}`",
                f"- Symbol: `{f.location.symbol or 'n/a'}`",
                f"- Source: `{f.source.analyzer}:{f.source.rule}`",
                f"- Why it matters: {f.message}",
                "- Recommendation steps:",
            ]
        )
        if f.recommendation:
            lines.extend([f"  - {step}" for step in f.recommendation])
        else:
            lines.append("  - None")

        lines.append("- Suggested tests:")
        if f.suggested_tests:
            lines.extend([f"  - {test}" for test in f.suggested_tests])
        else:
            lines.append("  - None")

        if f.context:
            lines.extend(["- Context:", "```", f.context, "```"])
        if f.suggested_patch:
            lines.extend(["- Suggested patch:", "```diff", f.suggested_patch, "```"])
        lines.append("")

    return "\n".join(lines)


def render_json(report: Report) -> str:
    return json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True)
