from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from anypoc.utils.base_model import LLMGeneratedBaseModel


# ==================== PoC Generation Types ====================
class PocStatus(Enum):
    """Status of a PoC generation."""

    NOT_STARTED = "NotStarted"
    INVALID_BUG = "InvalidBug"
    REACHED_BUGGY_LOCATION = "ReachedBuggyLocation"
    TRIGGERING_DATA_FLOW = "TriggeringDataFlow"
    INTERNAL_INVALID_STATE = "InternalInvalidState"
    OBSERVED_BY_ORACLE = "ObservedByOracle"


class FixSuggestion(Enum):
    """Severity classification for bugs."""

    NOT_A_BUG = "NotABug"
    UNTRIGGERABLE_NO_USER_IMPACT = "UntriggerableNoUserImpact"
    TRIGGERABLE_UNLIKELY_OR_LOW_IMPACT = "TriggerableUnlikelyOrLowImpact"
    LATENT_ADD_ASSERTION_TO_PREVENT_REGRESSION = "LatentAddAssertionToPreventRegression"
    TRIGGERABLE_MODERATE_SEVERITY_SHOULD_FIX = "TriggerableModerateSeverityShouldFix"
    TRIGGERABLE_HIGH_SEVERITY_MUST_FIX = "TriggerableHighSeverityMustFix"


# ==================== POC Pipeline Output Types ====================


class BugAnalysisVerdict(Enum):
    """Validity outcome for bug analysis step."""

    VALID = "Valid"
    INVALID = "Invalid"


class BugRejectionReason(Enum):
    """High-level reasons for rejecting a bug report."""

    OUT_OF_MEMORY = "OutOfMemory"
    HARDWARE_LIMITATION = "HardwareLimitation"
    UNSUPPORTED_OPERATING_SYSTEM = "UnsupportedOperatingSystem"
    ENVIRONMENT_CONSTRAINT = "EnvironmentConstraint"
    OTHER = "Other"


class BugAnalysisResult(LLMGeneratedBaseModel):
    """Structured response from the bug analysis agent."""

    verdict: BugAnalysisVerdict = Field(description="Whether the bug report is considered valid or invalid.")
    rejection_reason: BugRejectionReason = Field(
        description="If invalid, pick the closest reason; use Other when the report is valid."
    )
    analysis_details: str = Field(
        description=(
            "If invalid: brief reasoning for rejection. "
            "If valid: summary of exploration including key files/functions examined, "
            "understanding of the bug mechanism, root cause location, and relevant context for PoC generation."
        )
    )


class PocGenerationState(Enum):
    """Status of the PoC generation effort."""

    COMPLETED = "Completed"
    PARTIAL = "Partial"
    NEEDS_HELP = "NeedsHelp"
    IMPOSSIBLE = "Impossible"


class PocGenerationSummary(LLMGeneratedBaseModel):
    """Final summary produced after the PoC generation steps."""

    status: PocGenerationState = Field(description="Overall status of the PoC generation effort.")
    summary: str = Field(description="What was attempted, current PoC behavior, and whether the bug appears triggered.")
    next_actions: str = Field(
        description="Concrete next steps or support needed. Use 'None' if no additional help is required."
    )


class EvidenceCheckStatus(Enum):
    """Result of evidence checking and reproduction."""

    PASSED = "Passed"
    FLAKY = "Flaky"
    NOT_REPRODUCIBLE = "NotReproducible"
    INVALID_EVIDENCE = "InvalidEvidence"
    IMPOSSIBLE = "Impossible"


class EvidenceCheckOutcome(LLMGeneratedBaseModel):
    """Structured output from the evidence checker agent."""

    status: EvidenceCheckStatus = Field(description="Result after attempting to reproduce the PoC.")
    reproduction_summary: str = Field(
        description="Key steps and observations from the reproduction attempt, including whether the bug manifested."
    )
    conclusion: str = Field(
        description="Why this status was chosen and any follow-up actions for the PoC or environment."
    )


# ==================== Knowledge Base Types ====================


