"""Toolchain marker for the windows/win7/3.10 target.

This module exists so that every target directory is a real, importable,
buildable Python project: CI requires `python -m build` to succeed for each
``<platform>/<distro>/<python-version>`` combination.
"""

__all__ = ["TARGET"]

TARGET = {
    "platform": "windows",
    "distro": "win7",
    "python": "3.10",
}
