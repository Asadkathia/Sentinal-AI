from __future__ import annotations

import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from scr.engine import EngineError, dump_report_json, run_review
from scr.models import ReviewRequest, Severity
from scr.renderers import render_markdown


class ReviewPayload(BaseModel):
    mode: str
    base: Optional[str] = None
    diffText: Optional[str] = None
    paths: Optional[List[str]] = None
    failOn: str = "HIGH"
    maxFindings: int = 12
    maxPerFile: int = 3


def create_app(no_llm: bool = False) -> FastAPI:
    app = FastAPI(title="Smart Code Reviewer")
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    reports: dict[str, dict] = {}

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.post("/api/review")
    def api_review(payload: ReviewPayload) -> dict:
        req = _payload_to_request(payload, no_llm=no_llm)
        try:
            report, summary = run_review(req)
        except EngineError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        report_id = uuid.uuid4().hex[:10]
        report_json = dump_report_json(report)
        report_json["summary"] = summary.model_dump(mode="json")
        reports[report_id] = report_json
        return {"reportId": report_id, "summary": summary.model_dump(mode="json"), "findings": report_json["findings"]}

    @app.get("/api/report/{report_id}")
    def api_report(report_id: str) -> dict:
        report = reports.get(report_id)
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        return report

    @app.get("/api/report/{report_id}/markdown")
    def api_report_markdown(report_id: str) -> PlainTextResponse:
        report = reports.get(report_id)
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        from scr.models import Report

        md = render_markdown(Report.model_validate(report))
        return PlainTextResponse(md)

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        return templates.TemplateResponse("index.html", {"request": request})

    @app.get("/report/{report_id}", response_class=HTMLResponse)
    def report_page(request: Request, report_id: str) -> HTMLResponse:
        if report_id not in reports:
            raise HTTPException(status_code=404, detail="Report not found")
        return templates.TemplateResponse("report.html", {"request": request, "report_id": report_id})

    return app


def _payload_to_request(payload: ReviewPayload, no_llm: bool) -> ReviewRequest:
    mode = payload.mode
    if mode not in {"git", "diff", "paths"}:
        raise EngineError("mode must be one of git|diff|paths")
    return ReviewRequest(
        mode=mode,
        base=payload.base,
        diff_text=payload.diffText,
        paths=payload.paths,
        fail_on=Severity(payload.failOn.upper()),
        max_findings=payload.maxFindings,
        max_per_file=payload.maxPerFile,
        no_llm=no_llm,
    )
