from fastapi.testclient import TestClient

from scr.web import create_app


def test_api_review_smoke_diff_mode():
    client = TestClient(create_app(no_llm=True))

    health = client.get('/api/health')
    assert health.status_code == 200
    assert health.json() == {"ok": True}

    diff_text = """diff --git a/a.py b/a.py
index 1..2 100644
--- a/a.py
+++ b/a.py
@@ -1 +1,2 @@
-a=1
+b=2
+# TODO follow-up
"""
    review = client.post('/api/review', json={"mode": "diff", "diffText": diff_text})
    assert review.status_code == 200
    payload = review.json()
    assert "reportId" in payload
    assert isinstance(payload["findings"], list)

    report = client.get(f"/api/report/{payload['reportId']}")
    assert report.status_code == 200

    md = client.get(f"/api/report/{payload['reportId']}/markdown")
    assert md.status_code == 200
    assert "Smart Code Reviewer Report" in md.text
