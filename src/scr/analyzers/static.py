from __future__ import annotations

import re
from collections import Counter

from scr.context import extract_context
from scr.models import Category, ChangeRange, ChangeSet, Finding, Location, Severity, SourceInfo


def run_static_analyzer(changes: ChangeSet, context_map: dict, config: dict) -> list[Finding]:
    findings: list[Finding] = []
    fn_len_threshold = int(config.get("large_function_threshold", 60))
    nesting_threshold = int(config.get("deep_nesting_threshold", 4))
    param_threshold = int(config.get("too_many_params_threshold", 5))

    touched_files = {f.path for f in changes.files}
    docs_or_tests_touched = any(
        p.startswith("docs/") or "/test" in p or p.startswith("tests/") or p.endswith("_test.py") for p in touched_files
    )

    for changed in changes.files:
        lines = context_map.get(changed.path, {}).get("lines", [])
        if not lines:
            continue
        changed_ranges: list[ChangeRange] = changed.ranges or [ChangeRange(start_line=1, end_line=len(lines) or 1)]

        findings.extend(_check_todo_fixme(changed.path, changed.added_lines))
        findings.extend(_check_error_swallow(changed.path, lines, changed_ranges))
        findings.extend(_check_name_clarity(changed.path, lines, changed_ranges))
        findings.extend(_check_too_many_params(changed.path, lines, changed_ranges, param_threshold))
        findings.extend(_check_large_function(changed.path, lines, changed_ranges, fn_len_threshold))
        findings.extend(_check_deep_nesting(changed.path, lines, changed_ranges, nesting_threshold))
        findings.extend(_check_inconsistent_return(changed.path, lines, changed_ranges))
        findings.extend(_check_duplicate_blocks(changed.path, changed.added_lines))

        api_change = _public_api_changed(changed)
        if api_change and not docs_or_tests_touched:
            findings.append(
                Finding(
                    title="Public API changed without docs/tests update",
                    severity=Severity.MEDIUM,
                    confidence=0.62,
                    category=Category.tests,
                    file=changed.path,
                    location=Location(start_line=api_change),
                    message="Public function/class signatures appear changed, but no related docs or tests were modified.",
                    recommendation=[
                        "Add or update tests that cover the changed API behavior.",
                        "Update docs/changelog for externally visible API changes.",
                    ],
                    suggested_tests=["Add an integration test covering the modified public API."],
                    source=SourceInfo(analyzer="static", rule="api_change_without_docs_tests"),
                    context=extract_context(lines, ChangeRange(start_line=api_change, end_line=api_change)),
                )
            )

    return findings


def _intersects(line_no: int, ranges: list[ChangeRange]) -> bool:
    return any(r.start_line <= line_no <= r.end_line for r in ranges)


def _check_todo_fixme(path: str, added_lines: list[tuple[int, str]]) -> list[Finding]:
    out: list[Finding] = []
    for line_no, text in added_lines:
        if re.search(r"\b(TODO|FIXME)\b", text, flags=re.IGNORECASE):
            out.append(
                Finding(
                    title="New TODO/FIXME added",
                    severity=Severity.LOW,
                    confidence=0.9,
                    category=Category.maintainability,
                    file=path,
                    location=Location(start_line=line_no, end_line=line_no),
                    message="New TODO/FIXME markers were introduced. They often become long-lived debt without tracking.",
                    recommendation=["Convert the TODO/FIXME to a tracked issue link.", "Define acceptance criteria and owner."],
                    suggested_tests=[],
                    source=SourceInfo(analyzer="static", rule="todo_fixme_added"),
                )
            )
    return out


def _check_error_swallow(path: str, lines: list[str], ranges: list[ChangeRange]) -> list[Finding]:
    out: list[Finding] = []
    for idx, line in enumerate(lines, start=1):
        if not _intersects(idx, ranges):
            continue
        if re.search(r"\bexcept\b.*:\s*pass\b", line) or re.search(r"\bcatch\s*\([^)]*\)\s*\{\s*\}", line):
            out.append(
                Finding(
                    title="Swallowed exception",
                    severity=Severity.HIGH,
                    confidence=0.87,
                    category=Category.correctness,
                    file=path,
                    location=Location(start_line=idx, end_line=idx),
                    message="Exception is swallowed without logging or remediation, which can hide production failures.",
                    recommendation=["Log the error with context.", "Return/raise a meaningful domain error or fallback result."],
                    suggested_tests=["Add a test asserting behavior when the underlying call throws."],
                    source=SourceInfo(analyzer="static", rule="swallowed_error"),
                    context=extract_context(lines, ChangeRange(start_line=idx, end_line=idx)),
                )
            )
    return out


