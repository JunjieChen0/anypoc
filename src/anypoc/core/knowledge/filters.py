"""Filters for knowledge extraction."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Callable
from uuid import uuid4

from caw import Agent, ToolGroup


@dataclass(frozen=True)
class KnowledgeFilterRule:
    """Configuration for a knowledge filter rule."""

    name: str
    description: str
    instructions: str
    categories: tuple[str, ...]
    build_prompt: Callable[..., str]
    traj_prefix: str


def _normalize_category_path(path: str) -> list[str]:
    normalized = path.strip().strip("/")
    if normalized.endswith(".md"):
        normalized = normalized[:-3]
    if not normalized:
        return []
    return [part for part in normalized.split("/") if part]


def _extract_category(path: str, project_name: str | None) -> str | None:
    parts = _normalize_category_path(path)
    if not parts:
        return None
    if project_name and parts[0] == project_name:
        return parts[1] if len(parts) > 1 else None
    return parts[0]


def _build_code_knowledge_filter_prompt(
    *,
    path: str,
    content: str,
    keywords: list[str],
    bug_report_path: str | None,
    bug_report_content: str | None,
) -> str:
    keywords_text = ", ".join(keywords) if keywords else "(none)"
    bug_path = bug_report_path or "(not found)"
    bug_body = bug_report_content or "(bug report not available)"
    return f"""You are a strict filter for `code/` knowledge entries.

Goal: Decide if the proposed knowledge is too bug-specific. Use the bug report to judge.

Definition:
- "Too bug-specific" = only useful for this exact bug, PoC steps, crash logs, stack traces,
  reproduction details, or root-cause narratives tied to this run.
- "Reusable" = general facts about code structure, APIs, invariants, pitfalls, constraints,
  tricky patterns, or debugging hints that would help on unrelated future tasks.

Bug report path: {bug_path}

Bug report (truncated if long):
{bug_body}

Proposed knowledge entry:
- path: {path}
- keywords: {keywords_text}
- content:
{content}

Return ONLY valid JSON:
{{
  "decision": "save" | "block",
  "summary": "If decision is block, provide a 2-3 sentence, bug-agnostic summary. Otherwise use an empty string."
}}
"""


def _build_poc_form_filter_prompt(
    *,
    path: str,
    content: str,
    keywords: list[str],
    bug_report_path: str | None,
    bug_report_content: str | None,
) -> str:
    keywords_text = ", ".join(keywords) if keywords else "(none)"
    bug_path = bug_report_path or "(not found)"
    bug_body = bug_report_content or "(bug report not available)"
    return f"""You are a strict filter for `poc_forms/` knowledge entries.

Goal: Decide if the proposed knowledge describes reusable PoC formats/shapes. Use the bug report to judge.

Definition:
- "Too bug-specific" = step-by-step reproduction for this exact bug, crash logs, stack traces,
  addresses, patch references, or root-cause narratives tied to this run.
- "Reusable PoC form" = general PoC formats/shapes and what user capabilities they
  represent (e.g., crafted input files, HTML+JS pages, network payloads, server+client
  harnesses). Focus on forms that demonstrate user-triggerable scenarios, instead of
  internal tests that simulate unrealistic conditions.

Bug report path: {bug_path}

Bug report (truncated if long):
{bug_body}

Proposed knowledge entry:
- path: {path}
- keywords: {keywords_text}
- content:
{content}

Return ONLY valid JSON:
{{
  "decision": "save" | "block",
  "summary": "If decision is block, provide a 2-3 sentence, bug-agnostic summary. Otherwise use an empty string."
}}
"""


def _parse_filter_response(text: str) -> dict[str, str] | None:
    """Parse JSON response from the filter agent."""
    raw = text.strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    decision = str(data.get("decision", "")).strip().lower()
    if decision not in {"save", "block"}:
        return None
    summary = data.get("summary")
    if summary is None:
        summary = ""
    return {"decision": decision, "summary": str(summary).strip()}


def _get_filter_rule_for_path(
    path: str,
    project_name: str | None,
) -> KnowledgeFilterRule | None:
    category = _extract_category(path, project_name)
    if not category:
        return None
    for rule in _FILTER_RULES:
        if category in rule.categories:
            return rule
    return None


def _filter_knowledge_entry(
    *,
    path: str,
    content: str,
    keywords: list[str],
    bug_report_path: str | None,
    bug_report_content: str | None,
    project_name: str | None,
    filter_trajs_dir: Path | None,
) -> dict[str, str] | None:
    """Run a category-specific knowledge filter rule if applicable."""
    rule = _get_filter_rule_for_path(path, project_name)
    if rule is None:
        return None

    prompt = rule.build_prompt(
        path=path,
        content=content,
        keywords=keywords,
        bug_report_path=bug_report_path,
        bug_report_content=bug_report_content,
    )

    traj_path = None
    if filter_trajs_dir is not None:
        filter_trajs_dir.mkdir(parents=True, exist_ok=True)
        unique_name = f"{rule.traj_prefix}_{uuid4().hex[:8]}"
        traj_path = filter_trajs_dir / f"{unique_name}.traj.json"

    agent = Agent(
        name=rule.name,
        description=rule.description,
        system_prompt=rule.instructions,
        tools=ToolGroup.NO_INTERACTION,
        data_dir=None,
    )

    with agent.start_session(traj_path=traj_path) as session:
        turn = session.send(prompt)
        response = turn.result

    return _parse_filter_response(response)


_CODE_FILTER_RULE = KnowledgeFilterRule(
    name="Code Knowledge Filter",
    description="Filters out bug-specific code knowledge entries.",
    instructions=(
        "You are a careful reviewer for knowledge entries in the code/ category.\n\n"
        "You must classify the entry as:\n"
        "- save: reusable across unrelated future tasks\n"
        "- block: too tied to the current bug report\n\n"
        "If you block, provide a 2-3 sentence, bug-agnostic summary of the useful general ideas "
        "(no bug-specifics). Return JSON only."
    ),
    categories=("code",),
    build_prompt=_build_code_knowledge_filter_prompt,
    traj_prefix="code_filter",
)

_POC_FORM_FILTER_RULE = KnowledgeFilterRule(
    name="PoC Form Filter",
    description="Filters out bug-specific PoC form knowledge entries.",
    instructions=(
        "You are a careful reviewer for knowledge entries in the poc_forms/ category.\n\n"
        "You must classify the entry as:\n"
        "- save: reusable PoC formats representing user-triggerable scenarios\n"
        "- block: too tied to the current bug report, OR only describes internal tests "
        "that simulate unrealistic conditions\n\n"
        "If you block, provide a 2-3 sentence, bug-agnostic summary of the reusable PoC form "
        "(no bug-specifics). Return JSON only."
    ),
    categories=("poc_forms", "poc_patterns"),
    build_prompt=_build_poc_form_filter_prompt,
    traj_prefix="poc_form_filter",
)

_FILTER_RULES = (_CODE_FILTER_RULE, _POC_FORM_FILTER_RULE)
