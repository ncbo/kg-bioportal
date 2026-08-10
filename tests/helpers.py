"""Shared helpers for loading the repo's non-packaged scripts.

``merge_stats.py`` and ``build_site.py`` are standalone scripts rather than
part of the installed package, so tests import them by path.
"""

import importlib.util
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MERGE_STATS = os.path.join(REPO_ROOT, ".github", "scripts", "merge_stats.py")
BUILD_SITE = os.path.join(REPO_ROOT, "docs", "kg_site", "build_site.py")


def load_script(path, name):
    """Import a .py file by path, without it needing to be on sys.path."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