def _check_name_clarity(path: str, lines: list[str], ranges: list[ChangeRange]) -> list[Finding]:
    out: list[Finding] = []
    pattern = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]?)\s*=")
    for idx, line in enumerate(lines, start=1):
        if not _intersects(idx, ranges):
            continue
        m = pattern.match(line)
        if not m:
            continue
        var = m.group(1)
        if len(var) == 1 and var not in {"i", "j", "k", "x", "y"}:
            out.append(
                Finding(
                    title="Low-clarity variable name",
                    severity=Severity.LOW,
                    confidence=0.67,
                    category=Category.readability,
                    file=path,
                    location=Location(start_line=idx, end_line=idx, symbol=var),
                    message="Single-letter variable in non-loop context can reduce readability.",
                    recommendation=["Rename variable to reflect domain intent."],
                    suggested_tests=[],
                    source=SourceInfo(analyzer="static", rule="name_clarity_single_letter"),
                )
            )
    return out


def _check_too_many_params(path: str, lines: list[str], ranges: list[ChangeRange], threshold: int) -> list[Finding]:
    out: list[Finding] = []
    fn_pattern = re.compile(r"^\s*(def|function)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)")
    for idx, line in enumerate(lines, start=1):
        m = fn_pattern.match(line)
        if not m:
            continue
        if not _intersects(idx, ranges):
            continue
        params = [p.strip() for p in m.group(3).split(",") if p.strip() and p.strip() not in {"self", "cls"}]
        if len(params) > threshold:
            name = m.group(2)
            out.append(
                Finding(
                    title="Function has too many parameters",
                    severity=Severity.MEDIUM,
                    confidence=0.76,
                    category=Category.structure,
                    file=path,
                    location=Location(start_line=idx, end_line=idx, symbol=name),
                    message=f"`{name}` accepts {len(params)} parameters, which may indicate mixed responsibilities.",
                    recommendation=["Group related params into an object/dataclass.", "Split responsibilities into smaller functions."],
                    suggested_tests=["Add focused unit tests for each parameter cluster or branch."],
                    source=SourceInfo(analyzer="static", rule="too_many_params"),
                )
            )
    return out


def _function_blocks(lines: list[str]) -> list[tuple[str, int, int, list[str]]]:
    blocks: list[tuple[str, int, int, list[str]]] = []
    fn_pattern = re.compile(r"^(\s*)(def|function)\s+([A-Za-z_][A-Za-z0-9_]*)")
    i = 0
    while i < len(lines):
        line = lines[i]
        m = fn_pattern.match(line)
        if not m:
            i += 1
            continue
        indent = len(m.group(1))
        name = m.group(3)
        start = i + 1
        j = i + 1
        while j < len(lines):
            raw = lines[j]
            if raw.strip() and len(raw) - len(raw.lstrip(" ")) <= indent and fn_pattern.match(raw):
                break
            j += 1
        end = j
        blocks.append((name, start, end, lines[i:j]))
        i = j
    return blocks


def _check_large_function(path: str, lines: list[str], ranges: list[ChangeRange], threshold: int) -> list[Finding]:
    out: list[Finding] = []
    for name, start, end, block in _function_blocks(lines):
        if end - start + 1 <= threshold:
            continue
        if not any(_intersects(line, ranges) for line in range(start, end + 1)):
            continue
        out.append(
            Finding(
                title="Large function",
                severity=Severity.MEDIUM,
                confidence=0.73,
                category=Category.maintainability,
                file=path,
                location=Location(start_line=start, end_line=end, symbol=name),
                message=f"Function `{name}` spans {end - start + 1} lines, making reasoning and testing harder.",
                recommendation=["Extract helper functions around independent logic chunks.", "Keep IO and business logic separated."],
                suggested_tests=["Add targeted tests per extracted helper behavior."],
                source=SourceInfo(analyzer="static", rule="large_function"),
                context=extract_context(lines, ChangeRange(start_line=start, end_line=min(end, start + 5))),
            )
        )
    return out


