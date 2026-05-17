#!/usr/bin/env python3
"""Structured Obsidian vault tools.

These tools intentionally expose narrow, structured views of Charlie's Obsidian
vault so agents do not need to raw-read high-churn control files like Tasks.md.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from tools.registry import registry, tool_error


_DEFAULT_VAULT = "~/Documents/Obsidian Vault"
_TASK_RE = re.compile(r"^(?P<indent>\s*)[-*+]\s+\[(?P<mark>[^\]]*)\]\s*(?P<text>.*)$")
_HEADING_RE = re.compile(r"^(?P<level>#{1,6})\s+(?P<title>.*?)(?:\s+#+\s*)?$")
_DATE_RE = re.compile(r"(?:📅|due:?|scheduled:?|start:?)\s*(?P<date>\d{4}-\d{2}-\d{2})", re.IGNORECASE)


def _config_vault_path() -> str | None:
    """Return obsidian.vault_path from config.yaml when configured."""
    try:
        from hermes_cli.config import load_config

        cfg = load_config() or {}
        obsidian_cfg = cfg.get("obsidian") or {}
        if isinstance(obsidian_cfg, dict):
            raw = obsidian_cfg.get("vault_path")
            if raw:
                return str(raw)
    except Exception:
        return None
    return None


def _vault_path() -> Path:
    """Return the configured Obsidian vault path."""
    raw = os.environ.get("OBSIDIAN_VAULT_PATH") or _config_vault_path() or _DEFAULT_VAULT
    return Path(raw).expanduser().resolve()


def _check_obsidian_reqs() -> bool:
    """The Obsidian toolset is available when the vault directory exists."""
    try:
        return _vault_path().is_dir()
    except Exception:
        return False


def _resolve_vault_file(path: str | None) -> tuple[Path, Path]:
    """Resolve a vault-relative path and keep reads inside the vault."""
    vault = _vault_path()
    requested = path or "Tasks.md"
    p = Path(requested).expanduser()
    resolved = p.resolve() if p.is_absolute() else (vault / p).resolve()

    try:
        resolved.relative_to(vault)
    except ValueError as exc:
        raise ValueError("path must resolve inside the configured Obsidian vault") from exc

    return vault, resolved


def _status_for_marker(marker: str) -> str:
    mark = (marker or " ").strip().lower()
    if mark in {"", " "}:
        return "open"
    if mark == "x":
        return "done"
    if mark == "-":
        return "cancelled"
    return "active"


def _extract_due(text: str) -> str | None:
    match = _DATE_RE.search(text)
    return match.group("date") if match else None


def _empty_counts() -> dict[str, int]:
    return {"open": 0, "active": 0, "done": 0, "cancelled": 0}


def obsidian_read_tasks_tool(path: str = "Tasks.md", include_done: bool = False, limit: int = 50) -> str:
    """Read Markdown tasks from an Obsidian note as structured JSON."""
    try:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            return tool_error("limit must be an integer")
        if limit < 0:
            return tool_error("limit must be >= 0")
        limit = min(limit, 500)

        vault, file_path = _resolve_vault_file(path)
        if not file_path.exists():
            return tool_error(f"Obsidian file not found: {file_path.relative_to(vault)}")
        if not file_path.is_file():
            return tool_error(f"Obsidian path is not a file: {file_path.relative_to(vault)}")

        tasks: list[dict[str, Any]] = []
        status_counts = _empty_counts()
        section_counts: dict[str, dict[str, Any]] = {}
        matched_count = 0
        current_section = "(top)"
        current_level = 0

        for line_no, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
            heading = _HEADING_RE.match(line)
            if heading:
                current_level = len(heading.group("level"))
                current_section = heading.group("title").strip() or "(untitled)"
                continue

            match = _TASK_RE.match(line)
            if not match:
                continue

            marker = match.group("mark")
            status = _status_for_marker(marker)
            status_counts.setdefault(status, 0)
            status_counts[status] += 1

            section_entry = section_counts.setdefault(current_section, {"section": current_section, **_empty_counts()})
            section_entry.setdefault(status, 0)
            section_entry[status] += 1

            if not include_done and status in {"done", "cancelled"}:
                continue

            matched_count += 1
            if len(tasks) >= limit:
                continue

            text = match.group("text").strip()
            tasks.append({
                "line": line_no,
                "section": current_section,
                "heading_level": current_level,
                "status": status,
                "marker": marker,
                "text": text,
                "due": _extract_due(text),
            })

        rel_path = str(file_path.relative_to(vault))
        active_total = status_counts.get("open", 0) + status_counts.get("active", 0)
        total_tasks = sum(status_counts.values())
        result = {
            "path": rel_path,
            "include_done": include_done,
            "limit": limit,
            "total_tasks": total_tasks,
            "active_tasks": active_total,
            "matched_tasks": matched_count,
            "returned_tasks": len(tasks),
            "truncated": matched_count > len(tasks),
            "status_counts": status_counts,
            "section_counts": list(section_counts.values()),
            "summary": (
                f"{len(tasks)} of {matched_count} matching tasks returned from {rel_path}; "
                f"{active_total} active/open tasks, {status_counts.get('done', 0)} done, "
                f"{status_counts.get('cancelled', 0)} cancelled."
            ),
            "tasks": tasks,
        }
        return json.dumps(result, ensure_ascii=False)
    except UnicodeDecodeError:
        return tool_error("Obsidian file is not valid UTF-8 text")
    except Exception as exc:
        return tool_error(str(exc))


OBSIDIAN_READ_TASKS_SCHEMA = {
    "name": "obsidian_read_tasks",
    "description": (
        "Read Markdown tasks from an Obsidian note as structured JSON. "
        "Use this instead of raw-reading Tasks.md when you need Charlie's task list. "
        "By default it returns only active/open tasks, grouped with section and line metadata."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Vault-relative Obsidian note path to scan (default: Tasks.md). Absolute paths must stay inside the vault.",
                "default": "Tasks.md",
            },
            "include_done": {
                "type": "boolean",
                "description": "Include completed [x] and cancelled [-] tasks as well as active/open tasks.",
                "default": False,
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of matching task records to return (default 50, max 500). Counts still include the whole file.",
                "default": 50,
                "minimum": 0,
                "maximum": 500,
            },
        },
        "required": [],
    },
}


def _handle_obsidian_read_tasks(args, **kw):
    args = args or {}
    return obsidian_read_tasks_tool(
        path=args.get("path", "Tasks.md"),
        include_done=bool(args.get("include_done", False)),
        limit=args.get("limit", 50),
    )


registry.register(
    name="obsidian_read_tasks",
    toolset="obsidian",
    schema=OBSIDIAN_READ_TASKS_SCHEMA,
    handler=_handle_obsidian_read_tasks,
    check_fn=_check_obsidian_reqs,
    emoji="📝",
    max_result_size_chars=100_000,
)
