#!/usr/bin/env python3
"""
Bug Report Analyzer - Validate bug reports before POC generation

This module provides bug report validation functionality to be used
as part of the POC generation pipeline.
"""

from pathlib import Path

from caw import Agent, ToolGroup

from anypoc.types import BugAnalysisResult, BugAnalysisVerdict
from anypoc.utils import logger

LOG_PREFIX = "[Bug Analyzer]"


def analyze_bug(
    bug_content: str,
    paths_content: str,
    output_dir: Path,
    playground_dir: Path,
    trajs_dir: Path,
    custom_prompt: str | None = None,
) -> tuple[bool, str, str | None]:
    """
    Analyze a bug report to determine validity.

    Args:
        bug_content: The raw bug report content
        paths_content: Available paths description
        output_dir: Output directory for analysis results
        playground_dir: Directory containing the codebase
        trajs_dir: Directory for saving trajectory files
        custom_prompt: Optional project-specific prompt to append to analysis

    Returns:
        Tuple of (is_valid, result_content, analysis_summary) where:
        - is_valid: True if bug is valid, False if rejected
        - result_content: Original bug report if valid, rejection reason if invalid
        - analysis_summary: Summary of exploration and bug understanding (only when valid)
    """
    analysis_dir = output_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    rejection_path = analysis_dir / "rejection_reason.md"

    agent = _build_agent(playground_dir, trajs_dir)
    analysis_prompt = _build_analysis_prompt(bug_content, paths_content, custom_prompt)

    # Save the prompt to trajs directory
    prompt_path = trajs_dir / "bug_analyzer_prompt.md"
    prompt_path.write_text(f"# Bug Analyzer Prompt\n\n{analysis_prompt}")

    logger.info(f"{LOG_PREFIX} Analyzing...")
    with agent.start_session(traj_path=trajs_dir / "bug_analyzer.traj.json") as session:
        turn = session.send(analysis_prompt)
        result_text = turn.result

    # Save raw response
    response_path = analysis_dir / "analysis_response.md"
    response_path.write_text(result_text)

    analysis_result = BugAnalysisResult.extract_from_text(result_text)

    # Save parsed result as JSON if available
    if analysis_result:
        result_json_path = analysis_dir / "analysis_result.json"
        analysis_result.to_json_file(result_json_path)

        if analysis_result.verdict == BugAnalysisVerdict.INVALID:
            rejection_path.write_text(
                f"Verdict: {analysis_result.verdict.value}\n"
                f"Reason: {analysis_result.rejection_reason.value}\n"
                f"Details: {analysis_result.analysis_details}"
            )
            logger.info(f"{LOG_PREFIX} Bug rejected")
            return False, analysis_result.analysis_details, None
        # Valid verdict - return original bug content and analysis summary
        logger.info(f"{LOG_PREFIX} Bug validated")
        return True, bug_content, analysis_result.analysis_details

    # No structured result found - treat as rejection
    rejection_path.write_text(result_text)
    logger.info(f"{LOG_PREFIX} Bug rejected (no structured result)")
    return False, result_text, None


def _build_agent(playground_dir: Path, trajs_dir: Path) -> Agent:
    playground = playground_dir.resolve()

    instructions = f"""You are an expert security researcher tasked with validating bug reports.

Your job is to:
1. Determine if a bug report describes a real vulnerability or is likely a false positive
2. If valid, verify and refine the consequence and oracle information
3. Output either a validated/filtered bug report OR a rejection explanation

Be thorough but objective in your analysis. Look for evidence in the codebase when needed.
The source code location will be provided in the "Available Paths" section of the task prompt.

You can use {playground} as a scratch directory for any temporary files."""

    return Agent(
        name="Bug Analyzer",
        description="Validates bug reports and extracts/refines vulnerability information.",
        system_prompt=instructions,
        tools=ToolGroup.NO_INTERACTION,
        data_dir=None,
    )


def _build_analysis_prompt(
    bug_content: str,
    paths_content: str,
    custom_prompt: str | None = None,
) -> str:
    schema_description = BugAnalysisResult.to_prompt_description()

    # Build custom prompt section if provided
    custom_section = ""
    if custom_prompt:
        custom_section = f"""
## Project-Specific Instructions:
{custom_prompt}
"""

    return f"""Analyze this bug report to determine if it describes a real vulnerability.

## Bug Report:
{bug_content}

## Available Paths:
{paths_content}

## Your Tasks:

1. **Validity Check**: Determine if this bug report describes a real security issue or is likely a false positive.
   - Look for indicators of a real bug: clear reproduction steps, specific code paths, memory safety issues, etc.
   - Look for false positive indicators: misunderstanding of intended behavior, incomplete analysis, etc.
   - You may examine the codebase under the playground directory to verify claims.

2. **If the bug is VALID**: Confirm the bug appears real and exploitable.
   - In your analysis_details, summarize: key files/functions you examined, your understanding of the
     bug mechanism, the root cause location, and any relevant context that will help with PoC generation.

3. **If the bug is INVALID (likely false positive)**: Explain clearly why in analysis_details.
{custom_section}
## Final Response Format:
Your final message MUST include the structured analysis result:
{schema_description}
"""