def _check_deep_nesting(path: str, lines: list[str], ranges: list[ChangeRange], threshold: int) -> list[Finding]:
    out: list[Finding] = []
    for idx, line in enumerate(lines, start=1):
        if not _intersects(idx, ranges):
            continue
        indent_spaces = len(line) - len(line.lstrip(" "))
        brace_depth = line.count("{") - line.count("}")
        indent_depth = indent_spaces // 4 + max(0, brace_depth)
        if indent_depth >= threshold and re.search(r"\b(if|for|while|try|switch)\b", line):
            out.append(
                Finding(
                    title="Deep nesting in changed code",
                    severity=Severity.MEDIUM,
                    confidence=0.66,
                    category=Category.structure,
                    file=path,
                    location=Location(start_line=idx, end_line=idx),
                    message="Deep nesting increases branching complexity and maintenance cost.",
                    recommendation=["Use guard clauses/early returns.", "Extract nested branches into named helpers."],
                    suggested_tests=["Add branch coverage tests for each nested condition path."],
                    source=SourceInfo(analyzer="static", rule="deep_nesting"),
                )
            )
    return out


def _check_inconsistent_return(path: str, lines: list[str], ranges: list[ChangeRange]) -> list[Finding]:
    out: list[Finding] = []
    for name, start, end, block in _function_blocks(lines):
        if not any(_intersects(line, ranges) for line in range(start, end + 1)):
            continue
        return_types: Counter[str] = Counter()
        for idx, line in enumerate(block, start=start):
            m = re.search(r"\breturn\b\s*(.*)$", line)
            if not m:
                continue
            expr = m.group(1).strip()
            if expr in {"", "None", "null", "undefined"}:
                return_types["none"] += 1
            elif re.match(r"['\"].*['\"]$", expr):
                return_types["string"] += 1
            elif re.match(r"-?\d+(\.\d+)?$", expr):
                return_types["number"] += 1
            elif expr in {"True", "False", "true", "false"}:
                return_types["bool"] += 1
            else:
                return_types["object"] += 1
        if len(return_types) >= 3:
            out.append(
                Finding(
                    title="Inconsistent return shapes",
                    severity=Severity.HIGH,
                    confidence=0.64,
                    category=Category.correctness,
                    file=path,
                    location=Location(start_line=start, end_line=end, symbol=name),
                    message=f"`{name}` appears to return multiple unrelated types: {', '.join(sorted(return_types))}.",
                    recommendation=["Normalize return type (single data shape or typed result object).", "Use exceptions for error paths instead of ad-hoc return values."],
                    suggested_tests=["Add tests asserting stable return type across success/error paths."],
                    source=SourceInfo(analyzer="static", rule="inconsistent_return_types"),
                )
            )
    return out


def _check_duplicate_blocks(path: str, added_lines: list[tuple[int, str]]) -> list[Finding]:
    out: list[Finding] = []
    normalized = [(ln, re.sub(r"\s+", " ", txt.strip())) for ln, txt in added_lines if txt.strip()]
    windows: dict[str, list[int]] = {}
    size = 3
    for i in range(0, max(0, len(normalized) - size + 1)):
        block = "\n".join(t for _, t in normalized[i : i + size])
        windows.setdefault(block, []).append(normalized[i][0])
    for block, starts in windows.items():
        if len(starts) > 1:
            line = starts[1]
            out.append(
                Finding(
                    title="Near-duplicate code in added block",
                    severity=Severity.MEDIUM,
                    confidence=0.71,
                    category=Category.maintainability,
                    file=path,
                    location=Location(start_line=line, end_line=line + size - 1),
                    message="Very similar code blocks were added multiple times in the same patch.",
                    recommendation=["Extract repeated logic into a helper or shared utility."],
                    suggested_tests=["Add a regression test around the extracted helper behavior."],
                    source=SourceInfo(analyzer="static", rule="duplicate_block"),
                    suggested_patch=f"# Repeated block candidate:\n{block}",
                )
            )
            break
    return out


def _public_api_changed(changed_file) -> int | None:
    if not (changed_file.path.startswith("src/") or changed_file.path.endswith(".py") or changed_file.path.endswith(".ts")):
        return None
    patt = re.compile(r"^\s*(def|class|export\s+function|export\s+class)\s+")
    for line_no, text in changed_file.added_lines + changed_file.removed_lines:
        if patt.search(text):
            return line_no
    return None