class KnowledgeType(Enum):
    """Categories for reusable knowledge extracted from trajectories."""

    TEST_FRAMEWORK = "TestFramework"
    CLASS = "Class"
    FUNCTION = "Function"
    MODULE = "Module"
    INTERNAL_API = "InternalAPI"
    COMMAND_LINE_ARGUMENT = "CommandLineArgument"
    COMMAND = "Command"
    LIBRARY = "Library"
    BUILD_SYSTEM = "BuildSystem"
    CONFIGURATION = "Configuration"
    ENVIRONMENT_SETUP = "EnvironmentSetup"
    DEBUGGING = "Debugging"
    REPRODUCTION_TECHNIQUE = "ReproductionTechnique"
    LOGGING_OR_TELEMETRY = "LoggingOrTelemetry"
    OTHER = "Other"


class KnowledgeMetadata(LLMGeneratedBaseModel):
    """Non-LLM metadata used to track knowledge quality over time."""

    usefulness_ratings: list[list[float]] = Field(
        default_factory=lambda: [[]],
        description=(
            "Usefulness ratings per version. Each inner list contains numeric ratings collected for that version."
        ),
    )
    iterations_survived: int = Field(
        0,
        description="Number of extraction iterations/runs where this knowledge was reviewed and kept.",
    )
    version: int = Field(1, description="Version number starting from 1.")

    @model_validator(mode="before")
    @classmethod
    def _normalize_metadata(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        version = data.get("version")
        try:
            version_int = int(version) if version is not None else 1
        except (TypeError, ValueError):
            version_int = 1
        version_int = max(1, version_int)
        data["version"] = version_int

        survived = data.get("iterations_survived")
        try:
            survived_int = int(survived) if survived is not None else 0
        except (TypeError, ValueError):
            survived_int = 0
        data["iterations_survived"] = max(0, survived_int)

        ratings = data.get("usefulness_ratings")
        if ratings is None:
            data["usefulness_ratings"] = [[] for _ in range(version_int)]
        elif isinstance(ratings, (list, tuple)):
            normalized_outer: list[list[float]] = []
            for inner in ratings:
                if inner is None:
                    normalized_outer.append([])
                elif isinstance(inner, (list, tuple)):
                    normalized_inner: list[float] = []
                    for item in inner:
                        try:
                            normalized_inner.append(float(item))
                        except (TypeError, ValueError):
                            continue
                    normalized_outer.append(normalized_inner)
                else:
                    normalized_outer.append([])
            if not normalized_outer:
                normalized_outer = [[]]
            if len(normalized_outer) < version_int:
                normalized_outer.extend([[] for _ in range(version_int - len(normalized_outer))])
            elif len(normalized_outer) > version_int:
                # Treat ratings length as the source of truth if it diverges.
                data["version"] = len(normalized_outer)
            data["usefulness_ratings"] = normalized_outer

        return data


class ReusableKnowledge(LLMGeneratedBaseModel):
    """Reusable knowledge extracted from PoC generation trajectories."""

    id: str = Field(description="Unique identifier for this knowledge entry.")
    keywords: list[str] = Field(description="Keywords that help retrieve this knowledge.")
    knowledge_type: KnowledgeType = Field(description="Type/category of this knowledge.")
    knowledge: str = Field(description="Reusable knowledge content (write in Markdown).")
    metadata: KnowledgeMetadata = Field(
        default_factory=KnowledgeMetadata,
        description="Metadata tracked by the system (do not generate this in the report).",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_keywords(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        raw_id = data.get("id")
        if isinstance(raw_id, str):
            data["id"] = raw_id.strip()

        raw_keywords = data.get("keywords")
        if raw_keywords is None:
            return data

        if isinstance(raw_keywords, str):
            data["keywords"] = [raw_keywords]
        elif isinstance(raw_keywords, (list, tuple)):
            normalized = [str(item).strip() for item in raw_keywords if item is not None and str(item).strip()]
            # Deduplicate while preserving order
            data["keywords"] = list(dict.fromkeys(normalized))

        return data
