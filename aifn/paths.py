from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    return Path.cwd()


def aifn_dir() -> Path:
    return project_root() / ".aifn"


def registry_path() -> Path:
    return aifn_dir() / "registry.json"


def functions_dir() -> Path:
    return aifn_dir() / "functions"


def tests_dir() -> Path:
    return aifn_dir() / "tests"
