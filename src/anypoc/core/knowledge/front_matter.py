"""YAML front matter helpers for knowledge files."""

from __future__ import annotations

from dataclasses import dataclass, field

import yaml


@dataclass
class KnowledgeFrontMatter:
    """
    Front matter embedded in knowledge markdown files.

    Example format:
    ---
    keywords:
      - shader
      - compilation
    times_used: 5
    times_useful: 3
    ---
    # Actual markdown content here...
    """

    keywords: list[str] = field(default_factory=list)
    times_used: int = 0
    times_useful: int = 0

    def to_yaml_block(self) -> str:
        """Convert to YAML front matter block with --- delimiters."""
        data = {
            "keywords": self.keywords,
            "times_used": self.times_used,
            "times_useful": self.times_useful,
        }
        yaml_str = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        return f"---\n{yaml_str}---\n"


def parse_front_matter(content: str) -> tuple[KnowledgeFrontMatter, str]:
    """
    Parse YAML front matter from markdown content.

    Returns:
        Tuple of (front_matter, body_content)
    """
    content = content.strip()
    if not content.startswith("---"):
        # No front matter, return defaults
        return KnowledgeFrontMatter(), content

    # Find the closing ---
    second_delim = content.find("---", 3)
    if second_delim == -1:
        return KnowledgeFrontMatter(), content

    yaml_block = content[3:second_delim].strip()
    body = content[second_delim + 3 :].strip()

    try:
        data = yaml.safe_load(yaml_block) or {}
    except yaml.YAMLError:
        return KnowledgeFrontMatter(), content

    return (
        KnowledgeFrontMatter(
            keywords=data.get("keywords", []) or [],
            times_used=int(data.get("times_used", 0) or 0),
            times_useful=int(data.get("times_useful", 0) or 0),
        ),
        body,
    )


def update_front_matter(content: str, front_matter: KnowledgeFrontMatter) -> str:
    """
    Update or add front matter to markdown content.

    Returns the full content with updated front matter.
    """
    _, body = parse_front_matter(content)
    return front_matter.to_yaml_block() + "\n" + body
