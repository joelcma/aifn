from __future__ import annotations

import difflib
import importlib.util
import os
import sys
from typing import Optional

import click
import typer
from rich.console import Console
from rich.table import Table
from typer.core import TyperGroup

from .paths import aifn_dir, tests_dir
from .provider import ResolutionDecision, get_provider
from .registry import Registry, init_store
from .runner import InvocationArgumentError, resolve_entrypoint_path, run_entrypoint
from .scaffold import (
    remove_generated_function,
    rename_generated_function,
    update_generated_function,
    write_generated_function,
)
from .similarity import find_similar


class AIFNGroup(TyperGroup):
    def resolve_command(self, ctx: click.Context, args: list[str]):
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError:
            if args and not args[0].startswith("-"):
                command = self.get_command(ctx, "call")
                if command is not None:
                    return "call", command, args
            raise


app = typer.Typer(cls=AIFNGroup, help="AI-assisted local function registry CLI")
config_app = typer.Typer(
    invoke_without_command=True, help="Show or update project configuration"
)
app.add_typer(config_app, name="config")
console = Console()


SUPPORTED_PROVIDERS = {"placeholder", "openai"}
SUPPORTED_LANGUAGES = {"python", "bash"}
FUNCTION_NAME_HELP = "Function name or alias"


def normalize_provider_name(value: str) -> str:
    provider_name = value.strip().lower()
    if provider_name not in SUPPORTED_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_PROVIDERS))
        raise typer.BadParameter(
            f"Unsupported provider {value!r}. Choose one of: {supported}"
        )
    return provider_name


def normalize_language_name(value: str) -> str:
    language = value.strip().lower()
    if language not in SUPPORTED_LANGUAGES:
        supported = ", ".join(sorted(SUPPORTED_LANGUAGES))
        raise typer.BadParameter(
            f"Unsupported language {value!r}. Choose one of: {supported}"
        )
    return language


def prompt_for_provider(default: str) -> str:
    while True:
        provider_name = typer.prompt(
            "Provider",
            default=default,
            show_default=True,
        )
        try:
            return normalize_provider_name(provider_name)
        except typer.BadParameter as exc:
            console.print(str(exc), style="red")


def resolve_model_settings(
    registry: Registry,
    model: str | None = None,
    fast_model: str | None = None,
) -> tuple[str | None, str | None]:
    selected_main_model = model or registry.main_model or os.getenv("AIFN_MAIN_MODEL")
    selected_fast_model = (
        fast_model or registry.fast_model or os.getenv("AIFN_FAST_MODEL")
    )
    return selected_main_model, selected_fast_model


def print_config(registry: Registry) -> None:
    table = Table(title="Project configuration")
    table.add_column("Setting")
    table.add_column("Value")
    table.add_row("provider", registry.provider_name)
    table.add_row("main_model", registry.main_model or "<env/default>")
    table.add_row("fast_model", registry.fast_model or "<env/default>")
    console.print(table)


def doctor_report_line(status: str, name: str, detail: str) -> None:
    style = {
        "ok": "green",
        "warn": "yellow",
        "error": "red",
    }[status]
    console.print(f"[{style}]{status.upper()}[/{style}] {name}: {detail}")


def check_provider_config(registry: Registry) -> tuple[str, int]:
    try:
        provider_name = normalize_provider_name(registry.provider_name)
        doctor_report_line("ok", "provider", provider_name)
        return provider_name, 0
    except typer.BadParameter as exc:
        doctor_report_line("error", "provider", str(exc))
        return registry.provider_name, 1


def check_openai_environment() -> tuple[int, int]:
    errors = 0
    warnings = 0

    if importlib.util.find_spec("openai") is None:
        errors += 1
        doctor_report_line(
            "error", "openai package", "Install with: pip install -e '.[openai]'"
        )
    else:
        doctor_report_line("ok", "openai package", "Installed")

    if os.getenv("OPENAI_API_KEY"):
        doctor_report_line("ok", "OPENAI_API_KEY", "Present in environment")
    else:
        warnings += 1
        doctor_report_line("warn", "OPENAI_API_KEY", "Missing from environment")

    return errors, warnings


