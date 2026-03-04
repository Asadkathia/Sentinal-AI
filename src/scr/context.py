from __future__ import annotations

from pathlib import Path

from scr.models import ChangeRange, ChangeSet


def load_file_text(path: str) -> list[str]:
    try:
        return Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []


def extract_context(lines: list[str], rng: ChangeRange, before: int = 3, after: int = 3) -> str:
    if not lines:
        return ""
    start = max(1, rng.start_line - before)
    end = min(len(lines), rng.end_line + after)
    out = []
    for i in range(start, end + 1):
        marker = ">" if rng.start_line <= i <= rng.end_line else " "
        out.append(f"{marker}{i:4d}: {lines[i - 1]}")
    return "\n".join(out)


def build_context_map(changes: ChangeSet) -> dict[str, dict[str, object]]:
    context: dict[str, dict[str, object]] = {}
    for f in changes.files:
        lines = load_file_text(f.path)
        ranges = f.ranges or [ChangeRange(start_line=1, end_line=max(1, len(lines)))]
        contexts = [extract_context(lines, r) for r in ranges]
        context[f.path] = {"lines": lines, "range_context": contexts, "hunks": f.hunks, "ranges": ranges}
    return context
