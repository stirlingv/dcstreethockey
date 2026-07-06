"""
Guard test enforcing consistent sport terminology across the codebase.

DC Street Hockey is street hockey (a.k.a. ball hockey) — never "ice hockey"
or "floor hockey", and players are never "skaters". See the Terminology
section of CLAUDE.md. This test scans the project's Python and template
source so banned wording can't silently creep back in.
"""

import os
import re

from django.test import SimpleTestCase

# Repo root: this file lives at <root>/core/tests/test_terminology.py
REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)

# Words/phrases that must never appear in code or templates.
FORBIDDEN = re.compile(
    r"\b(skaters?|skating|floor[\s-]?hockey|ice[\s-]?hockey|field player)\b",
    re.IGNORECASE,
)

# Only source we author and ship. (Docs like CLAUDE.md legitimately quote the
# banned words to define them, so Markdown is intentionally excluded.)
SCAN_EXTENSIONS = (".py", ".html")

# Directories to skip entirely.
EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    "venv",
    "staticfiles",
    # Applied migrations are historical records — a since-removed field there
    # (SeasonSignup.position_preference) still carries a "Skater" label and
    # must not be edited retroactively.
    "migrations",
}

# This test file necessarily contains the banned words as patterns.
EXCLUDE_FILES = {os.path.abspath(__file__)}


def _iter_source_files():
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for name in filenames:
            if not name.endswith(SCAN_EXTENSIONS):
                continue
            path = os.path.join(dirpath, name)
            if path in EXCLUDE_FILES:
                continue
            yield path


class TerminologyGuardTest(SimpleTestCase):
    """No banned ice/floor-hockey or 'skater' language in source."""

    def test_no_forbidden_terms_in_source(self):
        offenders = []
        for path in _iter_source_files():
            with open(path, encoding="utf-8", errors="ignore") as fh:
                for lineno, line in enumerate(fh, start=1):
                    match = FORBIDDEN.search(line)
                    if match:
                        rel = os.path.relpath(path, REPO_ROOT)
                        offenders.append(f"{rel}:{lineno}: {match.group(0)!r}")

        self.assertEqual(
            offenders,
            [],
            "Banned sport terminology found — use street/ball hockey and "
            "player/forward/defense/goalie instead:\n" + "\n".join(offenders),
        )
