from types import SimpleNamespace
from io import StringIO

from typer.testing import CliRunner

from aifn.cli import app, resolve_call_args
from aifn.provider import GeneratedFunction, ResolutionDecision
from aifn.registry import FunctionRecord, Registry

runner = CliRunner()


def test_call_uses_selected_provider_and_registry_context(monkeypatch, tmp_path):
    class FakeProvider:
        def __init__(self):
            self.calls = []

        def resolve_missing_function(self, **kwargs):
            return ResolutionDecision(action="generate")

        def generate_function(self, **kwargs):
            self.calls.append(kwargs)
            return GeneratedFunction(
                canonical_name="summarize_text",
                code="def summarize_text(*args: str) -> str:\n    return 'ok'\n",
                tests="def test_placeholder():\n    assert True\n",
                description="summary",
                signature="summarize_text(*args: str) -> str",
                tags=["text"],
            )

    provider = FakeProvider()
    registry = Registry(path=tmp_path / "registry.json")
    registry.provider_name = "openai"
    registry.records = {
        "slugify": SimpleNamespace(
            to_dict=lambda: {
                "canonical_name": "slugify",
                "entrypoint": "functions/slugify.py:slugify",
                "description": "Convert text to a slug",
                "signature": "slugify(text: str) -> str",
                "aliases": ["make_slug"],
                "tags": ["text"],
                "version": 1,
            }
        )
    }

    monkeypatch.setattr("aifn.cli.init_store", lambda: None)
    monkeypatch.setattr("aifn.cli.find_similar", lambda registry, name: [])
    seen_provider_args = []

    def fake_get_provider(name=None, model=None):
        seen_provider_args.append((name, model))
        return provider

    monkeypatch.setattr("aifn.cli.get_provider", fake_get_provider)
    monkeypatch.setattr("aifn.cli.Registry.load", lambda: registry)
    monkeypatch.setattr(
        "aifn.cli.write_generated_function",
        lambda generated, registry: SimpleNamespace(
            canonical_name=generated.canonical_name,
            entrypoint=(
                f"{tmp_path / (generated.canonical_name + '.py')}:{generated.canonical_name}"
            ),
        ),
    )
    monkeypatch.setattr("aifn.cli.run_entrypoint", lambda entrypoint, args: "ok")

    result = runner.invoke(
        app,
        [
            "call",
            "summarize_text",
            "hello world",
            "--desc",
            "Summarize the input text",
            "--provider",
            "openai",
            "--model",
            "gpt-test",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert seen_provider_args == [("openai", "gpt-test")]
    assert provider.calls == [
        {
            "name": "summarize_text",
            "args": ["hello world"],
            "description": "Summarize the input text",
            "existing_capabilities": [registry.records["slugify"].to_dict()],
        }
    ]


def test_unknown_top_level_command_dispatches_to_call(monkeypatch, tmp_path):
    class FakeProvider:
        def __init__(self):
            self.calls = []

        def resolve_missing_function(self, **kwargs):
            return ResolutionDecision(action="generate")

        def generate_function(self, **kwargs):
            self.calls.append(kwargs)
            return GeneratedFunction(
                canonical_name="slugify",
                code="def slugify(*args: str) -> str:\n    return 'ok'\n",
                tests="def test_placeholder():\n    assert True\n",
                description="summary",
                signature="slugify(*args: str) -> str",
                tags=["text"],
            )

    provider = FakeProvider()
    registry = Registry(path=tmp_path / "registry.json")
    registry.provider_name = "openai"

    monkeypatch.setattr("aifn.cli.init_store", lambda: None)
    monkeypatch.setattr("aifn.cli.find_similar", lambda registry, name: [])
    monkeypatch.setattr("aifn.cli.get_provider", lambda name=None, model=None: provider)
    monkeypatch.setattr("aifn.cli.Registry.load", lambda: registry)
    monkeypatch.setattr(
        "aifn.cli.write_generated_function",
        lambda generated, registry: SimpleNamespace(
            canonical_name=generated.canonical_name,
            entrypoint=(
                f"{tmp_path / (generated.canonical_name + '.py')}:{generated.canonical_name}"
            ),
        ),
    )
    monkeypatch.setattr("aifn.cli.run_entrypoint", lambda entrypoint, args: "ok")

    result = runner.invoke(app, ["slugify", "Hello World", "--yes"])

    assert result.exit_code == 0
    assert provider.calls == [
        {
            "name": "slugify",
            "args": ["Hello World"],
            "description": None,
            "existing_capabilities": [],
        }
    ]


def test_call_adds_alias_when_provider_delegates_to_existing_function(
    monkeypatch, tmp_path
):
    class FakeProvider:
        def resolve_missing_function(self, **kwargs):
            return ResolutionDecision(action="alias", canonical_name="slugify")

        def generate_function(self, **kwargs):
            raise AssertionError(
                "generate_function should not be called for alias delegation"
            )

    provider = FakeProvider()
    registry = Registry(path=tmp_path / "registry.json")
    registry.provider_name = "openai"
    registry.add(
        FunctionRecord(
            canonical_name="slugify",
            entrypoint="functions/slugify.py:slugify",
            description="Convert text to a slug",
            aliases=[],
        )
    )

    monkeypatch.setattr("aifn.cli.init_store", lambda: None)
    monkeypatch.setattr(
        "aifn.cli.find_similar",
        lambda registry, name: [(0.88, registry.records["slugify"])],
    )
    monkeypatch.setattr("aifn.cli.get_provider", lambda name=None, model=None: provider)
    monkeypatch.setattr("aifn.cli.Registry.load", lambda: registry)
    monkeypatch.setattr("aifn.cli.run_entrypoint", lambda entrypoint, args: "slugged")

    result = runner.invoke(app, ["call", "make_slug", "hello world"])

    assert result.exit_code == 0
    assert registry.records["slugify"].aliases == ["make_slug"]


def test_init_prompts_for_provider_and_saves_it(monkeypatch, tmp_path):
    registry = Registry(path=tmp_path / "registry.json")

    monkeypatch.setattr("aifn.cli.aifn_dir", lambda: tmp_path)
    monkeypatch.setattr("aifn.cli.Registry.load", lambda: registry)

    saved_provider_names = []

    def fake_init_store(provider_name=None):
        saved_provider_names.append(provider_name)
        registry.provider_name = provider_name or registry.provider_name

    monkeypatch.setattr("aifn.cli.init_store", fake_init_store)

    result = runner.invoke(app, ["init"], input="openai\n")

    assert result.exit_code == 0
    assert saved_provider_names == ["openai"]
    assert registry.provider_name == "openai"


def test_call_rejects_unknown_saved_provider(monkeypatch, tmp_path):
    registry = Registry(path=tmp_path / "registry.json")
    registry.provider_name = "bogus"

    monkeypatch.setattr("aifn.cli.init_store", lambda: None)
    monkeypatch.setattr("aifn.cli.Registry.load", lambda: registry)

    result = runner.invoke(app, ["call", "summarize_text", "hello world", "--yes"])

    assert result.exit_code != 0
    assert "Unsupported provider" in result.output


def test_resolve_call_args_uses_piped_stdin_when_no_args_are_provided(monkeypatch):
    class FakeStdin(StringIO):
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr("aifn.cli.sys.stdin", FakeStdin("Hello World\n"))

    assert resolve_call_args(None) == ["Hello World"]


def test_resolve_call_args_prefers_explicit_args_over_piped_stdin(monkeypatch):
    class FakeStdin(StringIO):
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr("aifn.cli.sys.stdin", FakeStdin("Ignored Input\n"))

    assert resolve_call_args(["Hello World"]) == ["Hello World"]
