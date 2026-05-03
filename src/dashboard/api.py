"""Simple API server for the dashboard."""

import json
import mimetypes
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from anypoc.core.knowledge import KnowledgeManager
from anypoc.core.knowledge.tracking import get_knowledge_info_for_attempt
from caw import FastStats
from anypoc.utils import OUTPUT_DIR, PROJECTS_DIR
from anypoc.utils.spend_limit import GlobalCostStore, ProjectCostStore
from anypoc.utils.trajectory import is_trajectory_complete

try:
    import markdown
    from markdown.extensions.codehilite import CodeHiliteExtension
    from markdown.extensions.fenced_code import FencedCodeExtension

    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False

app = FastAPI()

# Allow CORS for dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Output directory - uses centralized config from anypoc.utils (respects ANYPOC_HOME / POC_OUTPUT_DIR)
OUTPUT_BASE_DIR = OUTPUT_DIR
OUTPUT_DIR_NAME = OUTPUT_BASE_DIR.name

# PROJECTS_DIR is imported from anypoc.utils (configurable via POC_PROJECTS_DIR)

# PoC pipeline steps
POC_STEPS = ["analysis", "generation", "evidence_check", "report"]

# Dashboard config file (persists sidebar preferences like hidden projects and order)
DASHBOARD_CONFIG_FILE = Path(__file__).resolve().parent / ".dashboard_config.json"

# Models config file (available providers and models for the CawProviderSelector)
MODELS_CONFIG_FILE = Path(__file__).resolve().parent / "models.json"


# Helper functions for monitor endpoints
def _get_output_dir(project: str) -> Path:
    """Get output directory for a project."""
    return OUTPUT_BASE_DIR / project


def _get_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0


