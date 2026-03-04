from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from scr.models import Category, Finding, Location, Severity, SourceInfo, ToolResult


def run_tool_analyzer(config: dict) -> tuple[list[Finding], list[ToolResult]]:
    findings: list[Finding] = []
    tool_results: list[ToolResult] = []

    root = Path.cwd()
    commands = detect_commands(root, config)
    if not commands:
        return findings, [ToolResult(name="tool-runner", status="not_run", summary="No matching toolchain detected")]

    for name, cmd in commands:
        result = execute_command(cmd)
        tool_results.append(result)
        if result.status == "failed":
            findings.append(
                Finding(
                    title=f"Local tool reported issues: {name}",
                    severity=Severity.MEDIUM,
                    confidence=0.85,
                    category=Category.tests,
                    file="(project)",
                    location=Location(),
                    message=result.summary,
                    recommendation=["Inspect local tool output and fix reported violations.", "Re-run `scr review` after addressing errors."],
                    suggested_tests=[f"Re-run `{cmd}` and ensure it passes."],
                    source=SourceInfo(analyzer="tool", rule=name, pointer=cmd),
                )
            )

    return findings, tool_results


def detect_commands(root: Path, config: dict) -> list[tuple[str, str]]:
    cmd_cfg = config.get("tool_commands", {})
    commands: list[tuple[str, str]] = []

    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        for c in cmd_cfg.get("python", []):
            if _cmd_exists(c):
                commands.append(("python", c))
    elif (root / "package.json").exists():
        for c in cmd_cfg.get("node", []):
            commands.append(("node", c))
    elif (root / "go.mod").exists():
        for c in cmd_cfg.get("go", []):
            if _cmd_exists(c):
                commands.append(("go", c))

    return commands


def execute_command(command: str) -> ToolResult:
    try:
        proc = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return ToolResult(name=command, status="not_run", summary="Command not found")
    except subprocess.TimeoutExpired:
        return ToolResult(name=command, status="error", summary="Timed out")

    output = (proc.stdout + "\n" + proc.stderr).strip()
    summary = summarize_output(output)
    if proc.returncode == 0:
        return ToolResult(name=command, status="passed", summary=summary or "passed")
    return ToolResult(name=command, status="failed", summary=summary or "failed")


def summarize_output(output: str, max_lines: int = 4) -> str:
    if not output:
        return ""
    lines = [line for line in output.splitlines() if line.strip()]
    return " | ".join(lines[:max_lines])


def _cmd_exists(command: str) -> bool:
    binary = command.strip().split(" ")[0]
    return shutil.which(binary) is not None
