from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


def load_callable(entrypoint: str) -> Any:
    """Load `path/to/file.py:function_name`."""
    path_text, function_name = entrypoint.split(":", maxsplit=1)
    path = Path(path_text)

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


def run_entrypoint(entrypoint: str, args: list[str]) -> Any:
    fn = load_callable(entrypoint)
    return fn(*args)