def _parse_time_bound(value: str | None, *, field_name: str) -> float | None:
    """Parse an ISO datetime string into a unix timestamp."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None

    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}; expected ISO datetime") from exc

    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.timestamp()


def _parse_time_field(value: str | None) -> str:
    if value is None or not value.strip():
        return "modified"
    normalized = value.strip().lower()
    if normalized not in {"modified", "created"}:
        raise HTTPException(status_code=400, detail="Invalid time_field; expected one of: modified, created")
    return normalized


def _get_ctime(path: Path) -> float:
    try:
        stat = path.stat()
    except OSError:
        return 0

    birthtime = getattr(stat, "st_birthtime", None)
    if birthtime is not None:
        return float(birthtime)
    return stat.st_ctime


def _traj_matches_time_range(path: Path, start_ts: float | None, end_ts: float | None, time_field: str) -> bool:
    timestamp = _get_ctime(path) if time_field == "created" else _get_mtime(path)
    if start_ts is not None and timestamp < start_ts:
        return False
    if end_ts is not None and timestamp > end_ts:
        return False
    return True


def _scan_jobs_dir(output_dir: Path) -> Path:
    return output_dir / "scans"


def _iter_scan_log_dirs(output_dir: Path) -> Iterator[Path]:
    scans_dir = _scan_jobs_dir(output_dir)
    if not scans_dir.is_dir():
        return
    for job_dir in scans_dir.iterdir():
        if not job_dir.is_dir():
            continue
        logs = job_dir / "logs"
        if logs.is_dir():
            yield logs


def _list_bug_reports(output_dir: Path) -> list[Path]:
    """All bug report markdown files across every scan job for a project."""
    scans_dir = _scan_jobs_dir(output_dir)
    if not scans_dir.is_dir():
        return []
    return sorted(
        [path for path in scans_dir.glob("*/reports/*.md") if path.is_file()],
        key=_get_mtime,
        reverse=True,
    )


def _list_bug_trajs(output_dir: Path) -> list[dict[str, Any]]:
    """List .traj.json files across all scan jobs."""
    items: list[dict[str, Any]] = []
    for logs_dir in _iter_scan_log_dirs(output_dir):
        for path in logs_dir.rglob("*.traj.json"):
            if not path.is_file():
                continue
            items.append(
                {
                    "name": path.name,
                    "absolute_path": str(path),
                    "mtime": _get_mtime(path),
                }
            )
    items.sort(key=lambda item: item.get("mtime", 0), reverse=True)
    return items


def _list_pocs(output_dir: Path) -> list[Path]:
    poc_dir = output_dir / "poc"
    if not poc_dir.is_dir():
        return []
    return sorted([path for path in poc_dir.iterdir() if path.is_dir()], key=_get_mtime, reverse=True)


def _get_poc_attempts(poc_path: Path) -> list[tuple[int, Path]]:
    """Get all attempt directories sorted by attempt number."""
    attempts = []
    if not poc_path.is_dir():
        return attempts
    for entry in poc_path.iterdir():
        if entry.is_dir() and entry.name.startswith("attempt_"):
            try:
                attempt_num = int(entry.name.split("_")[1])
                attempts.append((attempt_num, entry))
            except (IndexError, ValueError):
                continue
    attempts.sort(key=lambda x: x[0])
    return attempts


def _get_attempt_status(attempt_dir: Path) -> dict[str, Any]:
    """Get status from an attempt directory."""
    status_file = attempt_dir / "status.json"
    if not status_file.is_file():
        return {}
    try:
        return json.loads(status_file.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _get_poc_status(poc_path: Path) -> dict[str, Any]:
    """Get status from the latest attempt directory."""
    attempts = _get_poc_attempts(poc_path)
    if not attempts:
        # Fallback to legacy status.json in poc_path root
        status_file = poc_path / "status.json"
        if not status_file.is_file():
            return {}
        try:
            return json.loads(status_file.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    # Get the latest attempt
    latest_attempt_dir = attempts[-1][1]
    return _get_attempt_status(latest_attempt_dir)


def _get_poc_color(status: dict[str, Any]) -> str:
    analysis_status = status.get("analysis", {}).get("status", "pending")
    generation_status = status.get("generation", {}).get("status", "pending")
    evidence_status = status.get("evidence_check", {}).get("status", "pending")
    report_status = status.get("report", {}).get("status", "pending")

    if analysis_status in {"rejected", "error"}:
        return "red"
    if generation_status in {"error", "impossible"}:
        return "red"
    if evidence_status in {"error", "impossible"}:
        return "red"
    if evidence_status in {"invalid_evidence", "not_reproducible"}:
        return "yellow"
    if evidence_status == "flaky":
        return "blue"
    if report_status == "error":
        return "red"
    if evidence_status == "passed":
        return "green"

    all_statuses = [analysis_status, generation_status, evidence_status, report_status]
    if any(s in {"pending", "in_progress"} for s in all_statuses):
        return "white"
    return "white"


def _get_poc_total_cost(poc_path: Path) -> float:
    """Get total cost across all attempts."""
    attempts = _get_poc_attempts(poc_path)
    if not attempts:
        # Fallback to legacy structure
        trajs_dir = poc_path / "trajs"
        if not trajs_dir.is_dir():
            return 0.0
        return FastStats.directory_total_cost(trajs_dir)

    total = 0.0
    for _, attempt_dir in attempts:
        trajs_dir = attempt_dir / "trajs"
        if trajs_dir.is_dir():
            total += FastStats.directory_total_cost(trajs_dir)
    return total


def _get_attempt_cost(attempt_dir: Path) -> float:
    """Get cost for a specific attempt."""
    trajs_dir = attempt_dir / "trajs"
    if not trajs_dir.is_dir():
        return 0.0
    return FastStats.directory_total_cost(trajs_dir)


def _get_step_traj_file(attempt_dir: Path, step: str) -> Path | None:
    """Get trajectory file for a step within an attempt directory."""
    trajs_dir = attempt_dir / "trajs"
    if not trajs_dir.is_dir():
        return None
    step_to_file = {
        "analysis": "bug_analyzer.traj.json",
        "generation": "poc_generation.traj.json",
        "evidence_check": "evidence_checker.traj.json",
        "report": "report_writer.traj.json",
    }
    traj_name = step_to_file.get(step)
    if not traj_name:
        return None
    traj_path = trajs_dir / traj_name
    return traj_path if traj_path.is_file() else None


def _build_file_tree(directory: Path, base_path: Path) -> list[dict[str, Any]]:
    result = []
    try:
        items = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return result
    for item in items:
        try:
            relative = item.relative_to(base_path)
        except ValueError:
            continue
        node: dict[str, Any] = {
            "name": item.name,
            "path": relative.as_posix(),
            "is_dir": item.is_dir(),
        }
        if item.is_dir():
            node["children"] = _build_file_tree(item, base_path)
        else:
            try:
                node["size"] = item.stat().st_size
            except OSError:
                node["size"] = 0
        result.append(node)
    return result


@app.get("/api/projects")
def get_projects():
    """List all projects."""
    if not PROJECTS_DIR.exists():
        return {"projects": []}

    projects = []
    for project_dir in sorted(PROJECTS_DIR.iterdir()):
        if project_dir.is_dir() and not project_dir.name.startswith("."):
            dockerfile = project_dir / "Dockerfile"
            if dockerfile.exists():
                projects.append({"name": project_dir.name})

    return {"projects": projects}


class DashboardConfig(BaseModel):
    hidden_projects: list[str] = []
    project_order: list[str] = []


@app.get("/api/dashboard-config")
def get_dashboard_config():
    """Get dashboard sidebar config (hidden projects, ordering)."""
    if DASHBOARD_CONFIG_FILE.exists():
        try:
            return json.loads(DASHBOARD_CONFIG_FILE.read_text())
        except Exception:
            pass
    return {"hidden_projects": [], "project_order": []}


@app.put("/api/dashboard-config")
def put_dashboard_config(config: DashboardConfig):
    """Save dashboard sidebar config."""
    DASHBOARD_CONFIG_FILE.write_text(json.dumps(config.model_dump(), indent=2) + "\n")
    return {"ok": True}


@app.get("/api/models")
def get_models_config():
    """Get available providers and models for the agent runtime selector."""
    if MODELS_CONFIG_FILE.exists():
        try:
            return json.loads(MODELS_CONFIG_FILE.read_text())
        except Exception:
            pass
    return {"providers": {}}


# Monitor endpoints - per-project output visualization
@app.get("/api/projects/{project}/monitor/summary")
def get_monitor_summary(project: str):
    """Get summary stats for a project's outputs."""
    output_dir = _get_output_dir(project)
    if not output_dir.exists():
        return {
            "exists": False,
            "bugs": 0,
            "bugs_cost_usd": 0,
            "pocs": 0,
            "pocs_complete": 0,
            "pocs_cost_usd": 0,
        }

    bugs_cost = 0.0
    for logs_dir in _iter_scan_log_dirs(output_dir):
        bugs_cost += FastStats.directory_total_cost(logs_dir)

    poc_paths = _list_pocs(output_dir)
    pocs_count = len(poc_paths)
    pocs_complete = 0
    pocs_cost = 0.0
    for poc_path in poc_paths:
        status = _get_poc_status(poc_path)
        if _get_poc_color(status) == "green":
            pocs_complete += 1
        pocs_cost += _get_poc_total_cost(poc_path)

    return {
        "exists": True,
        "bugs": len(_list_bug_reports(output_dir)),
        "bugs_cost_usd": bugs_cost,
        "pocs": pocs_count,
        "pocs_complete": pocs_complete,
        "pocs_cost_usd": pocs_cost,
    }


