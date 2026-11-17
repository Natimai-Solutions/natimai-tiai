"""The backend runs, and is tested, under one Python.

The image's base (``FROM python:X.Y-slim``) and ``.python-version`` — which
uv, the CI and the developers' environments follow — name the same version.
Dependabot bumps the image alone: without this test, the server would move to a
Python the suite never ran on, and a dependency without wheels for it would
only show when the image is built (psycopg-binary on 3.15, November 2026).
"""

import os
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _image_python() -> str:
    dockerfile = (BACKEND / "Dockerfile").read_text()
    match = re.search(r"^FROM python:(\d+\.\d+)", dockerfile, re.MULTILINE)
    assert match, "the backend image is no longer built FROM python:X.Y"
    return match.group(1)


def test_the_image_and_python_version_name_the_same_python():
    pinned = (BACKEND / ".python-version").read_text().strip()
    assert _image_python() == pinned, (
        f"backend/Dockerfile builds on Python {_image_python()}, "
        f".python-version says {pinned}: bump both together"
    )


def test_the_ci_runs_the_suite_under_the_image_python():
    # On a developer's machine an older environment may still be in use; the
    # CI is where the version the image ships must be the one tested.
    if not os.environ.get("CI"):
        return
    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert running == _image_python(), (
        f"the suite runs under Python {running}, the image ships {_image_python()}"
    )
