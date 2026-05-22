from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from typing import Any

from .paths import project_root


class InvocationArgumentError(TypeError):
    pass


def resolve_entrypoint_path(entrypoint: str) -> tuple[Path, str]:
    path_text, function_name = entrypoint.split(":", maxsplit=1)
    path = Path(path_text)
    if not path.is_absolute():
        path = project_root() / path
    return path, function_name


def load_callable(entrypoint: str) -> Any:
    """Load `path/to/file.py:function_name`."""
    path, function_name = resolve_entrypoint_path(entrypoint)

    if not path.exists():
        raise FileNotFoundError(f"Function file not found: {path}")

    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    fn = getattr(module, function_name, None)
    if fn is None:
        raise AttributeError(f"Function {function_name!r} not found in {path}")
    if not callable(fn):
        raise TypeError(f"Entrypoint {function_name!r} is not callable")

    return fn


def validate_callable_args(fn: Any, args: list[str]) -> None:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return

    try:
        signature.bind(*args)
    except TypeError as exc:
        raise InvocationArgumentError(str(exc)) from exc


def run_entrypoint(entrypoint: str, args: list[str]) -> Any:
    fn = load_callable(entrypoint)
    validate_callable_args(fn, args)
    return fn(*args)