@app.get("/api/projects/{project}/monitor/bugs")
def get_monitor_bugs(project: str):
    """List bug reports for a project."""
    output_dir = _get_output_dir(project)
    items = []
    for bug_path in _list_bug_reports(output_dir):
        items.append({"name": bug_path.stem})

    complete_count = 0
    for logs_dir in _iter_scan_log_dirs(output_dir):
        complete_count += sum(1 for f in logs_dir.glob("*.traj.json") if is_trajectory_complete(f))

    return {"items": items, "complete_count": complete_count, "traj_files": _list_bug_trajs(output_dir)}


@app.get("/api/projects/{project}/monitor/bugs/{name}")
def get_monitor_bug_detail(project: str, name: str):
    """Get details for a specific bug report."""
    output_dir = _get_output_dir(project)

    # Find the .md report under any scan job's reports/ directory.
    md_candidates = sorted(output_dir.glob(f"scans/*/reports/{name}.md"))
    if not md_candidates:
        raise HTTPException(status_code=404, detail="Bug report not found")
    md_path = md_candidates[0]

    try:
        from scanner.types import BugReport

        bug_report = BugReport.from_file(md_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse report: {e}")

    try:
        raw_markdown = md_path.read_text(encoding="utf-8")
    except Exception:
        raw_markdown = ""
    markdown_html = _render_markdown(raw_markdown) if raw_markdown else ""

    job_dir = md_path.parent.parent  # scans/<scan-id>/
    return {
        "name": name,
        "scan_id": job_dir.name,
        "strategy": bug_report.strategy,
        "title": bug_report.title,
        "metadata": bug_report.metadata,
        "markdown_path": md_path.relative_to(output_dir).as_posix(),
        "markdown_name": md_path.name,
        "markdown_html": markdown_html,
    }


@app.get("/api/projects/{project}/monitor/pocs")
def get_monitor_pocs(project: str):
    """List PoCs for a project."""
    output_dir = _get_output_dir(project)
    items = []
    for poc_path in _list_pocs(output_dir):
        status = _get_poc_status(poc_path)
        color = _get_poc_color(status)
        total_cost = _get_poc_total_cost(poc_path)
        # Extract individual step statuses for filtering
        analysis_status = status.get("analysis", {}).get("status", "pending")
        generation_status = status.get("generation", {}).get("status", "pending")
        evidence_status = status.get("evidence_check", {}).get("status", "pending")
        annotation = _load_poc_annotation(poc_path)
        items.append(
            {
                "name": poc_path.name,
                "color": color,
                "is_complete": color == "green",
                "total_cost_usd": total_cost,
                "analysis_status": analysis_status,
                "generation_status": generation_status,
                "evidence_status": evidence_status,
                "annotation_status": annotation["status"],
            }
        )
    return {"items": items}


@app.get("/api/projects/{project}/monitor/pocs/{name}")
def get_monitor_poc_detail(project: str, name: str, attempt: int | None = None):
    """Get details for a specific PoC.

    Args:
        project: Project name
        name: PoC name
        attempt: Optional attempt number to view (defaults to latest)
    """
    output_dir = _get_output_dir(project)
    poc_path = output_dir / "poc" / name

    if not poc_path.is_dir():
        raise HTTPException(status_code=404, detail="PoC not found")

    # Get all attempts
    attempts_list = _get_poc_attempts(poc_path)
    total_cost = _get_poc_total_cost(poc_path)

    # Build attempts info
    attempts_info = []
    first_attempt_dir = None
    selected_attempt_dir = None
    selected_attempt_num = None

    for attempt_num, attempt_dir in attempts_list:
        if first_attempt_dir is None:
            first_attempt_dir = attempt_dir
        attempt_cost = _get_attempt_cost(attempt_dir)
        attempt_status = _get_attempt_status(attempt_dir)
        attempt_color = _get_poc_color(attempt_status)
        attempts_info.append(
            {
                "number": attempt_num,
                "cost_usd": attempt_cost,
                "color": attempt_color,
            }
        )
        # Select the requested attempt or default to latest
        if attempt is not None and attempt_num == attempt:
            selected_attempt_dir = attempt_dir
            selected_attempt_num = attempt_num
        elif attempt is None:
            # Default to latest (last in sorted list)
            selected_attempt_dir = attempt_dir
            selected_attempt_num = attempt_num

    # Handle case with no attempts (legacy structure)
    if not attempts_list:
        status = _get_poc_status(poc_path)
        color = _get_poc_color(status)
        steps = []
        for step_name in POC_STEPS:
            step_data = status.get(step_name, {})
            step_status = step_data.get("status", "pending")
            steps.append(
                {
                    "name": step_name,
                    "status": step_status,
                    "timestamp": step_data.get("timestamp", ""),
                    "cost_usd": None,
                    "traj_path": None,
                }
            )
        file_tree = _build_file_tree(poc_path, poc_path)
    else:
        # Get status from selected attempt
        selected_status = _get_attempt_status(selected_attempt_dir)
        color = _get_poc_color(selected_status)

        # Build steps - all steps from selected attempt
        steps = []
        for step_name in POC_STEPS:
            step_data = selected_status.get(step_name, {})
            step_status = step_data.get("status", "pending")

            traj_file = _get_step_traj_file(selected_attempt_dir, step_name)
            fs = FastStats.from_path(traj_file) if traj_file else None
            step_cost = fs.cost_usd if fs is not None else None

            traj_path_rel = None
            if traj_file:
                traj_path_rel = traj_file.relative_to(output_dir).as_posix()

            steps.append(
                {
                    "name": step_name,
                    "status": step_status,
                    "timestamp": step_data.get("timestamp", ""),
                    "cost_usd": step_cost,
                    "traj_path": traj_path_rel,
                }
            )

        # File tree for selected attempt only
        # We pass output_dir as base so relative paths include poc/name/attempt_X/
        file_tree = _build_file_tree(selected_attempt_dir, output_dir)

    # Look up the source scan job for this bug report (if any)
    scan_id = None
    bug_strategy = None
    md_candidates = sorted(output_dir.glob(f"scans/*/reports/{name}.md"))
    if md_candidates:
        md_path = md_candidates[0]
        scan_id = md_path.parent.parent.name
        try:
            from scanner.types import BugReport

            bug_strategy = BugReport.from_file(md_path).strategy
        except Exception:
            pass

    # Get knowledge usage and extraction info for the selected attempt
    knowledge_usage = None
    knowledge_extraction = None
    if selected_attempt_dir:
        knowledge_info = get_knowledge_info_for_attempt(selected_attempt_dir)
        knowledge_usage = knowledge_info.get("knowledge_usage")
        knowledge_extraction = knowledge_info.get("knowledge_extraction")

    # Get input directory content (shared across all attempts)
    input_dir = poc_path / "input"
    input_files = _build_file_tree(input_dir, input_dir) if input_dir.is_dir() else []

    # Load annotation
    annotation = _load_poc_annotation(poc_path)

    return {
        "name": name,
        "color": color,
        "is_complete": color == "green",
        "total_cost_usd": total_cost,
        "attempts": attempts_info,
        "selected_attempt": selected_attempt_num,
        "steps": steps,
        "file_tree": file_tree,
        "input_files": input_files,
        "scan_id": scan_id,
        "bug_strategy": bug_strategy,
        "knowledge_usage": knowledge_usage,
        "knowledge_extraction": knowledge_extraction,
        "annotation_status": annotation["status"],
        "annotation_notes": annotation["notes"],
    }


@app.get("/api/trajectory")
def get_trajectory(path: str):
    """Read a trajectory JSON file from a local path.

    Args:
        path: Absolute path to a .traj.json file.
    """
    file_path = Path(path).resolve()
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    if not file_path.name.endswith(".traj.json"):
        raise HTTPException(status_code=400, detail="Path must point to a .traj.json file")
    try:
        data = json.loads(file_path.read_text())
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Invalid JSON: {e}")
    return data


@app.get("/api/config")
def get_config():
    """Get dashboard configuration including base paths."""
    return {
        "output_dir": OUTPUT_DIR_NAME,
        "output_base_path": str(OUTPUT_BASE_DIR.resolve()),
    }


@app.get("/api/files/{base_dir}/{project}/{path:path}")
def get_file(base_dir: str, project: str, path: str):
    """Serve a file from the project's output directory."""
    # Validate base_dir matches configured output directory
    if base_dir != OUTPUT_DIR_NAME:
        raise HTTPException(status_code=404, detail="Not found")

    output_dir = _get_output_dir(project)
    file_path = (output_dir / path).resolve()

    # Security check
    try:
        file_path.relative_to(output_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found")

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Not found")

    # Determine content type

    mime, _ = mimetypes.guess_type(str(file_path))
    # Force text/plain rendering for source/config extensions that browsers
    # would otherwise download (e.g. application/javascript for .js) or
    # interpret as live web content (e.g. .html executing inline).
    text_extensions = {
        # Shell / logs / plain text
        ".sql",
        ".log",
        ".txt",
        ".csv",
        ".sh",
        ".bash",
        ".zsh",
        # Systems languages
        ".rs",
        ".go",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".cc",
        ".hh",
        # Scripting / dynamic languages
        ".py",
        ".js",
        ".mjs",
        ".cjs",
        ".jsx",
        ".ts",
        ".tsx",
        ".rb",
        ".lua",
        # Web source. NOTE: .html / .htm are intentionally NOT in this list —
        # HTML files should render as live web pages (text/html from
        # mimetypes.guess_type), not as source. Use the browser's View Source
        # if the raw markup is needed.
        ".css",
        ".scss",
        ".sass",
        # Structured data / config
        ".json",
        ".toml",
        ".yaml",
        ".yml",
        ".xml",
        ".ini",
        ".cfg",
        ".conf",
        ".gn",
        ".gni",
        ".properties",
        ".env",
        # Docs / misc
        ".md",
        ".rst",
        ".diff",
        ".patch",
    }
    if file_path.suffix.lower() in text_extensions:
        content_type = "text/plain; charset=utf-8"
    elif mime:
        content_type = mime
        if content_type.startswith("text/") and "charset" not in content_type:
            content_type += "; charset=utf-8"
    else:
        content_type = "text/plain; charset=utf-8"

    return Response(content=file_path.read_bytes(), media_type=content_type)


# =============================================================================
# Knowledge Base Endpoints
# =============================================================================


def _get_knowledge_dir() -> Path:
    """Get centralized knowledge directory."""
    return OUTPUT_BASE_DIR / "knowledge"


def _get_knowledge_manager(project: str) -> KnowledgeManager | None:
    """Get knowledge manager for a project, or None if no knowledge base exists."""
    knowledge_dir = _get_knowledge_dir()
    if not knowledge_dir.exists():
        return None
    return KnowledgeManager(knowledge_dir, project_name=project)


def _render_markdown(content: str) -> str:
    """Render markdown to HTML with syntax highlighting.

    Strips YAML front matter (if present) before rendering.
    """
    # Strip YAML front matter
    content = content.strip()
    if content.startswith("---"):
        second_delim = content.find("---", 3)
        if second_delim != -1:
            content = content[second_delim + 3 :].strip()

    if not MARKDOWN_AVAILABLE:
        # Fallback: wrap in pre tag
        import html

        return f"<pre>{html.escape(content)}</pre>"

    extensions = [
        FencedCodeExtension(),
        CodeHiliteExtension(css_class="highlight", guess_lang=False),
        "tables",
        "toc",
    ]
    return markdown.markdown(content, extensions=extensions)


@app.get("/api/projects/{project}/knowledge/summary")
def get_knowledge_summary(project: str):
    """Get summary statistics for a project's knowledge base."""
    manager = _get_knowledge_manager(project)
    if manager is None:
        return {
            "exists": False,
            "total_entries": 0,
            "categories_count": 0,
            "avg_rating": None,
            "entries_by_category": {},
            "top_keywords": [],
            "version_distribution": {},
        }

    all_metadata = manager.get_all_metadata()

    # Count entries by top-level category
    entries_by_category: dict[str, int] = {}
    for meta in all_metadata:
        if meta.category_path:
            top_cat = meta.category_path[0]
        else:
            top_cat = "uncategorized"
        entries_by_category[top_cat] = entries_by_category.get(top_cat, 0) + 1

    # Calculate average rating
    all_ratings = []
    for meta in all_metadata:
        for version_ratings in meta.usefulness_ratings:
            all_ratings.extend(version_ratings)
    avg_rating = sum(all_ratings) / len(all_ratings) if all_ratings else None

    # Count top keywords
    keyword_counts: dict[str, int] = {}
    for meta in all_metadata:
        for kw in meta.keywords:
            keyword_counts[kw] = keyword_counts.get(kw, 0) + 1
    top_keywords = sorted(keyword_counts.items(), key=lambda x: -x[1])[:20]

    # Version distribution
    version_dist: dict[str, int] = {}
    for meta in all_metadata:
        v = str(meta.version)
        version_dist[v] = version_dist.get(v, 0) + 1

    return {
        "exists": True,
        "total_entries": len(all_metadata),
        "categories_count": len(entries_by_category),
        "avg_rating": round(avg_rating, 2) if avg_rating is not None else None,
        "entries_by_category": entries_by_category,
        "top_keywords": [{"keyword": kw, "count": count} for kw, count in top_keywords],
        "version_distribution": version_dist,
    }


@app.get("/api/projects/{project}/knowledge/tree")
def get_knowledge_tree(project: str):
    """Get the knowledge tree structure for a project."""
    manager = _get_knowledge_manager(project)
    if manager is None:
        return {"tree": {}}

    tree = manager.get_knowledge_tree()
    return {"tree": tree}


@app.get("/api/projects/{project}/knowledge/entries")
def get_knowledge_entries(
    project: str,
    category: str | None = None,
    search: str | None = None,
    sort_by: str = "rating",
):
    """List knowledge entries for a project.

    Args:
        project: Project name
        category: Filter by top-level category (optional)
        search: Search in keywords and file paths (optional)
        sort_by: Sort by 'rating', 'name', 'updated', or 'iterations'
    """
    manager = _get_knowledge_manager(project)
    if manager is None:
        return {"items": []}

    all_metadata = manager.get_all_metadata()
    items = []

    for meta in all_metadata:
        # Filter by category
        if category:
            if not meta.category_path or meta.category_path[0] != category:
                continue

        # Filter by search term
        if search:
            search_lower = search.lower()
            path_match = search_lower in meta.file_path.lower()
            keyword_match = any(search_lower in kw.lower() for kw in meta.keywords)
            if not path_match and not keyword_match:
                continue

        avg_rating = meta.get_average_rating()
        items.append(
            {
                "file_path": meta.file_path,
                "name": Path(meta.file_path).stem,
                "category_path": meta.category_path,
                "keywords": meta.keywords[:5],  # Limit for display
                "version": meta.version,
                "avg_rating": round(avg_rating, 2) if avg_rating is not None else None,
                "iterations_survived": meta.iterations_survived,
                "updated_at": meta.updated_at,
            }
        )

    # Sort items
    if sort_by == "rating":
        items.sort(key=lambda x: (-(x.get("avg_rating") or -100), x["name"]))
    elif sort_by == "name":
        items.sort(key=lambda x: x["name"].lower())
    elif sort_by == "updated":
        items.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    elif sort_by == "iterations":
        items.sort(key=lambda x: (-x.get("iterations_survived", 0), x["name"]))

    return {"items": items}


@app.get("/api/projects/{project}/knowledge/entries/{path:path}")
def get_knowledge_entry_detail(project: str, path: str):
    """Get details for a specific knowledge entry.

    Args:
        project: Project name
        path: Relative file path (e.g., 'wasmtime/codegen/example.md')
    """
    manager = _get_knowledge_manager(project)
    if manager is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    # Ensure .md extension
    if not path.endswith(".md"):
        path = path + ".md"

    metadata = manager.get_metadata(path)
    if metadata is None:
        raise HTTPException(status_code=404, detail="Entry not found")

    content = manager.get_content(path)
    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")

    # Render markdown to HTML
    content_html = _render_markdown(content)

    # Get all ratings flattened
    all_ratings = []
    for version_ratings in metadata.usefulness_ratings:
        all_ratings.extend(version_ratings)

    return {
        "file_path": metadata.file_path,
        "name": Path(metadata.file_path).stem,
        "category_path": metadata.category_path,
        "knowledge_type": metadata.knowledge_type.value,
        "keywords": metadata.keywords,
        "content": content,
        "content_html": content_html,
        "version": metadata.version,
        "avg_rating": round(metadata.get_average_rating(), 2) if metadata.get_average_rating() is not None else None,
        "all_ratings": all_ratings,
        "iterations_survived": metadata.iterations_survived,
        "source_generations": metadata.source_generations[-5:],  # Last 5 sources
        "source_success_flags": metadata.source_success_flags[-5:],
        "created_at": metadata.created_at,
        "updated_at": metadata.updated_at,
    }


@app.get("/api/projects/{project}/knowledge/archive")
def get_knowledge_archive(project: str):
    """List archived knowledge entries for a project."""
    manager = _get_knowledge_manager(project)
    if manager is None:
        return {"items": []}

    archived = manager.list_archived_knowledge()
    return {"items": archived}


@app.get("/api/knowledge/shared")
def get_shared_knowledge():
    """Get shared knowledge entries (command_line_tools, language_specific)."""
    from anypoc.core.knowledge import SHARED_CATEGORIES

    knowledge_dir = _get_knowledge_dir()
    if not knowledge_dir.exists():
        return {"exists": False, "entries": [], "categories": list(SHARED_CATEGORIES)}

    manager = KnowledgeManager(knowledge_dir)  # No project_name — shared only
    all_metadata = manager.get_all_metadata()

    entries = []
    for meta in all_metadata:
        if not meta.category_path:
            continue
        top = meta.category_path[0]
        if top not in SHARED_CATEGORIES:
            continue
        avg_rating = meta.get_average_rating()
        entries.append(
            {
                "file_path": meta.file_path,
                "name": Path(meta.file_path).stem,
                "category_path": meta.category_path,
                "keywords": meta.keywords[:5],
                "version": meta.version,
                "avg_rating": round(avg_rating, 2) if avg_rating is not None else None,
                "iterations_survived": meta.iterations_survived,
                "updated_at": meta.updated_at,
            }
        )

    return {"exists": True, "entries": entries, "categories": list(SHARED_CATEGORIES)}


class AnnotationUpdate(BaseModel):
    status: str
    notes: str = ""


POC_ANNOTATION_STATUSES = ("unchecked", "To Report", "Reported", "Invalid", "Skipped", "Known", "WIP")


def _load_poc_annotation(poc_path: Path) -> dict[str, Any]:
    """Load annotation for a raw PoC entry, or return defaults."""
    annotation_path = poc_path / "annotation.json"
    if annotation_path.exists():
        try:
            data = json.loads(annotation_path.read_text())
            return {
                "status": data.get("status", "unchecked"),
                "notes": data.get("notes", ""),
            }
        except Exception:
            pass
    return {"status": "unchecked", "notes": ""}


@app.post("/api/projects/{project}/monitor/pocs/{name}/annotation")
def update_poc_annotation(project: str, name: str, update: AnnotationUpdate):
    """Update the annotation for a raw PoC entry."""
    output_dir = _get_output_dir(project)
    poc_path = output_dir / "poc" / name

    if not poc_path.is_dir():
        raise HTTPException(status_code=404, detail="PoC not found")

    if update.status not in POC_ANNOTATION_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {POC_ANNOTATION_STATUSES}")

    annotation_path = poc_path / "annotation.json"
    annotation_data = {
        "poc_name": name,
        "status": update.status,
        "notes": update.notes,
        "updated_at": datetime.now().isoformat(),
    }
    annotation_path.write_text(json.dumps(annotation_data, indent=2))

    return {"success": True, "poc_name": name}


# Cost endpoints


@app.get("/api/costs")
def get_costs(
    page: int = 1,
    page_size: int = 10,
    start_time: str | None = None,
    end_time: str | None = None,
    time_field: str | None = None,
    model_filter: str | None = None,
):
    """Get aggregated cost data across all projects."""
    # Validate model_filter
    parsed_model_filter = (model_filter or "all").lower()
    if parsed_model_filter not in ("bedrock", "non_bedrock", "all"):
        raise HTTPException(status_code=400, detail="model_filter must be 'bedrock', 'non_bedrock', or 'all'")

    def _model_matches(model_name: str) -> bool:
        if parsed_model_filter == "all":
            return True
        is_bedrock = "us.anthropic" in model_name
        return is_bedrock if parsed_model_filter == "bedrock" else not is_bedrock

    start_ts = _parse_time_bound(start_time, field_name="start_time")
    end_ts = _parse_time_bound(end_time, field_name="end_time")
    parsed_time_field = _parse_time_field(time_field)
    if start_ts is not None and end_ts is not None and start_ts > end_ts:
        raise HTTPException(status_code=400, detail="start_time must be before or equal to end_time")

    if not PROJECTS_DIR.exists():
        return {
            "total_cost": 0.0,
            "by_task": {"sources": 0.0, "patterns": 0.0, "bugs": 0.0, "pocs": 0.0},
            "by_project": [],
            "top_trajs": [],
            "total_trajs": 0,
            "time_field": parsed_time_field,
            "page": page,
            "page_size": page_size,
        }

    project_dirs = [
        p
        for p in sorted(PROJECTS_DIR.iterdir())
        if p.is_dir() and not p.name.startswith(".") and (p / "Dockerfile").exists()
    ]

    total_bugs = 0.0
    total_pocs = 0.0
    count_bugs = 0
    count_pocs = 0
    by_project = []
    all_trajs: list[dict[str, Any]] = []

    for project_dir in project_dirs:
        project = project_dir.name
        output_dir = _get_output_dir(project)
        if not output_dir.is_dir():
            continue

        # Bugs cost (across all scan jobs)
        bugs_cost = 0.0
        proj_bugs_count = 0
        for bug_reports_dir in _iter_scan_log_dirs(output_dir):
            for traj_file in bug_reports_dir.rglob("*.traj.json"):
                if not _traj_matches_time_range(traj_file, start_ts, end_ts, parsed_time_field):
                    continue
                fs = FastStats.from_path(traj_file)
                if fs is None or not _model_matches(fs.model):
                    continue
                cost = fs.cost_usd
                bugs_cost += cost
                proj_bugs_count += 1
                all_trajs.append(
                    {
                        "traj_path": str(traj_file.relative_to(output_dir)),
                        "abs_path": str(traj_file),
                        "cost": cost,
                        "project": project,
                    }
                )

        # PoCs cost
        pocs_cost = 0.0
        proj_pocs_count = 0
        poc_paths = _list_pocs(output_dir)
        for poc_path in poc_paths:
            for traj_file in poc_path.rglob("*.traj.json"):
                if not _traj_matches_time_range(traj_file, start_ts, end_ts, parsed_time_field):
                    continue
                fs = FastStats.from_path(traj_file)
                if fs is None or not _model_matches(fs.model):
                    continue
                cost = fs.cost_usd
                pocs_cost += cost
                proj_pocs_count += 1
                all_trajs.append(
                    {
                        "traj_path": str(traj_file.relative_to(output_dir)),
                        "abs_path": str(traj_file),
                        "cost": cost,
                        "project": project,
                    }
                )

        project_total = bugs_cost + pocs_cost
        project_count = proj_bugs_count + proj_pocs_count
        if project_total > 0:
            by_project.append(
                {
                    "project": project,
                    "bugs_cost": bugs_cost,
                    "pocs_cost": pocs_cost,
                    "total_cost": project_total,
                    "total_trajs": project_count,
                }
            )

        total_bugs += bugs_cost
        total_pocs += pocs_cost
        count_bugs += proj_bugs_count
        count_pocs += proj_pocs_count

    # Sort trajs by cost descending, deduplicate by abs_path
    seen_paths: set[str] = set()
    unique_trajs = []
    for t in all_trajs:
        if t["abs_path"] not in seen_paths:
            seen_paths.add(t["abs_path"])
            unique_trajs.append(t)
    unique_trajs.sort(key=lambda t: t["cost"], reverse=True)

    total_trajs = len(unique_trajs)
    start = (page - 1) * page_size
    top_trajs = unique_trajs[start : start + page_size]

    by_project.sort(key=lambda p: p["total_cost"], reverse=True)

    total_cost = total_bugs + total_pocs
    return {
        "total_cost": total_cost,
        "total_trajs": total_trajs,
        "time_field": parsed_time_field,
        "by_task": {
            "bugs": {"cost": total_bugs, "trajs": count_bugs},
            "pocs": {"cost": total_pocs, "trajs": count_pocs},
        },
        "by_project": by_project,
        "top_trajs": top_trajs,
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# Spend-limit endpoints
# ---------------------------------------------------------------------------


class SpendLimitBody(BaseModel):
    limit: float


@app.get("/api/spend-limits")
def get_spend_limits():
    """Return overall + per-project spend limits and current spend."""
    gstore = GlobalCostStore.load()

    # Collect per-project data
    projects: list[dict[str, Any]] = []
    if OUTPUT_BASE_DIR.exists():
        for d in sorted(OUTPUT_BASE_DIR.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            pstore = ProjectCostStore.load(d.name)
            projects.append(
                {
                    "name": d.name,
                    "limit": gstore.get_project_limit(d.name),
                    "total_cost": pstore.total_cost,
                    "tasks": pstore.tasks,
                }
            )

    return {
        "overall_limit": gstore.overall_limit,
        "overall_total_cost": gstore.overall_total_cost,
        "projects": projects,
    }


@app.put("/api/spend-limits/overall")
def set_overall_spend_limit(body: SpendLimitBody):
    """Set (or update) the overall spend limit."""
    gstore = GlobalCostStore.load()
    gstore.overall_limit = body.limit
    gstore.save()
    return {"ok": True, "overall_limit": body.limit}


@app.delete("/api/spend-limits/overall")
def clear_overall_spend_limit():
    """Remove the overall spend limit."""
    gstore = GlobalCostStore.load()
    gstore.overall_limit = None
    gstore.save()
    return {"ok": True}


@app.put("/api/spend-limits/project/{project}")
def set_project_spend_limit(project: str, body: SpendLimitBody):
    """Set (or update) a per-project spend limit."""
    gstore = GlobalCostStore.load()
    gstore.set_project_limit(project, body.limit)
    gstore.save()
    return {"ok": True, "project": project, "limit": body.limit}


@app.delete("/api/spend-limits/project/{project}")
def clear_project_spend_limit(project: str):
    """Remove a per-project spend limit."""
    gstore = GlobalCostStore.load()
    gstore.set_project_limit(project, None)
    gstore.save()
    return {"ok": True, "project": project}


@app.post("/api/spend-limits/reset/overall")
def reset_overall_spend():
    """Zero the overall spend counter (does not change limit)."""
    gstore = GlobalCostStore.load()
    gstore.overall_total_cost = 0.0
    gstore.save()
    return {"ok": True}


@app.post("/api/spend-limits/reset/project/{project}")
def reset_project_spend(project: str):
    """Zero all task counters for a project (does not change limit)."""
    pstore = ProjectCostStore.load(project)
    pstore.reset()
    pstore.save()
    return {"ok": True, "project": project}
