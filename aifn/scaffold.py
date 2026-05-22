from __future__ import annotations

from pathlib import Path

from .paths import functions_dir, project_root, tests_dir
from .provider import GeneratedFunction
from .registry import FunctionRecord, Registry
from .runner import resolve_entrypoint_path


def write_generated_function(
    generated: GeneratedFunction, registry: Registry
) -> FunctionRecord:
    extension = ".sh" if generated.language == "bash" else ".py"
    function_file = functions_dir() / f"{generated.canonical_name}{extension}"
    test_file = tests_dir() / f"test_{generated.canonical_name}.py"

    if function_file.exists():
        raise FileExistsError(f"Function file already exists: {function_file}")

    function_file.write_text(generated.code, encoding="utf-8")
    test_file.write_text(generated.tests, encoding="utf-8")
    relative_function_path = function_file.relative_to(project_root())

    record = FunctionRecord(
        canonical_name=generated.canonical_name,
        entrypoint=f"{relative_function_path}:{generated.canonical_name}",
        description=generated.description,
        signature=generated.signature,
        aliases=[],
        tags=generated.tags,
        version=1,
        language=generated.language,
    )
    registry.add(record)
    registry.save()
    return record


def update_generated_function(
    record: FunctionRecord,
    generated: GeneratedFunction,
    registry: Registry,
) -> FunctionRecord:
    function_file, _ = resolve_entrypoint_path(record.entrypoint)
    test_file = tests_dir() / f"test_{record.canonical_name}.py"

    if not function_file.exists():
        raise FileNotFoundError(f"Function file not found: {function_file}")

    function_file.write_text(generated.code, encoding="utf-8")
    test_file.write_text(generated.tests, encoding="utf-8")

    record.description = generated.description
    record.signature = generated.signature
    record.tags = generated.tags
    record.language = generated.language
    record.version += 1
    registry.save()
    return record


def remove_generated_function(record: FunctionRecord, registry: Registry) -> None:
    function_file, _ = resolve_entrypoint_path(record.entrypoint)
    test_file = tests_dir() / f"test_{record.canonical_name}.py"

    function_file.unlink(missing_ok=True)
    test_file.unlink(missing_ok=True)
    registry.records.pop(record.canonical_name, None)
    registry.save()


def rename_generated_function(
    record: FunctionRecord, new_name: str, registry: Registry
) -> FunctionRecord:
    function_file, function_name = resolve_entrypoint_path(record.entrypoint)
    old_name = record.canonical_name
    renamed_function_file = function_file.with_name(f"{new_name}{function_file.suffix}")
    old_test_file = tests_dir() / f"test_{old_name}.py"
    renamed_test_file = tests_dir() / f"test_{new_name}.py"

    if renamed_function_file != function_file:
        function_file.replace(renamed_function_file)
    if old_test_file.exists() and renamed_test_file != old_test_file:
        old_test_file.replace(renamed_test_file)

    record = registry.rename(record, new_name)
    record.entrypoint = (
        f"{_rename_entrypoint_path(record.entrypoint, new_name)}:{function_name}"
    )
    registry.save()
    return record


def _rename_entrypoint_path(entrypoint: str, new_name: str) -> str:
    path_text, _ = entrypoint.split(":", maxsplit=1)
    return str(Path(path_text).with_name(f"{new_name}.py"))