def check_entrypoints(registry: Registry) -> int:
    missing_entrypoints = []
    for record in registry.records.values():
        path, _ = resolve_entrypoint_path(record.entrypoint)
        if not path.exists():
            missing_entrypoints.append(record.canonical_name)

    if missing_entrypoints:
        doctor_report_line(
            "warn",
            "entrypoints",
            f"Missing files for: {', '.join(sorted(missing_entrypoints))}",
        )
        return 1

    doctor_report_line("ok", "entrypoints", "All registered function files exist")
    return 0


def resolve_call_args(args: list[str] | None) -> list[str]:
    resolved_args = list(args or [])
    if resolved_args or sys.stdin.isatty():
        return resolved_args

    piped_input = sys.stdin.read()
    if not piped_input:
        return resolved_args

    return [piped_input.rstrip("\n")]


def print_unified_diff(title: str, before: str, after: str) -> bool:
    diff_lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"before/{title}",
            tofile=f"after/{title}",
            lineterm="",
        )
    )
    if not diff_lines:
        return False

    console.print(f"[bold]{title}[/bold]")
    console.print("\n".join(diff_lines), markup=False)
    return True


def print_invocation_argument_error(name: str, exc: InvocationArgumentError) -> None:
    console.print(
        f"Function [bold]{name}[/bold] needs different arguments before it can run: {exc}"
    )


def run_record(
    record: FunctionRecord, args: list[str], *, created: bool = False
) -> bool:
    try:
        result = run_entrypoint(record.entrypoint, args)
    except InvocationArgumentError as exc:
        print_invocation_argument_error(record.canonical_name, exc)
        if created:
            console.print(
                f"The function was created successfully. Re-run [bold]aifn {record.canonical_name} ...[/bold] with the required input."
            )
            return False
        raise typer.Exit(code=1) from exc

    console.print(result)
    return True


@app.command()
def init() -> None:
    """Initialize .aifn in the current project."""
    registry = Registry.load()
    default_provider = registry.provider_name
    provider_name = prompt_for_provider(default_provider)
    init_store(provider_name=provider_name)
    console.print(f"Initialized [bold]{aifn_dir()}[/bold]")
    console.print(f"Default provider: [bold]{provider_name}[/bold]")


@config_app.callback()
def config_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        init_store()
        print_config(Registry.load())


@config_app.command("set-provider")
def config_set_provider(
    provider_name: str = typer.Argument(..., help="Project provider name"),
) -> None:
    normalized_provider = normalize_provider_name(provider_name)
    init_store(provider_name=normalized_provider)
    console.print(f"Saved provider: [bold]{normalized_provider}[/bold]")


@config_app.command("set-models")
def config_set_models(
    main_model: Optional[str] = typer.Option(None, "--main", help="Project main model"),
    fast_model: Optional[str] = typer.Option(None, "--fast", help="Project fast model"),
) -> None:
    if main_model is None and fast_model is None:
        raise typer.BadParameter("Provide --main, --fast, or both.")

    init_store(main_model=main_model, fast_model=fast_model)
    registry = Registry.load()
    print_config(registry)


@app.command()
def doctor() -> None:
    """Check project configuration and local environment."""
    errors = 0
    warnings = 0
    init_store()
    registry = Registry.load()

    doctor_report_line("ok", ".aifn", f"Initialized at {aifn_dir()}")

    provider_name, provider_errors = check_provider_config(registry)
    errors += provider_errors

    main_model, fast_model = resolve_model_settings(registry)
    doctor_report_line("ok", "main_model", main_model or "<provider default>")
    doctor_report_line("ok", "fast_model", fast_model or "<provider default>")

    if provider_name == "openai":
        openai_errors, openai_warnings = check_openai_environment()
        errors += openai_errors
        warnings += openai_warnings

    warnings += check_entrypoints(registry)

    if errors:
        raise typer.Exit(code=1)
    if warnings:
        raise typer.Exit(code=0)


