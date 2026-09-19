#!/usr/bin/env python3
"""
ytstr - YouTube & YouTube Music Streamer with Automatic Spectral-DJ Transitions
================================================================================
Copyright (C) 2026 Sujay Seeram

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""
import os
import shutil
import sys

# ---------------------------------------------------------------------------
# Self-Bootstrapping: Auto-switch to project's uv virtual environment
# ---------------------------------------------------------------------------
repo_root = os.path.dirname(os.path.abspath(__file__))
venv_python = os.path.join(repo_root, ".venv", "bin", "python")

if __name__ == "__main__":
    if os.path.exists(venv_python) and os.path.realpath(sys.executable) != os.path.realpath(venv_python):
        os.execv(venv_python, [venv_python] + sys.argv)
    elif not os.path.exists(venv_python) and shutil.which("uv"):
        os.execvp("uv", ["uv", "--directory", repo_root, "run", sys.argv[0]] + sys.argv[1:])

# Make ytstr.py act as a package proxy if imported accidentally
src_pkg = os.path.join(repo_root, "src", "ytstr")
__path__ = [src_pkg]

src_dir = os.path.join(repo_root, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

if __name__ == "__main__":
    from ytstr.cli import main
    sys.exit(main())
