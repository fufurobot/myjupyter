"""Toolchain marker for the unix/macos/3.13 target.

This module exists so that every target directory is a real, importable,
buildable Python project: CI requires `python -m build` to succeed for each
``<platform>/<distro>/<python-version>`` combination.
"""

__all__ = ["TARGET"]

TARGET = {
    "platform": "unix",
    "distro": "macos",
    "python": "3.13",
}
