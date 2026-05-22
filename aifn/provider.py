from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class GeneratedFunction:
    canonical_name: str
    code: str
    tests: str
    description: str
    signature: str
    tags: list[str]
    language: str = "python"


@dataclass
class ResolutionDecision:
    action: str
    canonical_name: str | None = None
    reason: str = ""
    review_required: bool = False


class FunctionProvider(Protocol):
    def resolve_missing_function(
        self,
        name: str,
        args: list[str],
        description: str | None = None,
        existing_capabilities: list[dict[str, Any]] | None = None,
        similar_capabilities: list[dict[str, Any]] | None = None,
    ) -> ResolutionDecision: ...

    def generate_function(
        self,
        name: str,
        args: list[str],
        description: str | None = None,
        existing_capabilities: list[dict[str, Any]] | None = None,
        language: str = "python",
    ) -> GeneratedFunction: ...

    def edit_function(
        self,
        name: str,
        args: list[str],
        current_code: str,
        current_tests: str,
        description: str | None = None,
        existing_capabilities: list[dict[str, Any]] | None = None,
        language: str = "python",
    ) -> GeneratedFunction: ...


class PlaceholderProvider:
    def resolve_missing_function(
        self,
        name: str,
        args: list[str],
        description: str | None = None,
        existing_capabilities: list[dict[str, Any]] | None = None,
        similar_capabilities: list[dict[str, Any]] | None = None,
    ) -> ResolutionDecision:
        del name, args, description, existing_capabilities
        return ResolutionDecision(
            action="generate",
            reason="Placeholder provider cannot classify ambiguous requests.",
            review_required=bool(similar_capabilities),
        )

    def generate_function(
        self,
        name: str,
        _args: list[str],
        description: str | None = None,
        _existing_capabilities: list[dict[str, Any]] | None = None,
        language: str = "python",
    ) -> GeneratedFunction:
        function_name = safe_python_identifier(name)
        desc = description or f"Generated placeholder function for {function_name}."

        if language == "bash":
            code = f'''#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' "{function_name}($*)"
'''
            tests = f'''from aifn.runner import run_entrypoint


def test_{function_name}_placeholder():
    assert (
        run_entrypoint(".aifn/functions/{function_name}.sh:{function_name}", ["hello"])
        == "{function_name}(hello)"
    )
'''
            signature = f'{function_name} "$@"'
        else:
            code = f'''from __future__ import annotations


def {function_name}(*args: str) -> str:
    """{desc}"""
    return "{function_name}(" + ", ".join(args) + ")"
'''

            tests = f"""from pathlib import Path
import importlib.util


def load_function():
    path = Path(__file__).parents[1] / "functions" / "{function_name}.py"
    spec = importlib.util.spec_from_file_location("{function_name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.{function_name}


def test_{function_name}_placeholder():
    fn = load_function()
    assert fn("hello") == "{function_name}(hello)"
"""
            signature = f"{function_name}(*args: str) -> str"

        return GeneratedFunction(
            canonical_name=function_name,
            code=code,
            tests=tests,
            description=desc,
            signature=signature,
            tags=[],
            language=language,
        )

    def edit_function(
        self,
        name: str,
        args: list[str],
        current_code: str,
        current_tests: str,
        description: str | None = None,
        existing_capabilities: list[dict[str, Any]] | None = None,
        language: str = "python",
    ) -> GeneratedFunction:
        del (
            name,
            args,
            current_code,
            current_tests,
            description,
            existing_capabilities,
            language,
        )
        raise RuntimeError(
            "Editing existing functions requires an AI provider. Configure `openai` first."
        )


