"""Repo-root pytest conftest.

Adds tools/ to sys.path so tests can `import govlib` the same way
tools/gov.py does when it is run directly as a script.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "tools"))
