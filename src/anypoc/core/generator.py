#!/usr/bin/env python3
"""
POC Generator - Generate proof-of-concept exploits from bug reports

Internal module that validates bug reports using an analyzer agent, then generates
POCs and finally checks evidence.

Pipeline:
1. Analyzer validates bug report (real bug vs false positive)
2. If valid, generator creates POC and collects evidence
3. If invalid, pipeline aborts with rejection reason saved

Note: This module provides internal functionality only. Use anypoc.core.manager
for the CLI interface.
"""

import signal
import sys
from pathlib import Path

from caw import Agent, ToolGroup

from anypoc.core.analyzer import analyze_bug
from anypoc.core.evidence_checker import CheckResult, check_evidence
from anypoc.core.knowledge import KnowledgeManager
from anypoc.core.report_writer import write_report
from anypoc.core.status import (
    PipelineStatus,
    find_latest_help_needed_attempt,
    find_next_attempt_number,
    get_attempt_dir,
    load_attempt_status,
)
from anypoc.types import BugAnalysisResult, PocGenerationState, PocGenerationSummary
from scanner.types import BugReport
from anypoc.utils import logger

LOG_PREFIX = "[POC Generator]"


def load_bug_report(bug_report_path: Path) -> str:
    """Load a bug report (markdown with frontmatter) as plain markdown."""
    return BugReport.from_file(bug_report_path).to_markdown()


def setup_directories(output_dir: Path) -> dict[str, Path]:
    """
    Create required directory structure.

    Args:
        output_dir: Root output directory

    Returns:
        Dictionary mapping directory names to paths
    """
    dirs = {
        "poc": output_dir / "poc",
        "evidence": output_dir / "evidence",
        "playground": output_dir / "playground",
        "reproduce": output_dir / "reproduce",
        "trajs": output_dir / "trajs",
    }

    for dir_path in dirs.values():
        dir_path.mkdir(parents=True, exist_ok=True)

    return dirs