class OpenAIProvider:
    def __init__(self, model: str | None = None, fast_model: str | None = None) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "OpenAI provider requires the `openai` package. Run: pip install -e '.[openai]'"
            ) from exc

        self.client = OpenAI()
        self.main_model = (
            model
            or os.getenv("AIFN_MAIN_MODEL")
            or os.getenv("AIFN_OPENAI_MODEL")
            or "gpt-5.4-mini"
        )
        self.fast_model = fast_model or os.getenv("AIFN_FAST_MODEL") or "gpt-5.4-nano"

    def resolve_missing_function(
        self,
        name: str,
        args: list[str],
        description: str | None = None,
        existing_capabilities: list[dict[str, Any]] | None = None,
        similar_capabilities: list[dict[str, Any]] | None = None,
    ) -> ResolutionDecision:
        del existing_capabilities
        requested_name = safe_python_identifier(name)
        candidates = similar_capabilities or []

        direct_match = find_programmatic_alias_match(requested_name, candidates)
        if direct_match:
            return ResolutionDecision(
                action="alias",
                canonical_name=direct_match,
                reason="Matched an existing capability using normalized names.",
            )

        if not candidates:
            return ResolutionDecision(
                action="generate",
                reason="No similar capabilities found.",
            )

        prompt = build_resolution_prompt(
            requested_name=requested_name,
            args=args,
            description=description,
            similar_capabilities=candidates,
        )
        payload = self._json_response(model=self.fast_model, prompt=prompt)
        action = payload.get("action", "generate")
        if action == "alias":
            canonical_name = safe_python_identifier(payload["canonical_name"])
            available_names = {
                safe_python_identifier(candidate["canonical_name"])
                for candidate in candidates
                if candidate.get("canonical_name")
            }
            if canonical_name not in available_names:
                raise ValueError(
                    f"Delegation selected unknown canonical function: {canonical_name}"
                )
            return ResolutionDecision(
                action="alias",
                canonical_name=canonical_name,
                reason=payload.get("reason", ""),
            )

        return ResolutionDecision(
            action="generate",
            reason=payload.get("reason", ""),
        )

    def generate_function(
        self,
        name: str,
        args: list[str],
        description: str | None = None,
        existing_capabilities: list[dict[str, Any]] | None = None,
        language: str = "python",
    ) -> GeneratedFunction:
        requested_name = safe_python_identifier(name)
        prompt = build_generation_prompt(
            requested_name=requested_name,
            args=args,
            description=description,
            existing_capabilities=existing_capabilities or [],
            language=language,
        )

        payload = self._json_response(model=self.main_model, prompt=prompt)
        canonical_name = safe_python_identifier(payload["canonical_name"])
        code = payload["code"]
        tests = payload["tests"]

        validate_generated_code(canonical_name, code, language=language)

        return GeneratedFunction(
            canonical_name=canonical_name,
            code=code.rstrip() + "\n",
            tests=tests.rstrip() + "\n",
            description=payload.get("description", description or ""),
            signature=payload.get("signature", f"{canonical_name}(*args: str)"),
            tags=list(payload.get("tags", [])),
            language=language,
        )

    def edit_function(
        self,
        name: str,
        args: list[str],
        current_code: str,
        current_tests: str,
        description: str | None = None,
        existing_capabilities: list[dict[str, Any]] | None = None,
        language: str = "python",
    ) -> GeneratedFunction:
        requested_name = safe_python_identifier(name)
        prompt = build_edit_prompt(
            requested_name=requested_name,
            args=args,
            current_code=current_code,
            current_tests=current_tests,
            description=description,
            existing_capabilities=existing_capabilities or [],
            language=language,
        )

        payload = self._json_response(model=self.main_model, prompt=prompt)
        canonical_name = safe_python_identifier(payload["canonical_name"])
        if canonical_name != requested_name:
            raise ValueError(
                f"Edited function must keep canonical name {requested_name!r}, got {canonical_name!r}"
            )

        code = payload["code"]
        tests = payload["tests"]
        validate_generated_code(canonical_name, code, language=language)

        return GeneratedFunction(
            canonical_name=canonical_name,
            code=code.rstrip() + "\n",
            tests=tests.rstrip() + "\n",
            description=payload.get("description", description or ""),
            signature=payload.get("signature", f"{canonical_name}(*args: str)"),
            tags=list(payload.get("tags", [])),
            language=language,
        )

    def _json_response(self, model: str, prompt: str) -> dict[str, Any]:
        response = self.client.responses.create(
            model=model,
            input=prompt,
        )
        text = getattr(response, "output_text", None)
        if not text:
            text = str(response)
        return parse_json_object(text)


def get_provider(
    name: str | None = None,
    model: str | None = None,
    fast_model: str | None = None,
) -> FunctionProvider:
    provider = (name or os.getenv("AIFN_PROVIDER", "placeholder")).lower()
    if provider == "openai":
        return OpenAIProvider(model=model, fast_model=fast_model)
    if provider == "placeholder":
        return PlaceholderProvider()
    raise ValueError(f"Unknown provider: {provider}")


def build_generation_prompt(
    requested_name: str,
    args: list[str],
    description: str | None,
    existing_capabilities: list[dict[str, Any]],
    language: str,
) -> str:
    rules = generation_rules_for(language)
    test_hint = generated_test_hint_for(language, requested_name)
    return f"""
You are generating a small {language} function for a local CLI tool called aifn.

Return ONLY a valid JSON object with exactly these keys:
- canonical_name: snake_case function name
- description: short human-readable description
- signature: callable signature string for the generated language
- tags: array of short strings
- code: complete source code defining the canonical function in {language}
- tests: complete pytest source code for the function

Rules:
- {rules}
- {test_hint}
- Do not include markdown fences.
- Do not include explanations outside JSON.

Requested function name: {requested_name}
Requested language: {language}
CLI args from current call: {json.dumps(args)}
Optional user description: {description or ""}
Existing capabilities: {json.dumps(existing_capabilities, indent=2)}
""".strip()


