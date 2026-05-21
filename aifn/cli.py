from __future__ import annotations

import sys
from typing import Optional

import click
import typer
from rich.console import Console
from rich.table import Table
from typer.core import TyperGroup

from .paths import aifn_dir
from .provider import ResolutionDecision, get_provider
from .registry import Registry, init_store
from .runner import run_entrypoint
from .scaffold import write_generated_function
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
console = Console()


SUPPORTED_PROVIDERS = {"placeholder", "openai"}


def normalize_provider_name(value: str) -> str:
    provider_name = value.strip().lower()
    if provider_name not in SUPPORTED_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_PROVIDERS))
        raise typer.BadParameter(
            f"Unsupported provider {value!r}. Choose one of: {supported}"
        )
    return provider_name


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


def resolve_call_args(args: list[str] | None) -> list[str]:
    resolved_args = list(args or [])
    if resolved_args or sys.stdin.isatty():
        return resolved_args

    piped_input = sys.stdin.read()
    if not piped_input:
        return resolved_args

    return [piped_input.rstrip("\n")]


@app.command()
def init() -> None:
    """Initialize .aifn in the current project."""
    registry = Registry.load()
    default_provider = registry.provider_name
    provider_name = prompt_for_provider(default_provider)
    init_store(provider_name=provider_name)
    console.print(f"Initialized [bold]{aifn_dir()}[/bold]")
    console.print(f"Default provider: [bold]{provider_name}[/bold]")


@app.command()
def call(
    name: str = typer.Argument(..., help="Function name or alias"),
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
        result = run_entrypoint(record.entrypoint, args)
        console.print(result)
        return

    selected_provider = normalize_provider_name(provider_name or registry.provider_name)
    provider = get_provider(name=selected_provider, model=model)
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
            result = run_entrypoint(aliased_record.entrypoint, args)
            console.print(result)
            return

        console.print(
            "Use `aifn alias NEW_NAME EXISTING_NAME` to alias it, or call again with --yes to scaffold anyway."
        )
        if decision.review_required and not yes:
            raise typer.Exit(code=1)

    generated = provider.generate_function(
        name=name,
        args=args,
        description=desc,
        existing_capabilities=[
            record.to_dict() for record in registry.records.values()
        ],
    )

    console.print(f"Function [bold]{generated.canonical_name}[/bold] does not exist.")
    console.print("Scaffold new generated implementation?")

    if not yes and not typer.confirm("Create it?"):
        raise typer.Exit(code=1)

    record = write_generated_function(generated, registry)
    console.print(
        f"Created [bold]{record.canonical_name}[/bold] at {record.entrypoint}"
    )
    result = run_entrypoint(record.entrypoint, args)
    console.print(result)


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