async def generate_poc(
    bug_report_path: Path,
    output_dir: Path,
    paths_file: Path,
    debug: bool = False,
    resume_from: int | None = None,
    help_context: str | None = None,
    custom_prompts: dict[str, str | None] | None = None,
    knowledge_manager: KnowledgeManager | None = None,
    disable_knowledge: bool = False,
    skip_analysis: bool = False,
) -> None:
    """
    Generate a PoC from the provided bug report and paths info.

    Args:
        bug_report_path: Path to the bug report file
        output_dir: Base output directory (attempts will be created as subdirectories)
        paths_file: Path to the paths description file
        debug: Run in debug mode without calling models
        resume_from: Attempt number to resume from. The new attempt inherits
            context (help_needed.md, generation summary, files) from that attempt.
        help_context: Additional context/instructions for the retry.
        custom_prompts: Optional dict of project-specific prompts:
            - "analysis": Custom analysis step prompt
            - "poc_gen": Custom POC generation step prompt
            - "evidence": Custom evidence checking step prompt
            - "bug_report_format": Custom bug report format template
        knowledge_manager: Optional KnowledgeManager for accessing the knowledge base
        disable_knowledge: If True, disable all knowledge features even if knowledge_manager
            is provided. No knowledge will be shown to the agent and no extraction will occur.
        skip_analysis: If True, skip the bug analysis step and treat the bug as valid
            with an empty summary.

    The function writes results to status.json in the attempt directory.
    Check pipeline_status.get_final_status() for the result.
    """

    logger.info(f"{LOG_PREFIX} Starting")
    if debug:
        logger.warn(f"{LOG_PREFIX} Debug mode")
    if disable_knowledge:
        logger.info(f"{LOG_PREFIX} Knowledge features disabled")

    if not bug_report_path.exists():
        raise FileNotFoundError(f"Bug report not found: {bug_report_path}")

    if not paths_file.exists():
        raise FileNotFoundError(f"Paths file not found: {paths_file}")

    # Handle attempt management
    base_output_dir = output_dir
    previous_attempt_dir: Path | None = None
    previous_status: PipelineStatus | None = None

    if resume_from is not None:
        # User-requested retry from a specific attempt. No state requirement —
        # retries are user-controlled and can happen for any reason.
        previous_status = load_attempt_status(base_output_dir, resume_from)
        if previous_status is None:
            raise ValueError(f"Attempt {resume_from} not found in {base_output_dir}")
        previous_attempt_dir = get_attempt_dir(base_output_dir, resume_from)
        attempt_number = find_next_attempt_number(base_output_dir)
        logger.info(f"{LOG_PREFIX} Retrying from attempt {resume_from}, creating attempt {attempt_number}")
    else:
        # Check if there's an existing attempt that needs help (auto-resume)
        help_result = find_latest_help_needed_attempt(base_output_dir)
        if help_result is not None:
            prev_attempt_num, previous_status = help_result
            previous_attempt_dir = get_attempt_dir(base_output_dir, prev_attempt_num)
            attempt_number = find_next_attempt_number(base_output_dir)
            logger.info(
                f"{LOG_PREFIX} Found attempt {prev_attempt_num} needing help, creating attempt {attempt_number}"
            )
        else:
            attempt_number = find_next_attempt_number(base_output_dir)
            logger.info(f"{LOG_PREFIX} Starting new attempt {attempt_number}")

    # Create attempt directory
    attempt_dir = get_attempt_dir(base_output_dir, attempt_number)
    dirs = setup_directories(attempt_dir)
    trajs_dir = dirs["trajs"]

    # Initialize pipeline status
    pipeline_status = PipelineStatus(
        bug_report_path=str(bug_report_path),
        output_dir=str(attempt_dir),
        attempt_number=attempt_number,
        resumed_from=(
            resume_from
            if resume_from
            else (int(previous_attempt_dir.name.split("_")[1]) if previous_attempt_dir else None)
        ),
    )
    pipeline_status.save(attempt_dir)

    interrupted = False

    def signal_handler(_signum, _frame):
        nonlocal interrupted
        if interrupted:
            logger.error(f"{LOG_PREFIX} Force exit")
            sys.exit(1)

        interrupted = True
        logger.warn(f"{LOG_PREFIX} Interrupted")
        interrupted_file = attempt_dir / "interrupted"
        interrupted_file.write_text("POC generation interrupted\n")
        sys.exit(130)

    signal.signal(signal.SIGINT, signal_handler)

    bug_content = load_bug_report(bug_report_path)
    paths_content = paths_file.read_text()

    if debug:
        logger.warn(f"{LOG_PREFIX} Debug mode - skipping agents")
        return

    # Build context from previous attempt if resuming
    resume_context = _build_resume_context(previous_attempt_dir, help_context) if previous_attempt_dir else None

    # Extract custom prompts
    custom_prompts = custom_prompts or {}
    analysis_prompt = custom_prompts.get("analysis")
    poc_gen_prompt = custom_prompts.get("poc_gen")
    evidence_prompt = custom_prompts.get("evidence")
    bug_report_format = custom_prompts.get("bug_report_format")

    # Step 1: Analyze and validate the bug report
    # Skip analysis if resuming from a previous attempt (bug was already validated)
    analysis_summary: str | None = None
    if skip_analysis:
        logger.info(f"{LOG_PREFIX} Step 1: Bug Analysis (skipped - bypass flag set)")
        pipeline_status.analysis.update("valid")
        filtered_content = bug_content
        is_valid = True
        analysis_summary = None
    elif previous_attempt_dir is not None and previous_status and previous_status.analysis.status == "valid":
        logger.info(
            f"{LOG_PREFIX} Step 1: Bug Analysis (skipped - reusing from attempt {previous_status.attempt_number})"
        )
        pipeline_status.analysis.update("valid")
        filtered_content = bug_content  # Use original bug content
        is_valid = True
        # Try to load analysis summary from previous attempt
        analysis_summary = _load_previous_analysis_summary(previous_attempt_dir)
    else:
        logger.info(f"{LOG_PREFIX} Step 1: Bug Analysis")
        try:
            is_valid, filtered_content, analysis_summary = analyze_bug(
                bug_content=bug_content,
                paths_content=paths_content,
                output_dir=attempt_dir,
                playground_dir=dirs["playground"],
                trajs_dir=trajs_dir,
                custom_prompt=analysis_prompt,
            )

            if is_valid:
                pipeline_status.analysis.update("valid")
            else:
                pipeline_status.analysis.update("rejected")
        except Exception:
            pipeline_status.analysis.update("error")
            pipeline_status.mark_complete()
            pipeline_status.save(attempt_dir)
            raise

    pipeline_status.save(attempt_dir)

    if not is_valid:
        logger.warn(f"{LOG_PREFIX} Bug rejected")
        pipeline_status.mark_complete()
        pipeline_status.save(attempt_dir)
        logger.info(f"{LOG_PREFIX} Final status: {pipeline_status.get_final_status()}")
        return

    # Step 2: Generate POC using validated bug report
    logger.info(f"{LOG_PREFIX} Step 2: POC Generation")
    # Disable knowledge if flag is set
    effective_knowledge_manager = None if disable_knowledge else knowledge_manager
    try:
        generation_summary = await _run_poc_generation(
            dirs=dirs,
            filtered_content=filtered_content,
            paths_content=paths_content,
            trajs_dir=trajs_dir,
            resume_context=resume_context,
            custom_prompt=poc_gen_prompt,
            knowledge_manager=effective_knowledge_manager,
            analysis_summary=analysis_summary,
        )

        # Check if agent needs help
        if generation_summary and generation_summary.status == PocGenerationState.NEEDS_HELP:
            logger.warn(f"{LOG_PREFIX} POC generation needs help")
            pipeline_status.generation.update("help_needed")
            pipeline_status.help_needed_reason = generation_summary.next_actions
            _write_help_needed_file(attempt_dir, generation_summary, "generation")
            pipeline_status.mark_complete()
            pipeline_status.save(attempt_dir)
            logger.info(f"{LOG_PREFIX} Final status: {pipeline_status.get_final_status()}")
            return
        else:
            logger.info(f"{LOG_PREFIX} POC generation complete")
            pipeline_status.generation.update("completed")
    except Exception:
        pipeline_status.generation.update("error")
        pipeline_status.save(attempt_dir)
        raise

    pipeline_status.save(attempt_dir)

    # Step 3: Evidence checking and reproduction
    logger.info(f"{LOG_PREFIX} Step 3: Evidence Check")
    try:
        check_result, check_explanation = await check_evidence(
            poc_dir=dirs["poc"],
            evidence_dir=dirs["evidence"],
            reproduce_dir=dirs["reproduce"],
            playground_dir=dirs["playground"],
            filtered_bug_report=filtered_content,
            trajs_dir=trajs_dir,
            custom_prompt=evidence_prompt,
        )

        # Map CheckResult to status string
        status_map = {
            CheckResult.PASSED: "passed",
            CheckResult.FLAKY: "flaky",
            CheckResult.INVALID_EVIDENCE: "invalid_evidence",
            CheckResult.NOT_REPRODUCIBLE: "not_reproducible",
            CheckResult.IMPOSSIBLE: "impossible",
        }
        pipeline_status.evidence_check.update(status_map[check_result])
    except Exception:
        pipeline_status.evidence_check.update("error")
        pipeline_status.save(attempt_dir)
        raise

    pipeline_status.save(attempt_dir)

    # Save check result summary
    check_summary_path = attempt_dir / "check_summary.md"
    check_summary_path.write_text(
        f"# Evidence Check Result\n\n**Status:** {check_result.value}\n\n## Explanation\n\n{check_explanation}\n"
    )

    # Step 4: Generate submission report (only for passed/flaky)
    if check_result in (CheckResult.PASSED, CheckResult.FLAKY):
        logger.info(f"{LOG_PREFIX} Step 4: Report Generation")
        try:
            write_report(
                filtered_bug_report=filtered_content,
                poc_dir=dirs["poc"],
                output_dir=attempt_dir,
                trajs_dir=trajs_dir,
                bug_report_format=bug_report_format,
            )
            pipeline_status.report.update("completed")
        except Exception:
            pipeline_status.report.update("error")
            pipeline_status.save(attempt_dir)
            raise
    else:
        pipeline_status.report.update("skipped")

    pipeline_status.mark_complete()
    pipeline_status.save(attempt_dir)

    # Log final status
    final_status = pipeline_status.get_final_status()
    if check_result == CheckResult.PASSED:
        logger.info(f"{LOG_PREFIX} Final status: {final_status}")
    else:
        logger.warn(f"{LOG_PREFIX} Final status: {final_status}")


