"""Knowledge metadata models."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from anypoc.types import KnowledgeType
from anypoc.utils import BaseModelWithHelpers


class KnowledgeFileMetadata(BaseModelWithHelpers):
    """Metadata for a single knowledge file, stored separately from content."""

    # Core identification
    knowledge_id: str = Field(description="Unique identifier matching the content file")
    file_path: str = Field(description="Relative path from content/ directory")
    category_path: list[str] = Field(
        default_factory=list, description="Hierarchical category path, e.g. ['build', 'gfx']"
    )
    knowledge_type: KnowledgeType = Field(default=KnowledgeType.OTHER)
    keywords: list[str] = Field(default_factory=list)

    # Quality tracking
    version: int = Field(default=1)
    usefulness_ratings: list[list[float]] = Field(
        default_factory=lambda: [[]],
        description="Ratings per version. Each inner list contains ratings for that version.",
    )
    iterations_survived: int = Field(default=0)

    # Source tracking
    source_generations: list[str] = Field(
        default_factory=list, description="List of generation directories this knowledge came from"
    )
    source_success_flags: list[bool] = Field(
        default_factory=list, description="Whether each source generation was successful"
    )

    # Timestamps
    created_at: str = Field(default="")
    updated_at: str = Field(default="")

    def add_rating(self, score: float) -> None:
        """Add a rating to the current version."""
        if not self.usefulness_ratings:
            self.usefulness_ratings = [[]]
        self.usefulness_ratings[-1].append(score)
        self.iterations_survived += 1
        self.updated_at = datetime.now().isoformat()

    def bump_version(self) -> None:
        """Increment version and add new ratings list."""
        self.version += 1
        self.usefulness_ratings.append([])
        self.updated_at = datetime.now().isoformat()

    def add_source(self, generation_dir: str, was_successful: bool) -> None:
        """Record a source generation."""
        if generation_dir not in self.source_generations:
            self.source_generations.append(generation_dir)
            self.source_success_flags.append(was_successful)

    def get_average_rating(self) -> float | None:
        """Get average rating across all versions."""
        all_ratings = [r for version_ratings in self.usefulness_ratings for r in version_ratings]
        if not all_ratings:
            return None
        return sum(all_ratings) / len(all_ratings)

    def get_success_ratio(self) -> float | None:
        """Get ratio of successful source generations."""
        if not self.source_success_flags:
            return None
        return sum(self.source_success_flags) / len(self.source_success_flags)
