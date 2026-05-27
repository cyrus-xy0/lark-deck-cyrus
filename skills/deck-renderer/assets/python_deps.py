"""Project-local Python dependency discovery.

install.sh installs optional runtime dependencies into <repo>/.deps/python and
Playwright browser binaries into <repo>/.deps/ms-playwright. Import this helper
before importing optional packages so scripts work without global pip installs.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def find_repo_root(start: Path) -> Path | None:
    path = start.resolve()
    if path.is_file():
        path = path.parent
    for candidate in [path, *path.parents]:
        if (candidate / "requirements.txt").is_file() and (candidate / "skills/deck-renderer/assets").is_dir():
            return candidate
        if candidate.name == "deck-renderer" and candidate.parent.name == "skills":
            return candidate.parent.parent
    return None


def activate_project_python_deps(start: Path | None = None) -> Path | None:
    repo = find_repo_root(start or Path(__file__))
    if repo is None:
        return None

    python_deps = repo / ".deps" / "python"
    if python_deps.is_dir():
        deps_str = str(python_deps)
        if deps_str not in sys.path:
            sys.path.insert(0, deps_str)

    browser_deps = repo / ".deps" / "ms-playwright"
    if browser_deps.is_dir() and not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_deps)

    return repo
