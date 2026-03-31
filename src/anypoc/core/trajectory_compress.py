"""
Compressed Trajectory Renderer - Renders trajectory transcripts as compact skeletons.

This module provides utilities to compress large trajectory transcripts (50k+ tokens)
into a compact skeleton format that shows the structure of the trajectory while
allowing retrieval of full details for specific turns.
"""

from __future__ import annotations

import json
from typing import Any


def _format_size(char_count: int) -> str:
    """Format character count as (Nc) or (N.Nk) for thousands."""
    if char_count >= 1000:
        return f"({char_count / 1000:.1f}k)"
    return f"({char_count}c)"


def _truncate(text: str, max_chars: int) -> str:
    """Truncate text and append ... if it exceeds max_chars."""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _extract_text_content(content: Any) -> str:
    """Extract text content from a message content field."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        if content.get("type") == "text":
            return content.get("text", "").strip()
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if isinstance(text, str) and text.strip():
                    texts.append(text.strip())
        return "\n".join(texts)
    return ""


def _get_content_length(content: Any) -> int:
    """Get the total character length of content."""
    text = _extract_text_content(content)
    return len(text)


def _extract_tool_calls_from_content(content: Any) -> list[dict[str, Any]]:
    """Extract tool calls from message content."""
    tool_calls = []

    if isinstance(content, dict):
        if content.get("type") == "tool_use":
            tool_calls.append(
                {
                    "type": "tool_call",
                    "id": content.get("id") or content.get("tool_use_id", ""),
                    "name": content.get("name", ""),
                    "input": content.get("input", {}),
                }
            )
        elif content.get("type") == "tool_bundle":
            # Handle tool bundles that contain paired calls and results
            segments = content.get("segments", [])
            for segment in segments:
                if isinstance(segment, dict) and segment.get("type") == "tool_call":
                    tool_calls.append(
                        {
                            "type": "tool_call",
                            "id": segment.get("tool_use_id", ""),
                            "name": segment.get("name", ""),
                            "input": segment.get("input", {}),
                        }
                    )
    elif isinstance(content, list):
        for block in content:
            tool_calls.extend(_extract_tool_calls_from_content(block))

    return tool_calls


def _extract_tool_results_from_content(content: Any) -> list[dict[str, Any]]:
    """Extract tool results from message content."""
    tool_results = []

    if isinstance(content, dict):
        if content.get("type") == "tool_result":
            tool_results.append(
                {
                    "type": "tool_result",
                    "id": content.get("tool_use_id", ""),
                    "content": content.get("content", ""),
                    "is_error": content.get("is_error", False),
                }
            )
        elif content.get("type") == "tool_bundle":
            # Handle tool bundles that contain paired calls and results
            segments = content.get("segments", [])
            for segment in segments:
                if isinstance(segment, dict) and segment.get("type") == "tool_result":
                    result_content = segment.get("content", "")
                    is_error = segment.get("is_error", False)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "id": segment.get("tool_use_id", ""),
                            "name": segment.get("tool_name") or segment.get("name", ""),
                            "content": result_content,
                            "is_error": is_error,
                        }
                    )
    elif isinstance(content, list):
        for block in content:
            tool_results.extend(_extract_tool_results_from_content(block))

    return tool_results


def _parse_tool_result_content(content: Any) -> tuple[str, bool]:
    """Parse tool result content to extract text and error status."""
    is_error = False

    if isinstance(content, str):
        # Check if it looks like a ToolResultBlock repr
        if content.startswith("ToolResultBlock("):
            is_error = "is_error=True" in content
        return content, is_error

    if isinstance(content, dict):
        is_error = content.get("is_error", False)
        if "content" in content:
            return str(content.get("content", "")), is_error
        if "text" in content:
            return content.get("text", ""), is_error
        return json.dumps(content), is_error

    return str(content) if content else "", is_error


def _build_turn_index(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Build an indexed list of turns from messages.

    Each turn is either:
    - A user message
    - An assistant text message
    - A tool call (with its result status attached)

    Tool results update the status of their corresponding tool call
    rather than getting their own index.
    """
    turns: list[dict[str, Any]] = []
    tool_call_index: dict[str, int] = {}  # tool_use_id -> turn index

    for msg in messages:
        if not isinstance(msg, dict):
            continue

        role = msg.get("role", "")
        content = msg.get("content")

        # Skip result messages and system messages
        if role in ("result", "system"):
            continue

        if role == "user":
            # Check if this is a tool result message
            tool_results = _extract_tool_results_from_content(content)

            if tool_results:
                # Update the corresponding tool calls with results
                for result in tool_results:
                    tool_id = result.get("id", "")
                    if tool_id in tool_call_index:
                        idx = tool_call_index[tool_id]
                        result_content, is_error = _parse_tool_result_content(result.get("content", ""))
                        # Use is_error from the result if present, otherwise parse from content
                        if result.get("is_error"):
                            is_error = True
                        turns[idx]["result_content"] = result_content
                        turns[idx]["is_error"] = is_error
            else:
                # Regular user message
                text = _extract_text_content(content)
                if text:
                    turns.append(
                        {
                            "type": "user",
                            "content": text,
                            "raw_content": content,
                        }
                    )

        elif role == "assistant":
            # Extract text content
            text = _extract_text_content(content)
            if text:
                turns.append(
                    {
                        "type": "asst",
                        "content": text,
                        "raw_content": content,
                    }
                )

            # Extract tool calls
            tool_calls = _extract_tool_calls_from_content(content)
            for tc in tool_calls:
                turn_idx = len(turns)
                tool_call_index[tc["id"]] = turn_idx
                turns.append(
                    {
                        "type": "tool",
                        "name": tc["name"],
                        "input": tc["input"],
                        "result_content": None,
                        "is_error": False,
                        "raw_content": content,
                    }
                )

            # Also check for bundled results in the same message
            tool_results = _extract_tool_results_from_content(content)
            for result in tool_results:
                tool_id = result.get("id", "")
                if tool_id in tool_call_index:
                    idx = tool_call_index[tool_id]
                    result_content, is_error = _parse_tool_result_content(result.get("content", ""))
                    if result.get("is_error"):
                        is_error = True
                    turns[idx]["result_content"] = result_content
                    turns[idx]["is_error"] = is_error

        elif role == "tool":
            # Some formats have tool results as separate messages with role="tool"
            tool_results = _extract_tool_results_from_content(content)
            if not tool_results and isinstance(content, (str, dict)):
                # The content itself might be the result
                tool_id = msg.get("tool_use_id", "")
                if tool_id and tool_id in tool_call_index:
                    idx = tool_call_index[tool_id]
                    result_content, is_error = _parse_tool_result_content(content)
                    turns[idx]["result_content"] = result_content
                    turns[idx]["is_error"] = is_error
            else:
                for result in tool_results:
                    tool_id = result.get("id", "")
                    if tool_id in tool_call_index:
                        idx = tool_call_index[tool_id]
                        result_content, is_error = _parse_tool_result_content(result.get("content", ""))
                        if result.get("is_error"):
                            is_error = True
                        turns[idx]["result_content"] = result_content
                        turns[idx]["is_error"] = is_error

    return turns


