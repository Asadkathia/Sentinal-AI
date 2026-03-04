from scr.models import Category, Finding, Location, Report, ReportMetadata, Severity, SourceInfo
from scr.renderers import render_json, render_markdown


def test_renderers_include_metadata_and_findings():
    report = Report(
        metadata=ReportMetadata(
            timestamp="2026-01-01T00:00:00+00:00",
            repo_root="/tmp/repo",
            input_mode="diff",
            base_ref=None,
            llm_used=False,
            tools=[],
            config={"fail_on": "HIGH"},
        ),
        findings=[
            Finding(
                title="Issue",
                severity=Severity.HIGH,
                confidence=0.9,
                category=Category.correctness,
                file="a.py",
                location=Location(start_line=2, end_line=2),
                message="bad",
                recommendation=["fix it"],
                suggested_tests=["add test"],
                source=SourceInfo(analyzer="static", rule="rule1"),
            )
        ],
    )

    md = render_markdown(report)
    js = render_json(report)

    assert "Smart Code Reviewer Report" in md
    assert "Input mode: `diff`" in md
    assert '"input_mode": "diff"' in js
    assert '"title": "Issue"' in js