@app.command()
def edit(
    name: str = typer.Argument(..., help=FUNCTION_NAME_HELP),
    args: list[str] = typer.Argument(
        None, help="Arguments passed to the edited function"
    ),
    desc: Optional[str] = typer.Option(
        None,
        "--desc",
        help="Describe the change you want made to the existing function",
    ),
    provider_name: Optional[str] = typer.Option(
        None,
        "--provider",
        help="Generation provider to use, for example placeholder or openai",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Override the provider model for this edit",
    ),
    fast_model: Optional[str] = typer.Option(
        None,
        "--fast-model",
        help="Override the fast delegation model for this edit",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Apply the proposed edit without an interactive confirmation",
    ),
) -> None:
    """Preview and optionally apply an AI-generated edit to an existing function."""
    init_store()
    registry = Registry.load()
    args = resolve_call_args(args)

    record = registry.find(name)
    if not record:
        console.print(f"No function found for {name!r}")
        raise typer.Exit(code=1)

    selected_provider = normalize_provider_name(provider_name or registry.provider_name)
    selected_main_model, selected_fast_model = resolve_model_settings(
        registry,
        model=model,
        fast_model=fast_model,
    )
    provider = get_provider(
        name=selected_provider,
        model=selected_main_model,
        fast_model=selected_fast_model,
    )

    function_file, _ = resolve_entrypoint_path(record.entrypoint)
    test_file = tests_dir() / f"test_{record.canonical_name}.py"
    current_code = function_file.read_text(encoding="utf-8")
    current_tests = test_file.read_text(encoding="utf-8") if test_file.exists() else ""

    generated = provider.edit_function(
        name=record.canonical_name,
        args=args,
        current_code=current_code,
        current_tests=current_tests,
        description=desc,
        existing_capabilities=[item.to_dict() for item in registry.records.values()],
        language=record.language,
    )

    changed = False
    changed |= print_unified_diff(
        f"{record.canonical_name}.py", current_code, generated.code
    )
    changed |= print_unified_diff(
        f"test_{record.canonical_name}.py",
        current_tests,
        generated.tests,
    )

    if not changed:
        console.print("No changes proposed.")
        return

    if not apply and not typer.confirm("Apply these changes?"):
        console.print("Preview only. No files were changed.")
        return

    updated_record = update_generated_function(record, generated, registry)
    console.print(
        f"Updated [bold]{updated_record.canonical_name}[/bold] to version {updated_record.version}"
    )


@app.command()
def call(
    name: str = typer.Argument(..., help=FUNCTION_NAME_HELP),
    args: list[str] = typer.Argument(None, help="Arguments passed to the function"),
    desc: Optional[str] = typer.Option(
        None, "--desc", help="Description for missing functions"
    ),
    provider_name: Optional[str] = typer.Option(
        None,
        "--provider",
        help="Generation provider to use, for example placeholder or openai",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Override the provider model for this call",
    ),
    fast_model: Optional[str] = typer.Option(
        None,
        "--fast-model",
        help="Override the fast delegation model for this call",
    ),
    language: str = typer.Option(
        "python",
        "--language",
        help="Language to generate for new functions: python or bash",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Accept scaffold without prompt"
    ),
) -> None:
    """Call a local function, or scaffold it if it does not exist."""
    init_store()
    registry = Registry.load()
    args = resolve_call_args(args)

    record = registry.find(name)
    if record:
        run_record(record, args)
        return

    selected_language = normalize_language_name(language)

    selected_provider = normalize_provider_name(provider_name or registry.provider_name)
    selected_main_model, selected_fast_model = resolve_model_settings(
        registry,
        model=model,
        fast_model=fast_model,
    )
    provider = get_provider(
        name=selected_provider,
        model=selected_main_model,
        fast_model=selected_fast_model,
    )
    similar = find_similar(registry, name)
    similar_capabilities = [candidate.to_dict() for _, candidate in similar[:5]]
    decision = provider.resolve_missing_function(
        name=name,
        args=args,
        description=desc,
        existing_capabilities=[
            record.to_dict() for record in registry.records.values()
        ],
        similar_capabilities=similar_capabilities,
    )

    if similar:
        table = Table(title="Similar capabilities found")
        table.add_column("Score")
        table.add_column("Canonical")
        table.add_column("Aliases")
        table.add_column("Description")
        for score, candidate in similar[:5]:
            table.add_row(
                f"{score:.2f}",
                candidate.canonical_name,
                ", ".join(candidate.aliases),
                candidate.description,
            )
        console.print(table)
        if decision.action == "alias" and decision.canonical_name:
            aliased_record = registry.add_alias(name, decision.canonical_name)
            registry.save()
            console.print(
                f"Added alias [bold]{name}[/bold] -> [bold]{aliased_record.canonical_name}[/bold]"
            )
            run_record(aliased_record, args)
            return

        console.print(
            "Use `aifn alias NEW_NAME EXISTING_NAME` to alias it, or generate a new function anyway."
        )
        if not yes and not typer.confirm("Generate a new function instead?"):
            raise typer.Exit(code=1)

    generated = provider.generate_function(
        name=name,
        args=args,
        description=desc,
        existing_capabilities=[
            record.to_dict() for record in registry.records.values()
        ],
        language=selected_language,
    )

    console.print(f"Function [bold]{generated.canonical_name}[/bold] does not exist.")
    console.print("Scaffold new generated implementation?")

    if not yes and not typer.confirm("Create it?"):
        raise typer.Exit(code=1)

    record = write_generated_function(generated, registry)
    console.print(
        f"Created [bold]{record.canonical_name}[/bold] at {record.entrypoint}"
    )
    run_record(record, args, created=True)