def _build_agent(
    playground_dir: Path,
    dirs: dict[str, Path],
    trajs_dir: Path,
    knowledge_manager: KnowledgeManager | None = None,
    tool_servers: list | None = None,
) -> Agent:
    playground = playground_dir.resolve()
    poc_dir = dirs["poc"].resolve()
    evidence_dir = dirs["evidence"].resolve()

    # Build knowledge base section if available
    knowledge_section = ""
    if knowledge_manager:
        knowledge_section = knowledge_manager.generate_agent_knowledge_section()

    instructions = f"""You are an expert exploit developer tasked with generating PoCs from validated bug reports.

## Directory Structure:
- **Playground** ({playground}): Use this for experimentation, testing ideas, and iterating on your approach
- **Final PoC** ({poc_dir}): Only place your final, minimal, working PoC here
- **Evidence** ({evidence_dir}): Store execution evidence (crash logs, screenshots, etc.)

## Workflow:
1. **Understand** the bug report thoroughly
2. **Experiment** in the playground - test ideas, try approaches, verify assumptions
3. **Iterate** until you can reliably trigger the bug
4. **Finalize** a minimal, clean PoC and place it in the poc directory
5. **Execute** and collect evidence

## Important:
- The playground is your scratch space - feel free to create test files and experiment
- Only copy to poc/ when you have a working, minimal PoC
- If the bug cannot be triggered, document why in IMPOSSIBLE.md
- Record precise steps so investigators can reproduce your work
- No dummy examples or conceptual demonstrations - either a real PoC or IMPOSSIBLE.md

## User-Triggerable PoC Principle

Your PoC must demonstrate something a **real user or attacker can do** through normal
interaction surfaces (file input, network request, API call, UI action, CLI arguments, etc.).

- **DO**: Craft a malicious input file, webpage, network payload, or API request that
  triggers the bug when processed by the target software in its normal mode of operation.
- **DO NOT**: Directly call internal functions, manipulate in-memory state, or write a
  test harness that bypasses the software's input path. Such PoCs prove the code is buggy
  but fail to show real-world exploitability.
- **Ask yourself**: "If I present this PoC to a triaging developer, would they immediately see that the bug is reachable from user-controlled input?" If not, improve the PoC to make this clearer.

{knowledge_section}
"""

    return Agent(
        name="POC Generator",
        description="Generates proof-of-concept exploits and supporting evidence from bug reports.",
        system_prompt=instructions,
        tools=ToolGroup.NO_INTERACTION,
        tool_servers=tool_servers,
        data_dir=None,
    )


