"""Shared constants for the knowledge base."""

SHARED_CATEGORIES = (
    "command_line_tools",
    "language_specific",
)

PROJECT_CATEGORIES = (
    "build",
    "internal_tools",
    "test_frameworks",
    "code",
    "poc_forms",
)

LANGUAGE_SUBDIRS = ("c", "cpp", "rust")

# Knowledge filter settings
CODE_FILTER_MAX_BUG_REPORT_CHARS = 6000

# All valid top-level paths an agent can use
ALL_VALID_CATEGORIES = SHARED_CATEGORIES + PROJECT_CATEGORIES