@app.command("list")
def list_functions() -> None:
    """List registered functions."""
    registry = Registry.load()
    table = Table(title="Registered functions")
    table.add_column("Name")
    table.add_column("Aliases")
    table.add_column("Description")
    table.add_column("Version")

    for record in registry.records.values():
        table.add_row(
            record.canonical_name,
            ", ".join(record.aliases),
            record.description,
            str(record.version),
        )
    console.print(table)


@app.command()
def inspect(name: str) -> None:
    """Show one function record."""
    registry = Registry.load()
    record = registry.find(name)
    if not record:
        console.print(f"No function found for {name!r}")
        raise typer.Exit(code=1)

    console.print_json(data=record.to_dict())


@app.command()
def remove(
    name: str = typer.Argument(..., help=FUNCTION_NAME_HELP),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Delete without interactive confirmation",
    ),
) -> None:
    """Remove a registered function and its generated files."""
    registry = Registry.load()
    record = registry.find(name)
    if not record:
        console.print(f"No function found for {name!r}")
        raise typer.Exit(code=1)

    if not yes and not typer.confirm(
        f"Remove function {record.canonical_name!r} and its generated files?"
    ):
        console.print("No files were removed.")
        raise typer.Exit(code=1)

    remove_generated_function(record, registry)
    console.print(f"Removed [bold]{record.canonical_name}[/bold]")


@app.command()
def rename(
    name: str = typer.Argument(..., help=FUNCTION_NAME_HELP),
    new_name: str = typer.Argument(..., help="New canonical function name"),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Rename without interactive confirmation",
    ),
) -> None:
    """Rename a registered function and preserve the old name as an alias."""
    registry = Registry.load()
    record = registry.find(name)
    if not record:
        console.print(f"No function found for {name!r}")
        raise typer.Exit(code=1)

    existing = registry.find(new_name)
    if existing is not None and existing is not record:
        console.print(f"A function already exists for {new_name!r}")
        raise typer.Exit(code=1)

    if new_name == record.canonical_name:
        console.print(f"[bold]{new_name}[/bold] is already the canonical name")
        return

    if not yes and not typer.confirm(
        f"Rename function {record.canonical_name!r} to {new_name!r}?"
    ):
        console.print("No files were renamed.")
        raise typer.Exit(code=1)

    renamed_record = rename_generated_function(record, new_name, registry)
    console.print(
        f"Renamed [bold]{name}[/bold] -> [bold]{renamed_record.canonical_name}[/bold]"
    )


@app.command()
def alias(alias_name: str, canonical_name: str) -> None:
    """Add an alias to an existing function."""
    registry = Registry.load()
    if canonical_name not in registry.records:
        console.print(f"No canonical function named {canonical_name!r}")
        raise typer.Exit(code=1)

    record = registry.add_alias(alias_name, canonical_name)
    registry.save()
    console.print(
        f"Added alias [bold]{alias_name}[/bold] -> [bold]{record.canonical_name}[/bold]"
    )


if __name__ == "__main__":
    app()
