from pathlib import Path

from aifn.provider import GeneratedFunction
from aifn.registry import Registry
from aifn.runner import load_callable, resolve_entrypoint_path
from aifn.scaffold import write_generated_function


def test_resolve_entrypoint_path_supports_relative_paths(monkeypatch, tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    function_file = project_dir / ".aifn" / "functions" / "slugify.py"
    function_file.parent.mkdir(parents=True)
    function_file.write_text(
        "def slugify(*args):\n    return '-'.join(args)\n", encoding="utf-8"
    )

    monkeypatch.setattr("aifn.runner.project_root", lambda: project_dir)

    path, function_name = resolve_entrypoint_path(".aifn/functions/slugify.py:slugify")

    assert path == function_file
    assert function_name == "slugify"
    assert (
        load_callable(".aifn/functions/slugify.py:slugify")("Hello", "World")
        == "Hello-World"
    )


def test_write_generated_function_stores_relative_entrypoint(monkeypatch, tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    aifn_dir = project_dir / ".aifn"
    functions_dir = aifn_dir / "functions"
    tests_dir = aifn_dir / "tests"
    functions_dir.mkdir(parents=True)
    tests_dir.mkdir(parents=True)
    registry = Registry(path=aifn_dir / "registry.json")

    monkeypatch.setattr("aifn.scaffold.project_root", lambda: project_dir)
    monkeypatch.setattr("aifn.scaffold.functions_dir", lambda: functions_dir)
    monkeypatch.setattr("aifn.scaffold.tests_dir", lambda: tests_dir)

    generated = GeneratedFunction(
        canonical_name="slugify",
        code="def slugify(*args: str) -> str:\n    return '-'.join(args)\n",
        tests="def test_placeholder():\n    assert True\n",
        description="Convert text to a slug",
        signature="slugify(*args: str) -> str",
        tags=["text"],
    )

    record = write_generated_function(generated, registry)

    assert record.entrypoint == ".aifn/functions/slugify.py:slugify"
    assert (
        registry.records["slugify"].entrypoint == ".aifn/functions/slugify.py:slugify"
    )
    assert Path(record.entrypoint.split(":", maxsplit=1)[0]).is_absolute() is False
