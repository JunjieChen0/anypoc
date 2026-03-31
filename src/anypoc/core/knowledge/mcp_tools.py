"""ToolKit classes for knowledge extraction and rating."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING

from caw import ToolKit, tool

from anypoc.core.trajectory_compress import get_trajectory_turns
from anypoc.utils import logger

from .filters import _filter_knowledge_entry
from .front_matter import KnowledgeFrontMatter, parse_front_matter, update_front_matter

if TYPE_CHECKING:
    from .manager import KnowledgeManager

LOG_PREFIX = "[KnowledgeManager]"


# =============================================================================
# Knowledge Extraction ToolKit
# =============================================================================


class KnowledgeExtractionToolKit(ToolKit, server_name="knowledge_extractor", display_name="Knowledge Extractor"):
    """ToolKit for knowledge extraction agent — add/update/inspect knowledge."""

    def __init__(
        self,
        manager: "KnowledgeManager",
        generation_dir: Path,
        was_successful: bool,
        trajectory: dict[str, Any],
        bug_report_path: str | None,
        bug_report_content: str | None,
        filter_trajs_dir: Path | None = None,
    ):
        self.manager = manager
        self.generation_dir = generation_dir
        self.was_successful = was_successful
        self.trajectory = trajectory
        self.bug_report_path = bug_report_path
        self.bug_report_content = bug_report_content
        self.filter_trajs_dir = filter_trajs_dir
        self.reported_ids: list[str] = []
        self.updated_ids: list[str] = []
        self.ratings: list[tuple[str, float]] = []

    @tool(
        name="report_new_knowledge",
        description=(
            "Submit a new knowledge entry.\n\n"
            "Parameters:\n"
            "- path: Category path like 'build/shader_flags.md' or 'command_line_tools/gdb_basics.md'\n"
            "- content: Plain markdown content (no YAML front matter needed)\n"
            "- keywords: List of keywords for search/discovery\n\n"
            "Strict category enforcement - path must start with one of:\n"
            "Shared: command_line_tools (general CLI tools, NOT project-specific), "
            "language_specific (general language pitfalls, NOT project APIs)\n"
            "Per-project: build (compilation/flags), internal_tools (project's own tools, NOT general CLI), "
            "test_frameworks (testing approaches, NOT PoC formats), "
            "code (general code facts/invariants, NOT bug-specific root causes), "
            "poc_forms (PoC formats and what user capabilities they represent, NOT bug patterns)\n"
            "Project categories are auto-prefixed with the project name."
        ),
    )
    async def report_new_knowledge(self, path: str, content: str, keywords: list[str]) -> str:
        manager = self.manager

        # Normalize path
        path = path.strip().strip("/")
        if not path:
            return "Invalid path: empty"

        # Ensure .md extension
        if not path.endswith(".md"):
            path = path + ".md"

        # Strip any existing front matter the agent may have included
        _, body = parse_front_matter(content)

        # Filter bug-specific knowledge for category-specific rules (code/, poc_forms/)
        try:
            filter_result = _filter_knowledge_entry(
                path=path,
                content=body,
                keywords=keywords,
                bug_report_path=self.bug_report_path,
                bug_report_content=self.bug_report_content,
                project_name=manager.project_name,
                filter_trajs_dir=self.filter_trajs_dir,
            )
            if filter_result is not None and filter_result.get("decision") == "block":
                summary = filter_result.get("summary") or "Not saved: knowledge too bug-specific."
                return summary
        except Exception as exc:
            logger.error(f"{LOG_PREFIX} Knowledge filter error; blocking entry: {exc}")
            return f"Filter error — entry not saved. Details: {exc}"

        # Inject front matter from keywords
        front_matter = KnowledgeFrontMatter(keywords=keywords, times_used=0, times_useful=0)
        content = update_front_matter(body, front_matter)

        # Create knowledge entry
        try:
            result = await manager.add_knowledge(
                path=path,
                content=content,
                source_generation=str(self.generation_dir),
                was_successful=self.was_successful,
            )
            if result:
                self.reported_ids.append(result)
                return f"Knowledge saved: {result}"
            return "Failed to save knowledge"
        except Exception as e:
            logger.error(f"{LOG_PREFIX} Error saving knowledge: {e}")
            return f"Error: {e}"

    @tool(
        name="update_knowledge",
        description=(
            "Update an existing knowledge entry by its file path (relative to content/).\n"
            "Provide:\n"
            "- file_path: Relative path like 'build/gfx/my_knowledge.md'\n"
            "- content: New markdown content\n"
            "- keywords: Updated keywords (optional, pass null to keep existing)\n"
        ),
    )
    async def update_knowledge(self, file_path: str, content: str, keywords: list[str] | None = None) -> str:
        manager = self.manager

        # Filter bug-specific knowledge for category-specific rules (code/, poc_forms/)
        try:
            _, body = parse_front_matter(content)
            existing = manager.get_metadata(file_path)
            filter_keywords = keywords if keywords is not None else (existing.keywords if existing else [])
            filter_result = _filter_knowledge_entry(
                path=file_path,
                content=body,
                keywords=filter_keywords,
                bug_report_path=self.bug_report_path,
                bug_report_content=self.bug_report_content,
                project_name=manager.project_name,
                filter_trajs_dir=self.filter_trajs_dir,
            )
            if filter_result is not None and filter_result.get("decision") == "block":
                summary = filter_result.get("summary") or "Not saved: knowledge too bug-specific."
                return summary
        except Exception as exc:
            logger.error(f"{LOG_PREFIX} Knowledge filter error; blocking entry: {exc}")
            return f"Filter error — entry not saved. Details: {exc}"

        try:
            result = await manager.update_knowledge(
                file_path=file_path,
                content=content,
                keywords=keywords,
                source_generation=str(self.generation_dir),
                was_successful=self.was_successful,
            )
            if result:
                self.updated_ids.append(file_path)
                return f"Knowledge updated: {file_path}"
            return f"Knowledge not found: {file_path}"
        except Exception as e:
            logger.error(f"{LOG_PREFIX} Error updating knowledge: {e}")
            return f"Error: {e}"

    @tool(
        name="rate_knowledge",
        description=(
            "Rate a knowledge entry by its file path.\n"
            "Score from -10 (actively misleading) to 10 (directly helped solve the task).\n"
            "- 10: directly helped solve/advance the run\n"
            "- 0: irrelevant / provided no benefit\n"
            "- -10: actively misleading / wasted time"
        ),
    )
    async def rate_knowledge(self, file_path: str, score: float) -> str:
        manager = self.manager

        if score < -10 or score > 10:
            return "Score must be between -10 and 10"

        try:
            result = await manager.rate_knowledge(file_path, score)
            if result:
                self.ratings.append((file_path, score))
                return f"Rated {file_path}: {score}"
            return f"Knowledge not found: {file_path}"
        except Exception as e:
            logger.error(f"{LOG_PREFIX} Error rating knowledge: {e}")
            return f"Error: {e}"

    @tool(
        name="get_knowledge_metadata",
        description="Get metadata about a knowledge entry including ratings, sources, and version info.",
    )
    def get_knowledge_metadata(self, file_path: str) -> str:
        manager = self.manager

        metadata = manager.get_metadata(file_path)
        if metadata is None:
            return f"Knowledge not found: {file_path}"

        avg_rating = metadata.get_average_rating()
        success_ratio = metadata.get_success_ratio()

        return json.dumps(
            {
                "file_path": file_path,
                "knowledge_type": metadata.knowledge_type.value,
                "keywords": metadata.keywords,
                "version": metadata.version,
                "average_rating": round(avg_rating, 2) if avg_rating else None,
                "total_ratings": sum(len(r) for r in metadata.usefulness_ratings),
                "iterations_survived": metadata.iterations_survived,
                "source_count": len(metadata.source_generations),
                "success_ratio": round(success_ratio, 2) if success_ratio else None,
                "created_at": metadata.created_at,
                "updated_at": metadata.updated_at,
            },
            indent=2,
        )

    @tool(
        name="get_trajectory_turns",
        description=(
            "Get full details for specific turns in the PoC generation trajectory.\n\n"
            "The compressed trajectory skeleton shows each turn as a single line:\n"
            "  [N] tool: {input...} -> status (size)\n\n"
            "Use this tool to retrieve the complete content for turns you want to examine.\n"
            "Pass a list of turn indices (e.g., [5, 6, 7]) to see full input/output.\n\n"
            "Example usage:\n"
            "- To see what a Bash command did: get_trajectory_turns([8])\n"
            "- To see a sequence of actions: get_trajectory_turns([3, 4, 5, 6])"
        ),
    )
    def get_trajectory_turns(self, indices: list[int]) -> str:
        if not self.trajectory:
            return "Error: No trajectory loaded in current session."
        return get_trajectory_turns(self.trajectory, indices)


# =============================================================================
# Knowledge Query ToolKit (for PoC generation runtime)
# =============================================================================


class KnowledgeQueryToolKit(ToolKit, server_name="knowledge_rating", display_name="Knowledge Rating"):
    """ToolKit for rating knowledge during PoC generation."""

    def __init__(
        self,
        manager: "KnowledgeManager",
        summary_dir: Path | None = None,
        generation_dir: Path | None = None,
    ):
        self.manager = manager
        self.summary_dir = summary_dir
        self.generation_dir = generation_dir
        self.ratings: list[dict[str, Any]] = []

    @tool(
        name="rate_knowledge",
        description=(
            "Rate how useful a knowledge entry was for your current task.\n"
            "Provide the file path relative to the knowledge content/ directory.\n"
            "Score from -10 (actively misleading) to 10 (directly helped).\n\n"
            "Call this after you use any knowledge from the knowledge base."
        ),
    )
    async def rate_knowledge(self, file_path: str, score: float) -> str:
        manager = self.manager

        if score < -10 or score > 10:
            return "Score must be between -10 and 10"

        result = await manager.rate_knowledge(file_path, score)
        if result:
            self.ratings.append(
                {
                    "file_path": file_path,
                    "score": score,
                    "timestamp": datetime.now().isoformat(),
                }
            )
            return f"Rated {file_path}: {score}"
        return f"Knowledge not found: {file_path}"
