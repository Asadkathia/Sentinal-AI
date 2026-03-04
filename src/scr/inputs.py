from __future__ import annotations

import subprocess
from pathlib import Path

from scr.models import ChangeRange, ChangeSet, ChangedFile


class InputError(Exception):
    pass


def collect_changes_from_unified_diff(diff_text: str | None = None, diff_path: str | None = None) -> ChangeSet:
    if diff_path:
        text = Path(diff_path).read_text(encoding="utf-8")
    elif diff_text is not None:
        text = diff_text
    else:
        raise InputError("Either diff_text or diff_path must be provided")

    files = parse_unified_diff(text)
    if not files:
        raise InputError("No changed files found in diff")
    return ChangeSet(mode="diff", diff_text=text, files=files)


def collect_changes_from_git(base_ref: str | None = None) -> ChangeSet:
    base = base_ref or infer_default_base_ref()
    merge_base = run_git(["merge-base", "HEAD", base]).strip()
    if not merge_base:
        raise InputError(f"Could not determine merge-base with {base}")

    diff_text = run_git(["diff", "--unified=3", f"{merge_base}...HEAD"])
    files = parse_unified_diff(diff_text)
    return ChangeSet(mode="git", base_ref=base, diff_text=diff_text, files=files)


def collect_changes_from_paths(paths: list[str]) -> ChangeSet:
    if not paths:
        raise InputError("No paths provided")

    changed_files: list[ChangedFile] = []
    for path in paths:
        p = Path(path)
        if p.is_dir():
            for file in sorted(f for f in p.rglob("*") if f.is_file()):
                changed_files.append(file_as_changed(file))
        elif p.is_file():
            changed_files.append(file_as_changed(p))
        else:
            raise InputError(f"Path not found: {path}")

    return ChangeSet(mode="paths", files=changed_files)


def file_as_changed(path: Path) -> ChangedFile:
    text = path.read_text(encoding="utf-8", errors="ignore")
    line_count = max(1, len(text.splitlines()))
    hunk = f"@@ -1,{line_count} +1,{line_count} @@\n" + text
    added = [(idx + 1, line) for idx, line in enumerate(text.splitlines())]
    return ChangedFile(path=str(path), ranges=[ChangeRange(start_line=1, end_line=line_count)], hunks=[hunk], added_lines=added)


def parse_unified_diff(diff_text: str) -> list[ChangedFile]:
    files: list[ChangedFile] = []
    current: ChangedFile | None = None
    current_hunk: list[str] = []
    new_line_no = 0

    def flush_hunk() -> None:
        nonlocal current_hunk
        if current and current_hunk:
            current.hunks.append("\n".join(current_hunk))
            current_hunk = []

    for raw_line in diff_text.splitlines():
        line = raw_line.rstrip("\n")
        if line.startswith("diff --git "):
            flush_hunk()
            if current:
                files.append(current)
            current = None
            continue

        if line.startswith("+++ "):
            path = line[4:]
            if path.startswith("b/"):
                path = path[2:]
            if path == "/dev/null":
                continue
            current = ChangedFile(path=path)
            continue

        if line.startswith("@@ ") and current:
            flush_hunk()
            current_hunk.append(line)
            # Example: @@ -10,4 +20,6 @@
            parts = line.split(" ")
            new_part = next((p for p in parts if p.startswith("+")), "+0,0")
            start_len = new_part[1:].split(",")
            start = int(start_len[0]) if start_len[0].isdigit() else 0
            length = int(start_len[1]) if len(start_len) > 1 and start_len[1].isdigit() else 1
            if length > 0:
                current.ranges.append(ChangeRange(start_line=start, end_line=start + max(0, length - 1)))
            new_line_no = start
            continue

        if current_hunk:
            current_hunk.append(line)
            if line.startswith("+") and not line.startswith("+++"):
                current.added_lines.append((new_line_no, line[1:]))
                new_line_no += 1
            elif line.startswith("-") and not line.startswith("---"):
                current.removed_lines.append((new_line_no, line[1:]))
            else:
                new_line_no += 1

    flush_hunk()
    if current:
        files.append(current)

    deduped: dict[str, ChangedFile] = {}
    for f in files:
        if f.path in deduped:
            existing = deduped[f.path]
            existing.ranges.extend(f.ranges)
            existing.hunks.extend(f.hunks)
            existing.added_lines.extend(f.added_lines)
            existing.removed_lines.extend(f.removed_lines)
        else:
            deduped[f.path] = f
    return list(deduped.values())


def infer_default_base_ref() -> str:
    candidates = ["origin/main", "main", "origin/master", "master"]
    for ref in candidates:
        result = subprocess.run(["git", "rev-parse", "--verify", ref], capture_output=True, text=True)
        if result.returncode == 0:
            return ref
    raise InputError("Could not infer base ref. Tried origin/main, main, origin/master, master")


def run_git(args: list[str]) -> str:
    process = subprocess.run(["git", *args], capture_output=True, text=True)
    if process.returncode != 0:
        raise InputError(process.stderr.strip() or "git command failed")
    return process.stdout
