#!/usr/bin/env python3
"""
Report Writer - Generate concise bug report for developers

This module creates a submission-ready bug report from validated findings.
"""

from pathlib import Path

from caw import Agent, ToolGroup

from anypoc.utils import logger

LOG_PREFIX = "[Report Writer]"


def write_report(
    filtered_bug_report: str,
    poc_dir: Path,
    output_dir: Path,
    trajs_dir: Path,
    bug_report_format: str | None = None,
) -> Path:
    """
    Generate a concise bug report for submission to developers.

    Args:
        filtered_bug_report: The validated bug report content
        poc_dir: Directory containing POC artifacts
        output_dir: Output directory for the report
        trajs_dir: Directory for saving trajectory files
        bug_report_format: Optional project-specific report format template

    Returns:
        Path to the generated report file
    """
    report_path = output_dir / "report_to_submit.md"

    agent = _build_agent(poc_dir, trajs_dir)
    prompt = _build_report_prompt(filtered_bug_report, poc_dir, bug_report_format)

    # Save the prompt to trajs directory
    prompt_path = trajs_dir / "report_writer_prompt.md"
    prompt_path.write_text(f"# Report Writer Prompt\n\n{prompt}")

    logger.info(f"{LOG_PREFIX} Writing report...")

    with agent.start_session(traj_path=trajs_dir / "report_writer.traj.json") as session:
        turn = session.send(prompt)
        report_content = turn.result

    # Save the report
    if report_content:
        report_path.write_text(report_content)

    logger.info(f"{LOG_PREFIX} Done")
    return report_path


def _build_agent(poc_dir: Path, trajs_dir: Path) -> Agent:
    instructions = f"""You are writing a bug report for the project's security team.

Be concise and precise. The developers are experts - no need for excessive context or explanation.
POC files in {poc_dir} will be zipped and attached separately.
"""

    return Agent(
        name="Report Writer",
        description="Generates concise bug reports for developers.",
        system_prompt=instructions,
        tools=ToolGroup.NO_INTERACTION,
        data_dir=None,
    )


def _build_report_prompt(
    filtered_bug_report: str,
    poc_dir: Path,
    bug_report_format: str | None = None,
) -> str:
    # Build format section based on whether a custom format is provided
    if bug_report_format:
        format_section = f"""## Report Format:
Your response MUST be a markdown document following this exact format:

{bug_report_format}

Fill in each section based on the bug report and POC artifacts.
Output ONLY the filled-in report, no additional commentary."""
    else:
        format_section = """## Report Format:
Write a concise markdown report with:
- A clear title
- Files to submit section
- Vulnerable code location(s)
- Brief vulnerability analysis
- Impact description

Output ONLY the report content, no additional commentary."""

    return f"""Write a concise bug report for submission to the security team.

## Validated Bug Report:
{filtered_bug_report}

## POC Directory: {poc_dir}
Review the POC files and reference them in your report.

{format_section}

Keep it short. No fluff."""
