from __future__ import annotations

from .paths import functions_dir, tests_dir
from .provider import GeneratedFunction
from .registry import FunctionRecord, Registry


def write_generated_function(generated: GeneratedFunction, registry: Registry) -> FunctionRecord:
    function_file = functions_dir() / f"{generated.canonical_name}.py"
    test_file = tests_dir() / f"test_{generated.canonical_name}.py"

    if function_file.exists():
        raise FileExistsError(f"Function file already exists: {function_file}")

    function_file.write_text(generated.code, encoding="utf-8")
    test_file.write_text(generated.tests, encoding="utf-8")

    record = FunctionRecord(
        canonical_name=generated.canonical_name,
        entrypoint=str(function_file) + f":{generated.canonical_name}",
        description=generated.description,
        signature=generated.signature,
        aliases=[],
        tags=generated.tags,
        version=1,
    )
    registry.add(record)
    registry.save()
    return record