def _build_generation_steps(
    bug_content: str,
    paths_content: str,
    dirs: dict[str, Path],
    resume_context: str | None = None,
    custom_prompt: str | None = None,
    knowledge_index: str | None = None,
    analysis_summary: str | None = None,
) -> list[tuple[str, str]]:
    poc_dir = dirs["poc"]
    evidence_dir = dirs["evidence"]
    playground_dir = dirs["playground"]
    summary_schema = PocGenerationSummary.to_prompt_description()

    # Add resume context section if resuming from previous attempt
    resume_section = ""
    if resume_context:
        resume_section = f"""
## IMPORTANT: Resuming from Previous Attempt

This is a continuation of a previous PoC generation attempt that needed help.
Review the context below carefully before proceeding:

{resume_context}

Use the information above to guide your approach. The previous attempt may have
made progress or identified specific blockers that you should address.
"""

    # Add project-specific instructions if provided
    custom_section = ""
    if custom_prompt:
        custom_section = f"""
## Project-Specific Instructions:
{custom_prompt}
"""

    # Add knowledge base index if available
    knowledge_section = ""
    if knowledge_index:
        knowledge_section = f"""
{knowledge_index}

**IMPORTANT**: After reading the FULL content of ANY knowledge file, you MUST rate its
usefulness using the `rate_knowledge` tool with a score from -10 to 10:
- 10: directly helped solve/advance the task
- 0: irrelevant / provided no benefit
- -10: actively misleading / wasted time

If poc_forms/ knowledge entries exist, review them for reusable PoC format ideas.
The collection is not exhaustive — feel free to invent new PoC forms as needed.

"""

    # Add analysis summary from bug analyzer if available
    analysis_section = ""
    if analysis_summary:
        analysis_section = f"""
## Analysis Summary (from Bug Analyzer)

The bug analyzer has already explored the codebase and provides the following context:

{analysis_summary}

Use this information to guide your PoC development. The analyzer has already verified the bug is valid.

"""

    step1_prompt = f"""You are generating a proof-of-concept (PoC) for a validated security bug.
{resume_section}{knowledge_section}{analysis_section}

## Validated Bug Report:
{bug_content}

## Available Paths:
{paths_content}

## Directories:
- **Playground (for experimentation):** {playground_dir}
- **Final PoC (only when ready):** {poc_dir}

## Your Approach:

1. **Experiment in playground first**: Use {playground_dir} to test ideas,
try different approaches, and iterate on your PoC.
Create test files, run experiments, and verify your understanding of the bug.

2. **Verify the bug triggers**: Before finalizing, make sure you can actually trigger the bug.
Test your PoC in the playground and confirm it causes the expected behavior (crash, assertion failure, etc.).

3. **Finalize only when confident**: Once you have a working PoC that reliably triggers the bug, create a
**minimal, concise, end-to-end functional** version and copy it to {poc_dir}.
The final PoC should be clean and self-contained.

## User-Triggerable PoC Principle

Your PoC must demonstrate something a **real user or attacker can do** through normal
interaction surfaces (file input, network request, API call, UI action, CLI arguments, etc.).

- **DO**: Craft a malicious input file, webpage, network payload, or API request that
  triggers the bug when processed by the target software in its normal mode of operation.
- **DO NOT**: Directly call internal functions, manipulate in-memory state, or write a
  test harness that bypasses the software's input path. Such PoCs prove the code is buggy
  but fail to show real-world exploitability.
- **Ask yourself**: "If I present this PoC to a triaging developer, would they immediately
  see that the bug is reachable from user-controlled input?" If not, improve the PoC to make this clearer.

## CRITICAL RULES:

- **NO dummy examples**: If you cannot trigger the real bug, do not create fake/simulated examples.
    Either create a real working PoC or declare it impossible.
- **Real bugs only**: The PoC must actually trigger the vulnerability in the target software,
    not just illustrate how it could theoretically work.
- **Do NOT kill the orchestrator**: Never run blanket kill commands like `pkill python`,
    `pkill -u`, or `kill -9 1` — they will terminate the poc runner/orchestrator
    process. Only terminate the specific test processes you started.

## If PoC is NOT Possible:

If after investigation you determine that creating a PoC is **impossible**,
write a file `{poc_dir}/IMPOSSIBLE.md` explaining:

1. **Failure Category** (pick one):
   - `UNREACHABLE`: The vulnerable code path cannot be reached from user-controlled input
   - `ENVIRONMENT_DEPENDENT`: Requires special hardware, OS, or environment we cannot replicate
   - `INVALID_BUG`: Further analysis shows this is not actually a valid/exploitable bug
   - `OTHER`: Some other fundamental blocker

2. **Detailed Explanation**: Why the PoC cannot be created

Do NOT create dummy or fake demonstrations as a substitute.
If it's impossible, just write IMPOSSIBLE.md and stop.
{custom_section}"""

    step2_prompt = f"""Execute the PoC and gather evidence.

## Tasks:

**Process safety**: Do not run blanket kill commands (e.g., `pkill python`, `pkill -u`,
`kill -9 1`) because they will terminate the poc runner/orchestrator process. Only
stop the specific test processes you launched.

1. **Execute the final PoC** from {poc_dir}
2. **Collect evidence** according to the oracle (crash logs, ASan output, screenshots, etc.)
3. **Save all evidence** to {evidence_dir}

If you wrote IMPOSSIBLE.md in the previous step, explain your findings in your response and skip execution.
"""

    step3_prompt = f"""Summarize the PoC generation progress and current status.

## Final Response Format:
Your final message MUST contain the summary directly using the following structure:
{summary_schema}

Keep the prose concise; the status field must pick one of the allowed options."""

    return [
        ("PoC Generation", step1_prompt),
        ("Execution & Evidence", step2_prompt),
        ("Generation Summary", step3_prompt),
    ]


