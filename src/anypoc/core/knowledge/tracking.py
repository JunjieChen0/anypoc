"""Knowledge summary utilities for usage and extraction tracking."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from anypoc.utils import logger

LOG_PREFIX = "[KnowledgeTracker]"


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warn(f"{LOG_PREFIX} Failed to load summary {path}: {exc}")
        return None


def _parse_ratings(raw: Any) -> list[dict[str, Any]]:
    ratings: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return ratings
    for item in raw:
        if isinstance(item, dict):
            file_path = item.get("file_path")
            score = item.get("score")
            if file_path and score is not None:
                try:
                    ratings.append({"file_path": str(file_path), "score": float(score)})
                except (TypeError, ValueError):
                    continue
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            file_path, score = item[0], item[1]
            if file_path and score is not None:
                try:
                    ratings.append({"file_path": str(file_path), "score": float(score)})
                except (TypeError, ValueError):
                    continue
    return ratings


def _normalize_ratings(
    ratings: list[dict[str, Any]] | list[tuple[str, float]],
) -> list[dict[str, Any]]:
    """Normalize rating records to dicts with file_path/score/timestamp (optional)."""
    normalized: list[dict[str, Any]] = []
    for rating in ratings:
        if isinstance(rating, dict):
            file_path = rating.get("file_path")
            score = rating.get("score")
            if not file_path or score is None:
                continue
            try:
                record = {"file_path": str(file_path), "score": float(score)}
            except (TypeError, ValueError):
                continue
            if "timestamp" in rating:
                record["timestamp"] = rating["timestamp"]
            normalized.append(record)
        elif isinstance(rating, (list, tuple)) and len(rating) >= 2:
            file_path, score = rating[0], rating[1]
            if not file_path or score is None:
                continue
            try:
                normalized.append({"file_path": str(file_path), "score": float(score)})
            except (TypeError, ValueError):
                continue
    return normalized


def _dedupe_ratings(ratings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the most recent rating per file_path."""
    deduped: dict[str, dict[str, Any]] = {}
    for rating in ratings:
        file_path = rating.get("file_path")
        if file_path:
            deduped[str(file_path)] = rating
    return list(deduped.values())


def _load_usage_summary(summary_dir: Path) -> dict[str, Any] | None:
    summary_path = summary_dir / "knowledge_usage_summary.json"
    if not summary_path.exists():
        return None
    return _load_json(summary_path)


def _load_extraction_summary(summary_dir: Path) -> dict[str, Any] | None:
    summary_path = summary_dir / "knowledge_extractor_summary.json"
    if not summary_path.exists():
        return None
    return _load_json(summary_path)


def get_knowledge_info_for_attempt(attempt_dir: Path) -> dict[str, Any]:
    """
    Get knowledge usage/extraction info for a PoC attempt from summary files.

    Returns:
        Dictionary with:
        - knowledge_usage: {ratings: [...]} or None
        - knowledge_extraction: {reported: [...], updated: [...], ratings: [...]} or None
    """
    result: dict[str, Any] = {
        "knowledge_usage": None,
        "knowledge_extraction": None,
    }

    summary_dir = attempt_dir / "misc"
    if not summary_dir.is_dir():
        return result

    usage_summary = _load_usage_summary(summary_dir)
    if usage_summary:
        ratings = _parse_ratings(usage_summary.get("ratings", []))
        if ratings:
            result["knowledge_usage"] = {"ratings": ratings}

    extraction_summary = _load_extraction_summary(summary_dir)
    if extraction_summary:
        reported = extraction_summary.get("reported_ids") or extraction_summary.get("reported") or []
        updated = extraction_summary.get("updated_ids") or extraction_summary.get("updated") or []
        ratings = _parse_ratings(extraction_summary.get("ratings", []))
        if reported or updated or ratings:
            result["knowledge_extraction"] = {
                "reported": list(reported) if isinstance(reported, list) else [],
                "updated": list(updated) if isinstance(updated, list) else [],
                "ratings": ratings,
            }

    return result