def _build_turn_index_from_caw_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Build an indexed list of turns from CAW-format trajectory turns.

    CAW turns have the structure:
        {
            "input": str,           # user message
            "output": [             # list of content blocks
                {"type": "text", "text": str},
                {"type": "tool_use", "name": str, "arguments": dict,
                 "output": str, "is_error": bool},
                ...
            ]
        }

    Returns the same internal format as _build_turn_index().
    """
    result: list[dict[str, Any]] = []

    for turn in turns:
        if not isinstance(turn, dict):
            continue

        # Map turn.input -> user entry
        user_input = turn.get("input", "")
        if isinstance(user_input, str) and user_input.strip():
            result.append(
                {
                    "type": "user",
                    "content": user_input.strip(),
                    "raw_content": user_input,
                }
            )

        # Map turn.output blocks -> asst / tool entries
        output_blocks = turn.get("output", [])
        if not isinstance(output_blocks, list):
            continue

        # Collect all text blocks into a single assistant entry
        text_parts = []
        for block in output_blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text = block.get("text", "")
                if isinstance(text, str) and text.strip():
                    text_parts.append(text.strip())

        if text_parts:
            combined_text = "\n".join(text_parts)
            result.append(
                {
                    "type": "asst",
                    "content": combined_text,
                    "raw_content": combined_text,
                }
            )

        # Tool use blocks (CAW inlines the result on the same block)
        for block in output_blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                result.append(
                    {
                        "type": "tool",
                        "name": block.get("name", ""),
                        "input": block.get("arguments", {}),
                        "result_content": block.get("output"),
                        "is_error": block.get("is_error", False),
                        "raw_content": block,
                    }
                )

    return result


def _get_turns(traj: dict) -> list[dict[str, Any]]:
    """Dispatch to the right turn parser based on trajectory format."""
    if "turns" in traj:
        return _build_turn_index_from_caw_turns(traj["turns"])
    return _build_turn_index(traj.get("messages", []))


def render_compressed_trajectory(
    traj: dict,
    max_input_chars: int = 40,
    max_text_chars: int = 35,
) -> str:
    """
    Render trajectory as a compressed skeleton.

    Args:
        traj: Trajectory dict (from AgentTrajectoryLogger JSON format)
        max_input_chars: Max chars for tool input JSON preview
        max_text_chars: Max chars for user/assistant text preview

    Returns:
        Compressed multi-line string representation

    Format:
        [0] user: "Reproduce the crash in parser..." (156c)
        [1] asst: "I'll examine the parser to..." (843c)
        [2] Read: {"file_path": "/src/pars...} → ok (3.2k)
        [3] Bash: {"command": "make -j8 t...} → Error (512c)
    """
    turns = _get_turns(traj)

    lines = []
    for idx, turn in enumerate(turns):
        turn_type = turn["type"]

        if turn_type == "user":
            text = turn["content"]
            # Normalize whitespace for preview
            text_preview = " ".join(text.split())
            text_preview = _truncate(text_preview, max_text_chars)
            size = _format_size(len(text))
            lines.append(f'[{idx}] user: "{text_preview}" {size}')

        elif turn_type == "asst":
            text = turn["content"]
            # Normalize whitespace for preview
            text_preview = " ".join(text.split())
            text_preview = _truncate(text_preview, max_text_chars)
            size = _format_size(len(text))
            lines.append(f'[{idx}] asst: "{text_preview}" {size}')

        elif turn_type == "tool":
            name = turn["name"]
            input_data = turn["input"]
            result_content = turn.get("result_content")
            is_error = turn.get("is_error", False)

            # Format input as JSON and truncate
            try:
                input_str = json.dumps(input_data, ensure_ascii=False)
            except (TypeError, ValueError):
                input_str = str(input_data)
            input_preview = _truncate(input_str, max_input_chars)

            # Determine status
            status = "Error" if is_error else "ok"

            # Format result size if we have result content
            if result_content is not None:
                result_text, _ = _parse_tool_result_content(result_content)
                size = _format_size(len(result_text))
                lines.append(f"[{idx}] {name}: {input_preview} → {status} {size}")
            else:
                # No result yet (shouldn't happen in complete trajectories)
                lines.append(f"[{idx}] {name}: {input_preview} → {status}")

    return "\n".join(lines)


def get_trajectory_turns(
    traj: dict,
    indices: list[int],
) -> str:
    """
    Get full content for specific turn indices.

    Args:
        traj: Trajectory dict
        indices: List of turn indices to retrieve (e.g., [7, 8, 9, 10])

    Returns:
        Full detailed rendering of the requested turns only
    """
    turns = _get_turns(traj)

    lines = []
    for idx in sorted(indices):
        if idx < 0 or idx >= len(turns):
            lines.append(f"[{idx}] (invalid index)")
            continue

        turn = turns[idx]
        turn_type = turn["type"]

        if turn_type == "user":
            text = turn["content"]
            lines.append(f"[{idx}] user:")
            lines.append(text)
            lines.append("")

        elif turn_type == "asst":
            text = turn["content"]
            lines.append(f"[{idx}] asst:")
            lines.append(text)
            lines.append("")

        elif turn_type == "tool":
            name = turn["name"]
            input_data = turn["input"]
            result_content = turn.get("result_content")
            is_error = turn.get("is_error", False)

            # Format input
            try:
                input_str = json.dumps(input_data, indent=2, ensure_ascii=False)
            except (TypeError, ValueError):
                input_str = str(input_data)

            status = "Error" if is_error else "ok"
            lines.append(f"[{idx}] {name} → {status}")
            lines.append("Input:")
            lines.append(input_str)

            if result_content is not None:
                result_text, _ = _parse_tool_result_content(result_content)
                lines.append("Result:")
                lines.append(result_text)

            lines.append("")

    return "\n".join(lines)


def get_trajectory_summary(traj: dict) -> dict[str, Any]:
    """
    Get a summary of the trajectory.

    Args:
        traj: Trajectory dict

    Returns:
        Dictionary with summary statistics
    """
    turns = _get_turns(traj)

    # Count by type
    user_count = sum(1 for t in turns if t["type"] == "user")
    asst_count = sum(1 for t in turns if t["type"] == "asst")
    tool_count = sum(1 for t in turns if t["type"] == "tool")
    error_count = sum(1 for t in turns if t["type"] == "tool" and t.get("is_error"))

    # Get tool usage breakdown
    tool_usage: dict[str, int] = {}
    for turn in turns:
        if turn["type"] == "tool":
            name = turn["name"]
            tool_usage[name] = tool_usage.get(name, 0) + 1

    # Get duration and cost - prefer CAW top-level fields, fall back to legacy metadata
    duration_ms = traj.get("duration_ms")
    total_cost_usd = None

    # CAW format: usage/total_usage at top level
    total_usage = traj.get("total_usage") or traj.get("usage")
    if isinstance(total_usage, dict):
        total_cost_usd = total_usage.get("cost_usd")

    # Legacy fallback
    if duration_ms is None or total_cost_usd is None:
        metadata = traj.get("metadata") or traj.get("info") or {}
        if duration_ms is None:
            duration_ms = metadata.get("duration_ms")
        if total_cost_usd is None:
            total_cost_usd = metadata.get("total_cost_usd")

    return {
        "total_turns": len(turns),
        "user_messages": user_count,
        "assistant_messages": asst_count,
        "tool_calls": tool_count,
        "tool_errors": error_count,
        "tool_usage": tool_usage,
        "duration_ms": duration_ms,
        "total_cost_usd": total_cost_usd,
    }
