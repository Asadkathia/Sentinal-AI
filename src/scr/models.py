from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Severity(str, Enum):
    BLOCKER = "BLOCKER"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NIT = "NIT"


class Category(str, Enum):
    readability = "readability"
    structure = "structure"
    maintainability = "maintainability"
    correctness = "correctness"
    performance = "performance"
    security = "security"
    tests = "tests"
    docs = "docs"


SEVERITY_RANK = {
    Severity.BLOCKER: 5,
    Severity.HIGH: 4,
    Severity.MEDIUM: 3,
    Severity.LOW: 2,
    Severity.NIT: 1,
}


class Location(BaseModel):
    start_line: int | None = None
    end_line: int | None = None
    symbol: str | None = None


class SourceInfo(BaseModel):
    analyzer: Literal["static", "tool", "llm"]
    rule: str
    pointer: str | None = None


class Finding(BaseModel):
    id: str = ""
    title: str
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    category: Category
    file: str
    location: Location = Field(default_factory=Location)
    message: str
    recommendation: list[str] = Field(default_factory=list)
    suggested_tests: list[str] = Field(default_factory=list)
    suggested_patch: str | None = None
    source: SourceInfo
    context: str | None = None

    @model_validator(mode="after")
    def ensure_id(self) -> "Finding":
        if not self.id:
            self.id = stable_finding_id(self)
        return self


class ToolResult(BaseModel):
    name: str
    status: Literal["passed", "failed", "not_run", "error"]
    summary: str


class ReportMetadata(BaseModel):
    timestamp: str
    repo_root: str
    input_mode: Literal["git", "diff", "paths"]
    base_ref: str | None = None
    llm_used: bool = False
    tools: list[ToolResult] = Field(default_factory=list)
    config: dict


class Report(BaseModel):
    metadata: ReportMetadata
    findings: list[Finding] = Field(default_factory=list)


class ChangeRange(BaseModel):
    start_line: int
    end_line: int


class ChangedFile(BaseModel):
    path: str
    old_path: str | None = None
    ranges: list[ChangeRange] = Field(default_factory=list)
    hunks: list[str] = Field(default_factory=list)
    added_lines: list[tuple[int, str]] = Field(default_factory=list)
    removed_lines: list[tuple[int, str]] = Field(default_factory=list)


class ChangeSet(BaseModel):
    mode: Literal["git", "diff", "paths"]
    base_ref: str | None = None
    diff_text: str = ""
    files: list[ChangedFile] = Field(default_factory=list)


class ReviewRequest(BaseModel):
    mode: Literal["git", "diff", "paths"]
    base: str | None = None
    diff_text: str | None = None
    paths: list[str] | None = None
    format: Literal["md", "json", "both"] = "md"
    fail_on: Severity = Severity.HIGH
    max_findings: int = 12
    max_per_file: int = 3
    no_llm: bool = False


class ReviewSummary(BaseModel):
    total_findings: int
    by_severity: dict[str, int]
    threshold_exceeded: bool
    llm_used: bool


class ReviewResponse(BaseModel):
    report_id: str
    summary: ReviewSummary
    findings: list[Finding]


def stable_finding_id(finding: Finding) -> str:
    payload = "|".join(
        [
            finding.source.rule,
            finding.file,
            str(finding.location.start_line or ""),
            str(finding.location.end_line or ""),
            normalize_text(finding.message),
        ]
    )
    return sha256(payload.encode("utf-8")).hexdigest()[:12]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


def project_root_from(paths: list[str]) -> str:
    if not paths:
        return str(Path.cwd())
    return str(Path(paths[0]).resolve().parent)