def _save_prompts_to_file(path: Path, prompts: list[tuple[str, str]], title: str) -> None:
    """Save a list of (step_name, prompt) tuples to a markdown file."""
    content_parts = [f"# {title}\n"]
    for idx, (step_name, prompt) in enumerate(prompts, start=1):
        content_parts.append(f"## Step {idx}: {step_name}\n\n{prompt}\n")
    path.write_text("\n---\n\n".join(content_parts))


async def _run_poc_generation(
    dirs: dict[str, Path],
    filtered_content: str,
    paths_content: str,
    trajs_dir: Path,
    resume_context: str | None = None,
    custom_prompt: str | None = None,
    knowledge_manager: KnowledgeManager | None = None,
    analysis_summary: str | None = None,
) -> PocGenerationSummary | None:
    """Run POC generation with its own agent session.

    Args:
        dirs: Directory paths for poc, evidence, playground, etc.
        filtered_content: Validated bug report content
        paths_content: Available paths description
        trajs_dir: Directory for saving trajectory files
        resume_context: Context from previous attempt if resuming
        custom_prompt: Optional project-specific prompt to append
        knowledge_manager: Optional KnowledgeManager for accessing the knowledge base
        analysis_summary: Summary from bug analyzer about explored files and bug understanding

    Returns:
        The parsed PocGenerationSummary if available, None otherwise.
    """
    # Setup knowledge base integration if manager provided
    knowledge_index: str | None = None
    query_toolkit = None

    if knowledge_manager:
        knowledge_index = knowledge_manager.generate_index_prompt()
        query_toolkit = knowledge_manager.create_query_toolkit(
            summary_dir=trajs_dir.parent / "misc",
            generation_dir=trajs_dir.parent,
        )

    tool_servers = [query_toolkit] if query_toolkit else None

    agent = _build_agent(
        dirs["playground"],
        dirs,
        trajs_dir,
        knowledge_manager=knowledge_manager,
        tool_servers=tool_servers,
    )

    step_prompts = _build_generation_steps(
        filtered_content,
        paths_content,
        dirs,
        resume_context,
        custom_prompt,
        knowledge_index=knowledge_index,
        analysis_summary=analysis_summary,
    )

    # Save all prompts to trajs directory
    _save_prompts_to_file(trajs_dir / "poc_generation_prompts.md", step_prompts, "POC Generation Prompts")

    summary_response = ""

    try:
        with agent.start_session(traj_path=trajs_dir / "poc_generation.traj.json") as session:
            for idx, (title, prompt) in enumerate(step_prompts, start=1):
                logger.info(f"{LOG_PREFIX} {title}")
                turn = session.send(prompt)
                if idx == len(step_prompts):
                    summary_response = turn.result
    finally:
        if knowledge_manager and query_toolkit:
            try:
                knowledge_manager.write_usage_summary(query_toolkit)
            except Exception as exc:
                logger.warn(f"{LOG_PREFIX} Failed to write knowledge usage summary: {exc}")

    if summary_response:
        return await _save_generation_summary(summary_response, dirs["poc"])
    return None


