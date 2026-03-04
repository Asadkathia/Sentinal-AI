from scr.models import Category, Finding, Location, Severity, SourceInfo
from scr.ranking import dedupe_and_rank


def make_finding(title: str, severity: Severity, confidence: float, file: str, line: int, rule: str, message: str):
    return Finding(
        title=title,
        severity=severity,
        confidence=confidence,
        category=Category.correctness,
        file=file,
        location=Location(start_line=line, end_line=line),
        message=message,
        recommendation=["fix"],
        suggested_tests=["test"],
        source=SourceInfo(analyzer="static", rule=rule),
    )


def test_dedupe_and_rank_stable_ordering():
    findings = [
        make_finding("a", Severity.MEDIUM, 0.7, "b.py", 2, "r1", "same"),
        make_finding("duplicate", Severity.HIGH, 0.8, "b.py", 2, "r1", "same"),
        make_finding("z", Severity.HIGH, 0.6, "a.py", 3, "r2", "msg2"),
        make_finding("n", Severity.LOW, 0.9, "a.py", 1, "r3", "msg3"),
    ]
    ranked = dedupe_and_rank(findings, max_total=10, max_per_file=10)
    assert len(ranked) == 3
    assert ranked[0].severity == Severity.HIGH
    assert ranked[0].confidence == 0.8
    assert ranked[1].file == "a.py"
