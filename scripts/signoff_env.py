#!/usr/bin/env python3
"""Fail unless sign-off is using the repository's pinned Nix environment."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


NIX_STORE = Path("/nix/store")
REPO_ROOT = Path(__file__).resolve().parent.parent


def verify_nix_shell() -> None:
    if not os.environ.get("IN_NIX_SHELL"):
        raise SystemExit(
            "sign-off must run inside the gf180characterization Nix shell; use "
            "`nix develop --accept-flake-config --command make ...`"
        )

    project_root = os.environ.get("PRJ_ROOT")
    if project_root is None or Path(project_root).resolve() != REPO_ROOT:
        raise SystemExit(
            "refusing a Nix shell not rooted at this gf180characterization "
            f"checkout ({REPO_ROOT})"
        )

    for variable in ("NIX_GCROOT", "DEVSHELL_DIR"):
        value = os.environ.get(variable)
        if value is None or not Path(value).resolve().is_relative_to(NIX_STORE):
            raise SystemExit(
                f"refusing Nix environment without a repository devshell {variable}"
            )


def nix_tool(name: str) -> Path:
    executable = shutil.which(name)
    if executable is None:
        raise SystemExit(f"required sign-off tool is missing: {name}")
    resolved = Path(executable).resolve()
    if not resolved.is_relative_to(NIX_STORE):
        raise SystemExit(
            f"refusing host sign-off tool {name}={resolved}; run through "
            "`nix develop --accept-flake-config --command ...`"
        )
    return resolved


def git_head(path: Path, git: Path) -> str:
    result = subprocess.run(
        [str(git), "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def verify_dependency(path: Path, expected: str, git: Path) -> str:
    if not (path / ".git").exists():
        raise SystemExit(f"pinned sign-off dependency is missing: {path}")
    actual = git_head(path, git)
    if actual != expected:
        raise SystemExit(
            f"sign-off dependency {path} is at {actual}, expected {expected}"
        )
    return actual


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", action="append", default=[])
    parser.add_argument(
        "--dependency",
        action="append",
        nargs=2,
        default=[],
        metavar=("PATH", "COMMIT"),
    )
    args = parser.parse_args()

    verify_nix_shell()
    python = Path(sys.executable).resolve()
    if not python.is_relative_to(NIX_STORE):
        raise SystemExit(f"refusing host Python for sign-off: {python}")

    requested_tools = list(dict.fromkeys(args.tool))
    if args.dependency and "git" not in requested_tools:
        requested_tools.append("git")
    tools = {name: nix_tool(name) for name in requested_tools}
    dependencies = {
        str(Path(path).resolve()): verify_dependency(
            Path(path).resolve(), commit, tools["git"]
        )
        for path, commit in args.dependency
    }
    print(f"sign-off Python: {python}")
    for name, path in tools.items():
        print(f"sign-off {name}: {path}")
    for path, commit in dependencies.items():
        print(f"sign-off dependency: {path} @ {commit}")


if __name__ == "__main__":
    main()
