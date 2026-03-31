"""YAML frontmatter helpers for bug report markdown files."""

from __future__ import annotations

from typing import Any

import yaml

_DELIM = "---"


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a markdown document into (frontmatter dict, body string).

    If the document does not start with a frontmatter block, returns ({}, text).
    """
    stripped = text.lstrip("\ufeff")  # tolerate BOM
    if not stripped.startswith(_DELIM):
        return {}, text

    lines = stripped.splitlines()
    if not lines or lines[0].strip() != _DELIM:
        return {}, text

    end_index: int | None = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == _DELIM:
            end_index = idx
            break
    if end_index is None:
        return {}, text

    raw_fm = "\n".join(lines[1:end_index])
    body_lines = lines[end_index + 1 :]
    # Strip a single leading blank line after the closing delimiter
    if body_lines and body_lines[0] == "":
        body_lines = body_lines[1:]
    body = "\n".join(body_lines)

    try:
        parsed = yaml.safe_load(raw_fm) or {}
    except yaml.YAMLError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return parsed, body


def render_with_frontmatter(metadata: dict[str, Any], body: str) -> str:
    """Render a markdown document with the given metadata as YAML frontmatter."""
    fm = yaml.safe_dump(metadata, sort_keys=False, default_flow_style=False).rstrip("\n")
    body_clean = body.lstrip("\n")
    return f"{_DELIM}\n{fm}\n{_DELIM}\n\n{body_clean}\n"