async def _save_generation_summary(summary_text: str, poc_dir: Path) -> PocGenerationSummary | None:
    """Persist and parse the generation summary from agent response.

    Returns:
        The parsed PocGenerationSummary if extraction succeeds, None otherwise.
    """
    summary_path = poc_dir / "generation_summary.md"
    json_path = poc_dir / "generation_summary.json"

    # Always write from agent response
    summary_path.write_text(summary_text)

    parsed = await PocGenerationSummary.extract_from_text_async(summary_text)
    if parsed:
        parsed.to_json_file(json_path)
    return parsed


def _load_previous_analysis_summary(previous_attempt_dir: Path) -> str | None:
    """Load analysis summary from a previous attempt's analysis result.

    Args:
        previous_attempt_dir: Path to the previous attempt directory

    Returns:
        The analysis_details string if found, None otherwise.
    """
    result_json_path = previous_attempt_dir / "analysis" / "analysis_result.json"
    if not result_json_path.exists():
        return None

    try:
        result = BugAnalysisResult.from_json_file(result_json_path)
        return result.analysis_details
    except Exception:
        return None


def _build_resume_context(previous_attempt_dir: Path, help_context: str | None) -> str:
    """Build context string from previous attempt for resumption.

    Args:
        previous_attempt_dir: Path to the previous attempt directory
        help_context: Additional context/instructions provided by user

    Returns:
        Formatted context string for the agent
    """
    context_parts = []

    # Read help_needed.md from previous attempt
    help_needed_file = previous_attempt_dir / "help_needed.md"
    if help_needed_file.exists():
        context_parts.append("### Previous Attempt Help Request")
        context_parts.append(help_needed_file.read_text())

    # Read generation summary from previous attempt
    summary_file = previous_attempt_dir / "poc" / "generation_summary.md"
    if summary_file.exists():
        context_parts.append("### Previous Attempt Summary")
        context_parts.append(summary_file.read_text())

    # Add user-provided help context
    if help_context:
        context_parts.append("### Additional Instructions from User")
        context_parts.append(help_context)

    # List files from previous attempt's poc and playground directories
    prev_poc_dir = previous_attempt_dir / "poc"
    prev_playground_dir = previous_attempt_dir / "playground"

    if prev_poc_dir.exists():
        poc_files = list(prev_poc_dir.rglob("*"))
        if poc_files:
            context_parts.append("### Files from Previous Attempt (poc/)")
            for f in poc_files[:20]:  # Limit to first 20 files
                if f.is_file():
                    context_parts.append(f"- {f.relative_to(prev_poc_dir)}")

    if prev_playground_dir.exists():
        playground_files = list(prev_playground_dir.rglob("*"))
        if playground_files:
            context_parts.append("### Files from Previous Attempt (playground/)")
            for f in playground_files[:20]:  # Limit to first 20 files
                if f.is_file():
                    context_parts.append(f"- {f.relative_to(prev_playground_dir)}")

    context_parts.append(f"\n**Previous attempt directory**: {previous_attempt_dir}")
    context_parts.append("You may read files from the previous attempt if needed.")

    return "\n\n".join(context_parts)


def _write_help_needed_file(
    attempt_dir: Path,
    summary: PocGenerationSummary,
    phase: str,
) -> Path:
    """Write help_needed.md file when agent requests assistance.

    Args:
        attempt_dir: Current attempt directory
        summary: The generation summary from the agent
        phase: Which phase needs help (e.g., "generation", "evidence_check")

    Returns:
        Path to the created help_needed.md file
    """
    help_file = attempt_dir / "help_needed.md"

    content = f"""# Help Needed

**Phase**: {phase}
**Status**: {summary.status.value}

## Summary of What Was Done

{summary.summary}

## What Help Is Needed

{summary.next_actions}

## How to Resume

To resume this attempt, use the POC manager CLI:

```bash
python -m anypoc.core.manager run <project_name> --bug-report <bug_report>
```

The manager will automatically detect and resume from this help_needed state.
"""

    help_file.write_text(content)
    return help_file
