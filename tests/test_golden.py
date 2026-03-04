import json
from pathlib import Path

from scr.engine import run_review
from scr.models import ReviewRequest


def test_golden_example_diff_json_findings_stable():
    request = ReviewRequest(mode="diff", diff_text="fixtures/example.diff", no_llm=True, max_findings=12, max_per_file=3)
    report, _summary = run_review(request)
    findings = [f.model_dump(mode="json") for f in report.findings]

    expected_path = Path("fixtures/example_report.json")
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    assert findings == expected