def build_resolution_prompt(
    requested_name: str,
    args: list[str],
    description: str | None,
    similar_capabilities: list[dict[str, Any]],
) -> str:
    return f"""
You are triaging a missing CLI function request for a local Python tool.

Return ONLY a valid JSON object with exactly these keys:
- action: either alias or generate
- canonical_name: canonical function name when action is alias, otherwise null
- reason: short explanation

Choose alias only when the requested name is clearly the same capability as one existing function.
Choose generate when the request needs new behavior, broader behavior, or the match is uncertain.
Do not include markdown fences.
Do not include explanations outside JSON.

Requested function name: {requested_name}
CLI args from current call: {json.dumps(args)}
Optional user description: {description or ""}
Similar capabilities: {json.dumps(similar_capabilities, indent=2)}
""".strip()


def build_edit_prompt(
    requested_name: str,
    args: list[str],
    current_code: str,
    current_tests: str,
    description: str | None,
    existing_capabilities: list[dict[str, Any]],
    language: str,
) -> str:
    rules = generation_rules_for(language)
    test_hint = generated_test_hint_for(language, requested_name)
    return f"""
You are updating an existing {language} function for a local CLI tool called aifn.

Return ONLY a valid JSON object with exactly these keys:
- canonical_name: snake_case function name
- description: short human-readable description
- signature: callable signature string for the generated language
- tags: array of short strings
- code: complete source code defining the canonical function in {language}
- tests: complete pytest source code for the function

Rules:
- Keep the canonical function name exactly {requested_name}.
- {rules}
- Update the existing code and tests instead of replacing them with an unrelated implementation.
- {test_hint}
- Do not include markdown fences.
- Do not include explanations outside JSON.

Requested function name: {requested_name}
Requested language: {language}
CLI args from current call: {json.dumps(args)}
Requested change: {description or ''}
Existing capabilities: {json.dumps(existing_capabilities, indent=2)}

Current code:
{current_code}

Current tests:
{current_tests}
""".strip()


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"Provider did not return a JSON object: {text[:300]}")
    return json.loads(cleaned[start : end + 1])


def validate_generated_code(
    canonical_name: str,
    code: str,
    *,
    language: str = "python",
) -> None:
    forbidden = [
        "subprocess",
        "os.system",
        "eval(",
        "exec(",
        "socket",
        "requests",
        "urllib",
    ]
    found = [token for token in forbidden if token in code]
    if found:
        raise ValueError(
            f"Generated code contains forbidden token(s): {', '.join(found)}"
        )

    if language == "bash":
        result = subprocess.run(
            ["bash", "-n"],
            input=code,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise ValueError(result.stderr.strip() or "Generated bash code is invalid")
        return

    compile(code, f"<generated {canonical_name}>", "exec")
    if f"def {canonical_name}" not in code:
        raise ValueError(f"Generated code must define function {canonical_name!r}")


def generation_rules_for(language: str) -> str:
    if language == "bash":
        return (
            "Generate small, boring, deterministic Bash. Prefer portable shell builtins "
            "and common POSIX utilities. Avoid network access, package installation, "
            "subshell-heavy complexity, reading secrets, or modifying files outside explicit intent. "
            "Arguments arrive as CLI strings; when a single argument is provided, treat it as the primary piped input."
        )
    return (
        "Generate small, boring, deterministic Python. Prefer pure functions: no filesystem, network, subprocess, eval, exec, environment variables, secrets, or shell calls. "
        "Use only the Python standard library unless the requested task clearly requires otherwise. "
        "Function arguments are received from the CLI as strings, so parse them inside the function when needed. "
        "Generated functions must work naturally with shell pipelines: when called with one string argument, treat it as the primary input value. "
        "The code must define a function named exactly canonical_name."
    )


def generated_test_hint_for(language: str, requested_name: str) -> str:
    if language == "bash":
        return (
            "Tests must use pytest and call aifn.runner.run_entrypoint with "
            f"`.aifn/functions/{requested_name}.sh:{requested_name}`."
        )
    return (
        "Tests must load the function from `.aifn/functions/<canonical_name>.py` "
        "using importlib.util and pathlib."
    )


def find_programmatic_alias_match(
    requested_name: str,
    similar_capabilities: list[dict[str, Any]],
) -> str | None:
    for candidate in similar_capabilities:
        canonical_name = candidate.get("canonical_name")
        if not canonical_name:
            continue
        normalized_names = [canonical_name, *candidate.get("aliases", [])]
        for value in normalized_names:
            if safe_python_identifier(value) == requested_name:
                return safe_python_identifier(canonical_name)
    return None


def safe_python_identifier(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value.strip())
    cleaned = cleaned.lower().strip("_")
    if not cleaned:
        raise ValueError("Function name cannot be empty")
    if cleaned[0].isdigit():
        cleaned = f"fn_{cleaned}"
    return cleaned
