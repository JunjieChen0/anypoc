"""
Knowledge Manager - Manages a centralized hierarchical knowledge base for PoC generation.

The knowledge base is organized as:
    output/knowledge/
    |-- content/
    |   |-- command_line_tools/           # Shared: General CLI tools
    |   |-- language_specific/            # Shared: Language knowledge
    |   |   |-- c/
    |   |   |-- cpp/
    |   |   `-- rust/
    |   |-- {project_name}/               # Per-project (one per project)
    |   |   |-- build/
    |   |   |-- internal_tools/
    |   |   |-- test_frameworks/
    |   |   |-- code/
    |   |   `-- poc_forms/                # PoC formats and user capabilities (not bug patterns)
    |   `-- ...
    |-- metadata/                          # Mirrors content/ structure
    |-- archive/
    |   |-- content/
    |   `-- metadata/
    `-- trajs/                             # Extractor trajectories
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from caw import Agent, ToolGroup

from anypoc.core.trajectory_compress import get_trajectory_summary, render_compressed_trajectory
from anypoc.types import KnowledgeType
from anypoc.utils import logger

from .constants import LANGUAGE_SUBDIRS, PROJECT_CATEGORIES, SHARED_CATEGORIES
from .extraction import (
    KnowledgeExtractionSummary,
    _build_extraction_prompt,
    _build_extractor_system_prompt,
    _load_bug_report_for_generation,
)
from .front_matter import parse_front_matter, update_front_matter
from .mcp_tools import KnowledgeExtractionToolKit, KnowledgeQueryToolKit
from .metadata import KnowledgeFileMetadata
from .tracking import _dedupe_ratings, _normalize_ratings

LOG_PREFIX = "[KnowledgeManager]"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON to disk atomically to avoid partial writes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(path)


class KnowledgeManager:
    """
    Manages a hierarchical knowledge base for PoC generation.

    The knowledge base separates content (markdown files) from metadata (JSON files),
    allowing agents to freely explore content while metadata is managed by the system.
    """

    def __init__(self, knowledge_dir: str | Path, project_name: str | None = None):
        """
        Initialize the knowledge manager.

        Args:
            knowledge_dir: Root directory for the knowledge base
            project_name: Name of the current project (enables project-scoped categories)
        """
        self.knowledge_dir = Path(knowledge_dir).resolve()
        self.project_name = project_name
        self.content_dir = self.knowledge_dir / "content"
        self.metadata_dir = self.knowledge_dir / "metadata"
        self.archive_dir = self.knowledge_dir / "archive"
        self.archive_content_dir = self.archive_dir / "content"
        self.archive_metadata_dir = self.archive_dir / "metadata"

        # Ensure directories exist
        self._ensure_directories()

        # Load metadata index (rebuilt on each init)
        self._metadata_cache: dict[str, KnowledgeFileMetadata] = {}
        self._rebuild_metadata_index()

    def _ensure_directories(self) -> None:
        """Create necessary directories including predefined categories."""
        self.content_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self.archive_content_dir.mkdir(parents=True, exist_ok=True)
        self.archive_metadata_dir.mkdir(parents=True, exist_ok=True)

        # Shared categories
        for category in SHARED_CATEGORIES:
            (self.content_dir / category).mkdir(exist_ok=True)
            (self.metadata_dir / category).mkdir(exist_ok=True)

        # Language subdirectories under language_specific/
        for lang in LANGUAGE_SUBDIRS:
            (self.content_dir / "language_specific" / lang).mkdir(exist_ok=True)
            (self.metadata_dir / "language_specific" / lang).mkdir(exist_ok=True)

        # Per-project categories
        if self.project_name:
            for category in PROJECT_CATEGORIES:
                (self.content_dir / self.project_name / category).mkdir(parents=True, exist_ok=True)
                (self.metadata_dir / self.project_name / category).mkdir(parents=True, exist_ok=True)

    def _rebuild_metadata_index(self) -> None:
        """Rebuild the in-memory metadata index from disk."""
        self._metadata_cache.clear()

        for json_path in self.metadata_dir.rglob("*.json"):
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                metadata = KnowledgeFileMetadata.model_validate(data)
                self._metadata_cache[metadata.file_path] = metadata
            except Exception as e:
                logger.warn(f"{LOG_PREFIX} Failed to load metadata {json_path}: {e}")

    def _validate_and_resolve_path(self, path: str) -> tuple[str | None, str | None]:
        """Validate and resolve a knowledge path.

        Returns (resolved_path, error_message). One will be None.
        """
        parts = path.strip("/").split("/")
        top = parts[0]

        if top in SHARED_CATEGORIES:
            return path, None

        if top in PROJECT_CATEGORIES:
            if not self.project_name:
                return None, "Cannot create project-scoped knowledge without project context"
            return f"{self.project_name}/{path}", None

        # Already prefixed with project name?
        if self.project_name and top == self.project_name and len(parts) > 1:
            if parts[1] in PROJECT_CATEGORIES:
                return path, None

        valid = list(SHARED_CATEGORIES) + list(PROJECT_CATEGORIES)
        return None, f"Path must start with a valid category: {', '.join(valid)}"

    def reload(self) -> None:
        """Reload the metadata cache from disk.

        Call this after external processes (e.g., container execution) may have
        modified the knowledge base files to sync the in-memory cache with disk.
        """
        self._rebuild_metadata_index()
        logger.info(f"{LOG_PREFIX} Reloaded metadata cache ({len(self._metadata_cache)} entries)")

    def _get_metadata_path(self, content_path: str) -> Path:
        """Get the metadata JSON path for a content file path."""
        # content_path is relative, e.g., "build/gfx/my_knowledge.md"
        # metadata path is "metadata/build/gfx/my_knowledge.json"
        if content_path.endswith(".md"):
            json_name = content_path[:-3] + ".json"
        else:
            json_name = content_path + ".json"
        return self.metadata_dir / json_name

    def _get_content_path(self, file_path: str) -> Path:
        """Get the absolute content file path."""
        return self.content_dir / file_path

    # -------------------------------------------------------------------------
    # Public API: Add/Update/Rate Knowledge
    # -------------------------------------------------------------------------

    async def add_knowledge(
        self,
        path: str,
        content: str,
        source_generation: str | None = None,
        was_successful: bool = False,
    ) -> str | None:
        """
        Add a new knowledge entry.

        Args:
            path: Relative path like 'build/gfx/shader_flags.md'
            content: Markdown content with YAML front matter containing keywords

        Returns the file path if successful, None otherwise.
        """
        # Normalize path
        file_path = path.strip().strip("/")
        if not file_path.endswith(".md"):
            file_path = file_path + ".md"

        # Validate and resolve path (strips .md for validation, re-adds after)
        path_without_ext = file_path[:-3] if file_path.endswith(".md") else file_path
        resolved, error = self._validate_and_resolve_path(path_without_ext)
        if error is not None or resolved is None:
            logger.warn(f"{LOG_PREFIX} Invalid path '{file_path}': {error}")
            return None
        resolved_path: str = resolved
        file_path = resolved_path + ".md" if not resolved_path.endswith(".md") else resolved_path

        # Check if already exists
        if file_path in self._metadata_cache:
            logger.warn(f"{LOG_PREFIX} Knowledge already exists: {file_path}")
            return None

        # Parse front matter to extract keywords
        front_matter, _ = parse_front_matter(content)

        # Extract category path from file path
        parts = file_path.rsplit("/", 1)
        rel_dir = parts[0]
        category_path = rel_dir.split("/")

        # Ensure directories exist
        content_full_dir = self.content_dir / rel_dir
        metadata_full_dir = self.metadata_dir / rel_dir
        content_full_dir.mkdir(parents=True, exist_ok=True)
        metadata_full_dir.mkdir(parents=True, exist_ok=True)

        # Generate unique ID (path without .md)
        knowledge_id = file_path[:-3] if file_path.endswith(".md") else file_path

        # Create metadata
        now = datetime.now().isoformat()
        metadata = KnowledgeFileMetadata(
            knowledge_id=knowledge_id,
            file_path=file_path,
            category_path=category_path,
            knowledge_type=KnowledgeType.OTHER,
            keywords=front_matter.keywords,
            created_at=now,
            updated_at=now,
        )

        if source_generation:
            metadata.add_source(source_generation, was_successful)

        # Write content file
        content_path = self._get_content_path(file_path)
        content_path.write_text(content, encoding="utf-8")

        # Write metadata file
        metadata_path = self._get_metadata_path(file_path)
        metadata_path.write_text(metadata.model_dump_json(indent=2), encoding="utf-8")

        # Update cache
        self._metadata_cache[file_path] = metadata

        logger.info(f"{LOG_PREFIX} Added knowledge: {file_path}")
        return file_path

    async def update_knowledge(
        self,
        file_path: str,
        content: str,
        keywords: list[str] | None = None,
        source_generation: str | None = None,
        was_successful: bool = False,
    ) -> bool:
        """
        Update an existing knowledge entry.

        Returns True if successful, False if not found.
        """
        metadata = self._metadata_cache.get(file_path)
        if metadata is None:
            return False

        # Update content
        content_path = self._get_content_path(file_path)
        content_path.write_text(content, encoding="utf-8")

        # Update metadata
        metadata.bump_version()
        if keywords is not None:
            metadata.keywords = keywords
        if source_generation:
            metadata.add_source(source_generation, was_successful)

        # Write metadata
        metadata_path = self._get_metadata_path(file_path)
        metadata_path.write_text(metadata.model_dump_json(indent=2), encoding="utf-8")

        logger.info(f"{LOG_PREFIX} Updated knowledge: {file_path} (v{metadata.version})")
        return True

    async def rate_knowledge(self, file_path: str, score: float) -> bool:
        """
        Rate a knowledge entry.

        Updates both the JSON metadata and the markdown front matter:
        - times_used: incremented by 1
        - times_useful: incremented by 1 if score > 0

        Returns True if successful, False if not found.
        """
        metadata = self._metadata_cache.get(file_path)
        if metadata is None:
            return False

        metadata.add_rating(score)

        # Write metadata JSON
        metadata_path = self._get_metadata_path(file_path)
        metadata_path.write_text(metadata.model_dump_json(indent=2), encoding="utf-8")

        # Update markdown front matter
        content_path = self._get_content_path(file_path)
        if content_path.exists():
            content = content_path.read_text(encoding="utf-8")
            front_matter, _ = parse_front_matter(content)
            front_matter.times_used += 1
            if score > 0:
                front_matter.times_useful += 1
            updated_content = update_front_matter(content, front_matter)
            content_path.write_text(updated_content, encoding="utf-8")

        logger.info(f"{LOG_PREFIX} Rated knowledge: {file_path} = {score}")
        return True

    # -------------------------------------------------------------------------
    # Public API: Query Knowledge
    # -------------------------------------------------------------------------

    def get_metadata(self, file_path: str) -> KnowledgeFileMetadata | None:
        """Get metadata for a knowledge entry."""
        return self._metadata_cache.get(file_path)

    def get_content(self, file_path: str) -> str | None:
        """Get the markdown content of a knowledge entry."""
        content_path = self._get_content_path(file_path)
        if not content_path.exists():
            return None
        return content_path.read_text(encoding="utf-8")

    def get_all_metadata(self) -> list[KnowledgeFileMetadata]:
        """Get all metadata entries."""
        return list(self._metadata_cache.values())

    def search_by_keywords(
        self,
        keywords: list[str],
        category_prefix: list[str] | None = None,
        limit: int = 10,
    ) -> list[KnowledgeFileMetadata]:
        """
        Search knowledge by keywords.

        Returns metadata entries sorted by relevance (keyword match count).
        """
        keywords_lower = [k.lower() for k in keywords]
        results: list[tuple[int, KnowledgeFileMetadata]] = []

        for metadata in self._metadata_cache.values():
            # Filter by category prefix
            if category_prefix:
                if len(metadata.category_path) < len(category_prefix):
                    continue
                if metadata.category_path[: len(category_prefix)] != category_prefix:
                    continue

            # Score by keyword matches
            entry_keywords_lower = [k.lower() for k in metadata.keywords]
            score = sum(1 for k in keywords_lower if any(k in ek for ek in entry_keywords_lower))

            if score > 0:
                results.append((score, metadata))

        # Sort by score descending
        results.sort(key=lambda x: -x[0])
        return [m for _, m in results[:limit]]

    def get_knowledge_tree(self, category_prefix: list[str] | None = None) -> dict[str, Any]:
        """
        Get the knowledge tree structure.

        Returns a nested dict representing the directory structure with file lists.
        """
        tree: dict[str, Any] = {}

        for metadata in self._metadata_cache.values():
            # Filter by category prefix
            if category_prefix:
                if len(metadata.category_path) < len(category_prefix):
                    continue
                if metadata.category_path[: len(category_prefix)] != category_prefix:
                    continue

            # Build tree path
            current = tree
            for part in metadata.category_path:
                if part not in current:
                    current[part] = {}
                current = current[part]

            # Add file entry
            filename = Path(metadata.file_path).name
            if "_files" not in current:
                current["_files"] = []
            avg_rating = metadata.get_average_rating()
            current["_files"].append(
                {
                    "name": filename,
                    "path": metadata.file_path,
                    "type": metadata.knowledge_type.value,
                    "avg_rating": round(avg_rating, 2) if avg_rating is not None else None,
                }
            )

        return tree

    # -------------------------------------------------------------------------
    # Public API: Index/Prompt Generation
    # -------------------------------------------------------------------------

    def generate_index_prompt(
        self,
        include_rating_instructions: bool = True,
    ) -> str:
        """
        Generate a prompt describing the current knowledge base.

        This prompt can be included in the PoC generation prompt to inform
        the agent about available knowledge.

        Args:
            include_rating_instructions: Whether to include instructions about rating knowledge.
                Set to False when the rating tool is not available (e.g., during extraction).
        """
        lines = [
            "# Available Knowledge Base",
            "",
            f"Knowledge directory: `{self.content_dir}`",
            "",
            "The index below is a **compact preview** — only top-rated entries and top-10 keywords are shown per category.",
            "Use bash and search tools to explore the full directory and find additional entries.",
            "Each markdown file has YAML front matter with keywords, times_used, and times_useful.",
            "",
        ]

        if include_rating_instructions:
            lines.extend(
                [
                    "**Important**: After using any knowledge, call `rate_knowledge` with the file path",
                    "and a score from -10 (misleading) to 10 (directly helped).",
                    "",
                ]
            )

        lines.extend(
            [
                "## Enforced Category Structure",
                "",
                "Shared knowledge (all projects):",
                "- `command_line_tools/` - General CLI tools (gdb, valgrind, etc.). NOT project-specific tools.",
                "- `language_specific/` - Language knowledge (`c/`, `cpp/`, `rust/`). General pitfalls, NOT project APIs.",
                "",
            ]
        )
        if self.project_name:
            lines.extend(
                [
                    f"Project-specific knowledge (`{self.project_name}/`):",
                    f"- `{self.project_name}/build/` - Build system, compilation, flags. How to compile the project.",
                    f"- `{self.project_name}/internal_tools/` - Project's specific tools. NOT general CLI tools.",
                    f"- `{self.project_name}/test_frameworks/` - Testing approaches. NOT PoC formats (use poc_forms/).",
                    f"- `{self.project_name}/code/` - General code facts/invariants. NOT bug-specific root causes or crash logs.",
                    f"- `{self.project_name}/poc_forms/` - PoC formats and what user capabilities they represent. NOT bug patterns.",
                    "",
                ]
            )

        # Separate entries into shared vs project
        shared_entries: dict[str, list[KnowledgeFileMetadata]] = {}
        project_entries: dict[str, list[KnowledgeFileMetadata]] = {}

        for metadata in self._metadata_cache.values():
            if not metadata.category_path:
                continue
            top = metadata.category_path[0]
            if top in SHARED_CATEGORIES:
                shared_entries.setdefault(top, []).append(metadata)
            elif self.project_name and top == self.project_name and len(metadata.category_path) > 1:
                sub = metadata.category_path[1]
                project_entries.setdefault(sub, []).append(metadata)
            else:
                # Entries from other projects — skip them, not relevant
                pass

        def _render_category_entries(heading: str, by_cat: dict[str, list[KnowledgeFileMetadata]]) -> None:
            if not by_cat:
                return
            lines.append(f"## {heading}")
            lines.append("")
            for cat_name in sorted(by_cat.keys()):
                entries = by_cat[cat_name]
                lines.append(f"### {cat_name}/ ({len(entries)} entries)")
                # Top 10 keywords by frequency across all entries
                kw_counter: Counter[str] = Counter()
                for m in entries:
                    kw_counter.update(m.keywords)
                top_kw = [kw for kw, _ in kw_counter.most_common(10)]
                if top_kw:
                    lines.append(f"Top keywords: {', '.join(top_kw)}")
                # Show top-rated entries: 1 per category, up to 5 for poc_forms
                max_show = 5 if cat_name == "poc_forms" else 2
                sorted_entries = sorted(
                    entries,
                    key=lambda m: (-(m.get_average_rating() or 0), m.file_path),
                )
                for metadata in sorted_entries[:max_show]:
                    avg = metadata.get_average_rating()
                    rating_str = f" [rating: {avg:.1f}]" if avg else ""
                    lines.append(f"- `{metadata.file_path}`{rating_str}")
                lines.append("")

        _render_category_entries("Shared Knowledge (all projects)", shared_entries)
        if self.project_name:
            _render_category_entries(f"Project Knowledge ({self.project_name})", project_entries)

        if not shared_entries and not project_entries:
            lines.append("(Knowledge base is empty)")

        return "\n".join(lines)

    def generate_agent_knowledge_section(self) -> str:
        """Generate the knowledge base section for a PoC generation agent spec.

        Returns a markdown section describing how to use the knowledge base,
        including category structure and MCP tool instructions.
        Returns empty string if no project context is set.
        """
        project_label = ""
        if self.project_name:
            pn = self.project_name
            project_label = (
                f"\nProject-specific knowledge ({pn}/):\n"
                f"- {pn}/build/              - Build system, compilation, flags. How to compile the project.\n"
                f"- {pn}/internal_tools/     - Project's specific tools. NOT general CLI tools.\n"
                f"- {pn}/test_frameworks/    - Testing approaches. NOT PoC formats (use poc_forms/).\n"
                f"- {pn}/code/               - General code facts/invariants. NOT bug-specific root causes.\n"
                f"- {pn}/poc_forms/          - PoC formats and what user capabilities they represent. NOT bug patterns.\n"
            )

        return (
            f"\n## Knowledge Base\n\n"
            f"A knowledge base is available at: {self.content_dir}\n\n"
            f"This directory contains markdown files in a two-tier structure:\n\n"
            f"Shared knowledge (all projects):\n"
            f"- command_line_tools/   - General CLI tools (gdb, valgrind, etc.). NOT project-specific tools.\n"
            f"- language_specific/    - Language knowledge (c/, cpp/, rust/). General pitfalls, NOT project APIs.\n"
            f"{project_label}\n"
            f"**How to use:**\n"
            f"1. Before starting, review the knowledge index (provided in the task prompt) to identify useful entries\n"
            f"2. Read relevant knowledge files directly using the Read tool (browse the content directory)\n"
            f"3. **MANDATORY**: After reading the FULL content of any knowledge file, you MUST rate it\n"
            f"   using the `rate_knowledge` MCP tool\n\n"
            f"**Rating scale (-10 to 10):**\n"
            f"- 10: directly helped solve/advance your task\n"
            f"- 0: irrelevant or provided no benefit\n"
            f"- -10: actively misleading or wasted time\n"
        )

    # -------------------------------------------------------------------------
    # Public API: Evolve (Cleanup)
    # -------------------------------------------------------------------------

    async def evolve(
        self,
        min_rating_threshold: float = -2.0,
        min_iterations_to_evaluate: int = 3,
    ) -> dict[str, Any]:
        """
        Clean up poorly-rated knowledge by archiving it.

        Archived knowledge is moved to the archive/ directory, preserving
        the directory structure. This allows for later review or restoration.

        Args:
            min_rating_threshold: Archive entries with average rating below this
            min_iterations_to_evaluate: Only evaluate entries with at least this many ratings

        Returns:
            Summary of evolution actions taken
        """
        archived: list[str] = []
        kept: list[str] = []
        skipped: list[str] = []

        for file_path, metadata in list(self._metadata_cache.items()):
            total_ratings = sum(len(r) for r in metadata.usefulness_ratings)

            if total_ratings < min_iterations_to_evaluate:
                skipped.append(file_path)
                continue

            avg_rating = metadata.get_average_rating()
            if avg_rating is not None and avg_rating < min_rating_threshold:
                # Archive this knowledge (move to archive directory)
                self._archive_knowledge(file_path, metadata)
                del self._metadata_cache[file_path]
                archived.append(file_path)
                logger.info(f"{LOG_PREFIX} Archived low-rated knowledge: {file_path} (avg: {avg_rating:.2f})")
            else:
                kept.append(file_path)

        # Clean up empty directories in active knowledge
        self._cleanup_empty_dirs()

        return {
            "archived": archived,
            "kept": kept,
            "skipped": skipped,
            "total_remaining": len(self._metadata_cache),
        }

    def _archive_knowledge(self, file_path: str, metadata: KnowledgeFileMetadata) -> None:
        """Move a knowledge entry to the archive directory."""
        # Source paths
        content_path = self._get_content_path(file_path)
        metadata_path = self._get_metadata_path(file_path)

        # Destination paths (same relative structure in archive)
        archive_content_path = self.archive_content_dir / file_path
        if file_path.endswith(".md"):
            archive_metadata_path = self.archive_metadata_dir / (file_path[:-3] + ".json")
        else:
            archive_metadata_path = self.archive_metadata_dir / (file_path + ".json")

        # Ensure destination directories exist
        archive_content_path.parent.mkdir(parents=True, exist_ok=True)
        archive_metadata_path.parent.mkdir(parents=True, exist_ok=True)

        # Add archive timestamp to metadata
        metadata.updated_at = datetime.now().isoformat()

        # Move content file
        if content_path.exists():
            # If archive already has this file, append timestamp to avoid overwrite
            if archive_content_path.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                stem = archive_content_path.stem
                suffix = archive_content_path.suffix
                archive_content_path = archive_content_path.with_name(f"{stem}_{timestamp}{suffix}")
            content_path.rename(archive_content_path)

        # Move/write metadata file
        if archive_metadata_path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            stem = archive_metadata_path.stem
            archive_metadata_path = archive_metadata_path.with_name(f"{stem}_{timestamp}.json")
        archive_metadata_path.write_text(metadata.model_dump_json(indent=2), encoding="utf-8")

        # Remove original metadata file
        if metadata_path.exists():
            metadata_path.unlink()

    def _cleanup_empty_dirs(self) -> None:
        """Remove empty directories in content and metadata."""
        # Build set of protected directory relative paths
        protected: set[str] = set()
        for cat in SHARED_CATEGORIES:
            protected.add(cat)
        for lang in LANGUAGE_SUBDIRS:
            protected.add(f"language_specific/{lang}")
        if self.project_name:
            protected.add(self.project_name)
            for cat in PROJECT_CATEGORIES:
                protected.add(f"{self.project_name}/{cat}")

        for base_dir in [self.content_dir, self.metadata_dir]:
            for dirpath in sorted(base_dir.rglob("*"), reverse=True):
                if dirpath.is_dir() and not any(dirpath.iterdir()):
                    rel_path = dirpath.relative_to(base_dir)
                    if str(rel_path) not in protected:
                        dirpath.rmdir()

    def list_archived_knowledge(self) -> list[dict[str, Any]]:
        """List all archived knowledge entries with their metadata."""
        archived: list[dict[str, Any]] = []

        for json_path in self.archive_metadata_dir.rglob("*.json"):
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                metadata = KnowledgeFileMetadata.model_validate(data)
                avg_rating = metadata.get_average_rating()
                archived.append(
                    {
                        "file_path": metadata.file_path,
                        "archive_metadata_path": str(json_path.relative_to(self.archive_dir)),
                        "knowledge_type": metadata.knowledge_type.value,
                        "keywords": metadata.keywords,
                        "average_rating": round(avg_rating, 2) if avg_rating is not None else None,
                        "updated_at": metadata.updated_at,
                    }
                )
            except Exception as e:
                logger.warn(f"{LOG_PREFIX} Failed to load archived metadata {json_path}: {e}")

        return archived

    async def restore_from_archive(self, archive_content_path: str) -> bool:
        """
        Restore a knowledge entry from the archive.

        Args:
            archive_content_path: Relative path within archive/content/

        Returns:
            True if restored successfully, False otherwise
        """
        source_content = self.archive_content_dir / archive_content_path
        if not source_content.exists():
            logger.warn(f"{LOG_PREFIX} Archive content not found: {archive_content_path}")
            return False

        # Find corresponding metadata
        if archive_content_path.endswith(".md"):
            metadata_name = archive_content_path[:-3] + ".json"
        else:
            metadata_name = archive_content_path + ".json"
        source_metadata = self.archive_metadata_dir / metadata_name

        if not source_metadata.exists():
            logger.warn(f"{LOG_PREFIX} Archive metadata not found: {metadata_name}")
            return False

        try:
            data = json.loads(source_metadata.read_text(encoding="utf-8"))
            metadata = KnowledgeFileMetadata.model_validate(data)
        except Exception as e:
            logger.warn(f"{LOG_PREFIX} Failed to load archive metadata: {e}")
            return False

        # Restore to original location
        dest_content = self._get_content_path(metadata.file_path)
        dest_metadata = self._get_metadata_path(metadata.file_path)

        # Check if already exists in active knowledge
        if metadata.file_path in self._metadata_cache:
            logger.warn(f"{LOG_PREFIX} Knowledge already exists: {metadata.file_path}")
            return False

        # Ensure directories exist
        dest_content.parent.mkdir(parents=True, exist_ok=True)
        dest_metadata.parent.mkdir(parents=True, exist_ok=True)

        # Move files back
        source_content.rename(dest_content)
        metadata.updated_at = datetime.now().isoformat()
        dest_metadata.write_text(metadata.model_dump_json(indent=2), encoding="utf-8")
        source_metadata.unlink()

        # Update cache
        self._metadata_cache[metadata.file_path] = metadata

        logger.info(f"{LOG_PREFIX} Restored knowledge from archive: {metadata.file_path}")
        return True

    # -------------------------------------------------------------------------
    # Public API: MCP Server Integration
    # -------------------------------------------------------------------------

    def create_extraction_toolkit(
        self,
        generation_dir: Path,
        was_successful: bool,
        trajectory: dict[str, Any] | None = None,
        filter_trajs_dir: Path | None = None,
    ) -> KnowledgeExtractionToolKit:
        """
        Create a ToolKit for knowledge extraction.

        This provides tools for the extraction agent to add/update/rate knowledge,
        and to retrieve full details from specific trajectory turns.

        Args:
            generation_dir: Path to the generation directory
            was_successful: Whether the generation was successful
            trajectory: The loaded trajectory dict (for get_trajectory_turns tool)
            filter_trajs_dir: Directory for filter agent trajectories
        """
        bug_report_path, bug_report_content = _load_bug_report_for_generation(generation_dir)
        return KnowledgeExtractionToolKit(
            manager=self,
            generation_dir=generation_dir,
            was_successful=was_successful,
            trajectory=trajectory or {},
            bug_report_path=bug_report_path,
            bug_report_content=bug_report_content,
            filter_trajs_dir=filter_trajs_dir,
        )

    def create_query_toolkit(
        self,
        summary_dir: Path | None = None,
        generation_dir: Path | None = None,
    ) -> KnowledgeQueryToolKit:
        """
        Create a ToolKit for rating knowledge during PoC generation.

        The agent should explore the knowledge directory directly using
        standard tools (Read, Glob, Grep). This toolkit only provides
        the rating tool to track knowledge usefulness.
        """
        return KnowledgeQueryToolKit(
            manager=self,
            summary_dir=summary_dir,
            generation_dir=generation_dir,
        )

    def write_usage_summary(self, toolkit: KnowledgeQueryToolKit) -> Path | None:
        """Persist knowledge usage summary for a generation run."""
        summary_dir = toolkit.summary_dir
        if summary_dir is None and toolkit.generation_dir is not None:
            summary_dir = toolkit.generation_dir / "misc"
        if summary_dir is None:
            return None

        ratings = _dedupe_ratings(_normalize_ratings(toolkit.ratings))
        summary = {
            "generation_dir": str(toolkit.generation_dir) if toolkit.generation_dir else None,
            "ratings": ratings,
            "created_at": datetime.now().isoformat(),
            "source": "runtime",
        }
        summary_path = summary_dir / "knowledge_usage_summary.json"
        _write_json_atomic(summary_path, summary)
        return summary_path

    # -------------------------------------------------------------------------
    # Public API: Knowledge Extraction
    # -------------------------------------------------------------------------

    def extract_from_generation(
        self,
        generation_dir: str | Path,
        was_successful: bool,
        extractor_traj_dir: str | Path | None = None,
    ) -> KnowledgeExtractionSummary | None:
        """
        Extract knowledge from a PoC generation trajectory.

        Args:
            generation_dir: Path to the generation directory
            was_successful: Whether the generation was successful (from PipelineStatus)
            extractor_traj_dir: Directory to save the extractor's trajectory.
                If None, saves to <generation_dir>/trajs/ (used during PoC generation).
                When running via CLI, pass <knowledge_dir>/trajs/ for centralized storage.

        Returns:
            Summary of extraction results, or None if no trajectory found
        """
        generation_dir = Path(generation_dir).resolve()
        traj_path = generation_dir / "trajs" / "poc_generation.traj.json"

        if not traj_path.exists():
            logger.info(f"{LOG_PREFIX} No trajectory found at {traj_path}. Skipping.")
            return None

        try:
            traj = json.loads(traj_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warn(f"{LOG_PREFIX} Failed to load trajectory JSON {traj_path}: {exc}")
            return None

        # Generate extraction prompt with compressed trajectory
        # Don't include rating instructions - extraction agent doesn't have the rating tool
        existing_index = self.generate_index_prompt(include_rating_instructions=False)
        compressed_transcript = render_compressed_trajectory(traj)
        traj_summary = get_trajectory_summary(traj)
        prompt = _build_extraction_prompt(
            generation_dir=generation_dir,
            traj_path=traj_path,
            knowledge_dir=self.knowledge_dir,
            existing_index=existing_index,
            compressed_trajectory=compressed_transcript,
            trajectory_summary=traj_summary,
            was_successful=was_successful,
        )

        # Setup trajectory directory
        # When running standalone, save to knowledge dir; otherwise save alongside generation
        if extractor_traj_dir is not None:
            trajs_dir = Path(extractor_traj_dir).resolve()
            # Use bug_id + attempt for unique filename (e.g., "my-bug-name_attempt_1")
            bug_id = generation_dir.parent.name
            output_filename = f"{bug_id}_{generation_dir.name}"
        else:
            trajs_dir = generation_dir / "trajs"
            output_filename = "knowledge_extractor"
        trajs_dir.mkdir(parents=True, exist_ok=True)
        filter_trajs_dir = trajs_dir.parent / "knowledge_other"
        filter_trajs_dir.mkdir(parents=True, exist_ok=True)

        # Create ToolKit for extraction (includes trajectory for get_trajectory_turns tool)
        toolkit = self.create_extraction_toolkit(
            generation_dir,
            was_successful,
            trajectory=traj,
            filter_trajs_dir=filter_trajs_dir,
        )

        # Build agent with system prompt and tools
        system_prompt = _build_extractor_system_prompt(
            generation_dir=generation_dir,
            knowledge_dir=self.knowledge_dir,
            was_successful=was_successful,
        )

        agent = Agent(
            name="Trajectory Knowledge Extractor",
            description="Extracts reusable knowledge from PoC generation trajectories.",
            system_prompt=system_prompt,
            tools=ToolGroup.NO_INTERACTION,
            tool_servers=[toolkit],
            data_dir=None,
        )

        with agent.start_session(traj_path=trajs_dir / f"{output_filename}.traj.json") as session:
            turn = session.send(prompt)
            agent_response = turn.result

        # Resolve the trajectory path
        extractor_traj_path = trajs_dir / f"{output_filename}.traj.json"

        # Always write extraction summary to the attempt's misc directory
        summary_dir = generation_dir / "misc"
        extraction_summary = {
            "generation_dir": str(generation_dir),
            "knowledge_dir": str(self.knowledge_dir),
            "reported_ids": list(toolkit.reported_ids),
            "updated_ids": list(toolkit.updated_ids),
            "ratings": _dedupe_ratings(_normalize_ratings(toolkit.ratings)),
            "extractor_traj_path": str(extractor_traj_path),
            "was_successful": was_successful,
            "created_at": datetime.now().isoformat(),
            "source": "runtime",
        }
        try:
            _write_json_atomic(summary_dir / "knowledge_extractor_summary.json", extraction_summary)
        except Exception as exc:
            logger.warn(f"{LOG_PREFIX} Failed to write extraction summary: {exc}")

        return KnowledgeExtractionSummary(
            generation_dir=generation_dir,
            trajectory_path=traj_path,
            knowledge_dir=self.knowledge_dir,
            extractor_traj_path=extractor_traj_path,
            agent_response=agent_response,
            reported_ids=list(toolkit.reported_ids),
            updated_ids=list(toolkit.updated_ids),
            ratings=list(toolkit.ratings),
            was_successful=was_successful,
        )
