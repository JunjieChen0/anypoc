from __future__ import annotations

import asyncio
import json
import re
from enum import Enum
from pathlib import Path
from typing import Any, Type, TypeVar

from caw import Agent, ModelTier, ToolGroup
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)
LLMModelT = TypeVar("LLMModelT", bound="LLMGeneratedBaseModel")

_SECTION_HEADER_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
_CODE_BLOCK_RE = re.compile(r"```(?:[\w+-]+)?\s*\n([\s\S]*?)```", re.MULTILINE)
_FENCED_BLOCK_RE = re.compile(r"^```(?:[\w+-]+)?\s*\n([\s\S]*?)\n```$", re.DOTALL)


def _snake_to_readable(snake_str: str) -> str:
    words = snake_str.split("_")
    return " ".join(word.capitalize() for word in words)


def _normalize_header_text(header: str) -> str:
    header = header.strip().strip("#").strip()
    header = header.rstrip(":")
    header = re.sub(r"\s+", " ", header)
    return header.lower()


def _split_sections_from_markdown(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_header: str | None = None
    buffer: list[str] = []
    top_level: int | None = None
    for line in text.splitlines():
        header_match = _SECTION_HEADER_RE.match(line)
        if header_match:
            level = len(header_match.group(1))
            if top_level is None:
                top_level = level
            if level != top_level:
                if current_header is not None:
                    buffer.append(line)
                continue
            if current_header is not None:
                sections.append((current_header, "\n".join(buffer).strip()))
            current_header = header_match.group(2).strip()
            buffer = []
            continue
        if current_header is not None:
            buffer.append(line)
    if current_header is not None:
        sections.append((current_header, "\n".join(buffer).strip()))
    return sections


# Greedy match so inner ``` fences (e.g. code snippets) don't terminate early.
_MARKDOWN_FENCE_RE = re.compile(r"```markdown\s*\n([\s\S]*)```", re.MULTILINE)


def _extract_sections(text: str, valid_headers: set[str] | None = None) -> list[tuple[str, str]]:
    stripped = text.strip()
    first_line = _first_nonempty_line(stripped)
    # Structured-output mode: first line is a heading whose name matches a known model field.
    if first_line:
        header_match = _SECTION_HEADER_RE.match(first_line)
        if header_match:
            normalized = _normalize_header_text(header_match.group(2))
            if valid_headers is None or normalized in valid_headers:
                return _split_sections_from_markdown(stripped)
    # Reasoning/preamble mode: try the first ```markdown block first.
    block_match = _MARKDOWN_FENCE_RE.search(stripped)
    if block_match:
        return _split_sections_from_markdown(block_match.group(1).strip())
    # Fallback: parse the whole text (handles structured output inside plain ``` blocks).
    return _split_sections_from_markdown(stripped)


def _first_nonempty_line(value: str) -> str:
    for line in value.splitlines():
        stripped_line = line.strip()
        if stripped_line:
            return stripped_line
    return ""


def _strip_enclosing_wrappers(value: str) -> str:
    if not value:
        return value
    wrapped_pairs = [("**", "**"), ("`", "`"), ("'", "'"), ('"', '"')]
    for start, end in wrapped_pairs:
        if value.startswith(start) and value.endswith(end):
            return value[len(start) : len(value) - len(end)].strip()
    return value


def _strip_enum_prefix(value: str) -> str:
    lowered = value.lstrip("-* ")
    if lowered.lower().startswith("option:"):
        return lowered.split(":", 1)[1].strip()
    return lowered.strip()


def _extract_enum_value(content: str, enum_values: list[str]) -> str | None:
    first_line = _first_nonempty_line(content)
    if not first_line:
        return None
    candidate = _strip_enum_prefix(_strip_enclosing_wrappers(first_line))
    normalized_map = {enum_value.casefold(): enum_value for enum_value in enum_values}
    normalized_candidate = candidate.casefold()
    if normalized_candidate in normalized_map:
        return normalized_map[normalized_candidate]
    for enum_value in enum_values:
        if normalized_candidate.startswith(enum_value.casefold()):
            return enum_value
    for enum_value in enum_values:
        if re.search(rf"\b{re.escape(enum_value)}\b", content, re.IGNORECASE):
            return enum_value
    return None


def _unwrap_fenced_block(value: str) -> str:
    match = _FENCED_BLOCK_RE.match(value.strip())
    if match:
        return match.group(1).strip()
    return value.strip()


def _extract_string_value(content: str) -> str | None:
    if not content.strip():
        return None
    cleaned = _unwrap_fenced_block(content)
    cleaned = _strip_enclosing_wrappers(cleaned)
    cleaned = cleaned.strip()
    return cleaned or None


def _parse_markdown_to_data(text: str, model: Type[T]) -> dict[str, Any]:
    schema = model.model_json_schema()
    properties = schema.get("properties", {})
    defs = schema.get("$defs", {})
    readable_to_field = {
        _normalize_header_text(_snake_to_readable(field_name)): field_name for field_name in model.model_fields
    }
    sections = _extract_sections(text, valid_headers=set(readable_to_field.keys()))
    if not sections:
        return {}
    parsed: dict[str, Any] = {}
    for header, content in sections:
        normalized_header = _normalize_header_text(header)
        field_name = readable_to_field.get(normalized_header)
        if not field_name:
            continue
        field_schema = properties.get(field_name, {})
        enum_values = _resolve_enum_values(field_schema, defs)
        if enum_values:
            enum_value = _extract_enum_value(content, enum_values)
            if enum_value is not None:
                parsed[field_name] = enum_value
            else:
                # Pass through raw value for model validator to coerce
                raw_value = _first_nonempty_line(content)
                if raw_value:
                    parsed[field_name] = raw_value
            continue
        if field_schema.get("type") == "string":
            string_value = _extract_string_value(content)
            if string_value is not None:
                parsed[field_name] = string_value
        elif field_schema.get("type") == "array":
            items_type = (field_schema.get("items") or {}).get("type")
            if items_type == "string":
                values = []
                for line in content.splitlines():
                    stripped = line.strip()
                    if not stripped:
                        continue
                    normalized = stripped.lstrip("-* ").strip()
                    if normalized:
                        values.append(normalized)
                if values:
                    parsed[field_name] = values
    return parsed


def _parse_model_from_markdown(text: str, model: Type[T]) -> T | None:
    parsed_data = _parse_markdown_to_data(text, model)
    if not parsed_data:
        return None
    try:
        return model.model_validate(parsed_data)
    except ValidationError:
        return None


def _resolve_enum_values(field_info: dict[str, Any], defs: dict[str, Any]) -> list[str] | None:
    """Resolve enum values from field_info, handling $ref to $defs."""
    # Direct enum values in field_info
    if "enum" in field_info:
        return field_info["enum"]

    # Check $ref to $defs (e.g., {"$ref": "#/$defs/MyEnum"})
    if "$ref" in field_info:
        ref_path = field_info["$ref"]
        if ref_path.startswith("#/$defs/"):
            def_name = ref_path.split("/")[-1]
            if def_name in defs and "enum" in defs[def_name]:
                return defs[def_name]["enum"]

    # Check anyOf for enum reference (e.g., {"anyOf": [{"$ref": "#/$defs/MyEnum"}, ...]})
    if "anyOf" in field_info:
        for option in field_info["anyOf"]:
            if "$ref" in option:
                ref_path = option["$ref"]
                if ref_path.startswith("#/$defs/"):
                    def_name = ref_path.split("/")[-1]
                    if def_name in defs and "enum" in defs[def_name]:
                        return defs[def_name]["enum"]

    return None


def model_to_description(model: Type[BaseModel]) -> str:
    """Build a markdown prompt description for a given model schema."""
    lines = ["Please respond in Markdown format with the following sections."]
    lines.append("Use the descriptions to guide your responses, but do not include the descriptions themselves.")
    lines.append("Format:")
    lines.append("```markdown")

    schema = model.model_json_schema()
    properties = schema.get("properties", {})
    defs = schema.get("$defs", {})

    for field_name, field_info in properties.items():
        field_desc = field_info.get("description", "")
        readable_name = _snake_to_readable(field_name)

        # Resolve enum values (handles both direct enum and $ref to $defs)
        enum_values = _resolve_enum_values(field_info, defs)

        lines.append(f"# {readable_name}")

        if field_desc:
            lines.append(f"{field_desc}")

        if enum_values:
            options_str = ", ".join(f'"{v}"' for v in enum_values)
            lines.append(f"Options: {options_str}")

        lines.append("")

    lines.append("```")

    return "\n".join(lines)


def _extract_model_from_text_llm(
    text: str,
    model: Type[T],
) -> T | None:
    schema = model.model_json_schema()
    prompt = f"""Extract structured data from the following text and return ONLY a valid JSON object
that matches the schema below.

Input Text:
{text}

Target Schema:
{json.dumps(schema, indent=2)}

Instructions:
1. Read the input text carefully
2. Extract the relevant information for each field in the schema
3. Return ONLY a valid JSON object - no additional text, explanations, or markdown formatting
4. The JSON must validate against the provided schema
5. Use null for optional fields if information is not available

Return only the JSON object:"""

    try:
        agent = Agent(model=ModelTier.FAST, tools=ToolGroup.READER)
        traj = agent.completion(prompt)
        full_response = traj.result or ""
        if not full_response:
            return None
        json_match = re.search(r"\{.*\}", full_response, re.DOTALL)
        if not json_match:
            return None

        json_str = json_match.group(0)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return None

        try:
            return model.model_validate(data)
        except ValidationError:
            return None
    except Exception:
        return None


def extract_model_from_text(
    text: str,
    model: Type[T],
    repeat: int = 3,
) -> T | None:
    """Synchronously extract a model instance from text using the LLM helper."""
    parsed_result = _parse_model_from_markdown(text, model)
    if parsed_result is not None:
        return parsed_result
    attempts = max(1, repeat)
    for _ in range(attempts):
        result = _extract_model_from_text_llm(text, model)
        if result is not None:
            return result
    return None


class BaseModelWithHelpers(BaseModel):
    """Extended BaseModel with common serialization helpers."""

    @classmethod
    def from_dict(cls, data: dict) -> BaseModelWithHelpers:
        """Create instance from dictionary."""
        return cls.model_validate(data)

    @classmethod
    def from_json_str(cls, json_str: str) -> BaseModelWithHelpers:
        """Create instance from JSON string."""
        return cls.model_validate_json(json_str)

    @classmethod
    def from_json_file(cls, file_path: str | Path) -> BaseModelWithHelpers:
        """Create instance from JSON file."""
        with open(file_path, "r") as f:
            return cls.model_validate_json(f.read())

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return self.model_dump()

    def to_json_str(self, **kwargs) -> str:
        """Convert to JSON string."""
        kwargs.setdefault("indent", 2)
        return self.model_dump_json(**kwargs)

    def to_json_file(self, file_path: str | Path, **kwargs) -> None:
        """Save to JSON file."""
        kwargs.setdefault("indent", 2)
        with open(file_path, "w") as f:
            f.write(self.model_dump_json(**kwargs))

    def to_markdown(self) -> str:
        """Render the model fields as markdown with headers for each field."""
        sections = []

        for field_name in self.model_fields:
            header = _snake_to_readable(field_name)
            value = getattr(self, field_name)
            rendered_value = self._format_markdown_value(value)
            sections.append(f"## {header}\n{rendered_value}")

        return "\n\n".join(sections).strip()

    @staticmethod
    def _format_markdown_value(value: Any) -> str:
        if value is None:
            return "None"
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            if not value:
                return "[]"
            return "\n".join(f"- {item}" for item in value)
        return str(value)


class LLMGeneratedBaseModel(BaseModelWithHelpers):
    """Base Pydantic model with prompt-generation and extraction helpers."""

    @classmethod
    def to_prompt_description(cls) -> str:
        """Generate the markdown description used when prompting an LLM."""
        return model_to_description(cls)

    @classmethod
    async def extract_from_text_async(
        cls: Type[LLMModelT],
        text: str,
        repeat: int = 3,
    ) -> LLMModelT | None:
        """Async helper that extracts the model from LLM output."""
        parsed_result = _parse_model_from_markdown(text, cls)
        if parsed_result is not None:
            return parsed_result
        attempts = max(1, repeat)
        for _ in range(attempts):
            result = await asyncio.to_thread(_extract_model_from_text_llm, text, cls)
            if result is not None:
                return result
        return None

    @classmethod
    def extract_from_text(
        cls: Type[LLMModelT],
        text: str,
        repeat: int = 3,
    ) -> LLMModelT | None:
        """Blocking helper that extracts the model from LLM output."""
        return extract_model_from_text(text, cls, repeat=repeat)
