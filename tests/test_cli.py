from io import StringIO
from types import SimpleNamespace

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

    registry.main_model = "project-main"
    registry.fast_model = "project-fast"

    def fake_get_provider(name=None, model=None, fast_model=None):
        seen_provider_args.append((name, model, fast_model))
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
    assert seen_provider_args == [("openai", "gpt-test", "project-fast")]
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
    monkeypatch.setattr(
        "aifn.cli.get_provider",
        lambda name=None, model=None, fast_model=None: provider,
    )
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


def test_call_can_generate_new_function_despite_similar_match(monkeypatch, tmp_path):
    class FakeProvider:
        def __init__(self):
            self.calls = []

        def resolve_missing_function(self, **kwargs):
            return ResolutionDecision(action="generate", review_required=True)

        def generate_function(self, **kwargs):
            self.calls.append(kwargs)
            return GeneratedFunction(
                canonical_name="get_coordinates",
                code="def get_coordinates(*args: str) -> str:\n    return 'ok'\n",
                tests="def test_placeholder():\n    assert True\n",
                description="Look up coordinates",
                signature="get_coordinates(*args: str) -> str",
                tags=["geo"],
            )

    provider = FakeProvider()
    registry = Registry(path=tmp_path / "registry.json")
    registry.provider_name = "openai"
    registry.add(
        FunctionRecord(
            canonical_name="closest_city",
            entrypoint="functions/closest_city.py:closest_city",
            description="Find a nearby city from coordinates",
        )
    )

    monkeypatch.setattr("aifn.cli.init_store", lambda **kwargs: None)
    monkeypatch.setattr(
        "aifn.cli.find_similar",
        lambda registry, name: [(0.85, registry.records["closest_city"])],
    )
    monkeypatch.setattr(
        "aifn.cli.get_provider",
        lambda name=None, model=None, fast_model=None: provider,
    )
    monkeypatch.setattr("aifn.cli.Registry.load", lambda: registry)
    monkeypatch.setattr(
        "aifn.cli.write_generated_function",
        lambda generated, registry: SimpleNamespace(
            canonical_name=generated.canonical_name,
            entrypoint=f"{tmp_path / 'get_coordinates.py'}:{generated.canonical_name}",
        ),
    )
    monkeypatch.setattr("aifn.cli.run_entrypoint", lambda entrypoint, args: "ok")

    result = runner.invoke(app, ["call", "get_coordinates"], input="y\n")

    assert result.exit_code == 0
    assert "Generate a new function instead?" in result.output
    assert provider.calls == [
        {
            "name": "get_coordinates",
            "args": [],
            "description": None,
            "existing_capabilities": [registry.records["closest_city"].to_dict()],
        }
    ]


def test_call_shows_friendly_message_when_new_function_needs_arguments(
    monkeypatch, tmp_path
):
    class FakeProvider:
        def generate_function(self, **kwargs):
            return GeneratedFunction(
                canonical_name="get_coordinates",
                code="def get_coordinates(location: str) -> str:\n    return location\n",
                tests="def test_placeholder():\n    assert True\n",
                description="Look up coordinates",
                signature="get_coordinates(location: str) -> str",
                tags=["geo"],
            )

        def resolve_missing_function(self, **kwargs):
            return ResolutionDecision(action="generate")

    provider = FakeProvider()
    registry = Registry(path=tmp_path / "registry.json")
    registry.provider_name = "openai"
    record = FunctionRecord(
        canonical_name="get_coordinates",
        entrypoint="functions/get_coordinates.py:get_coordinates",
        description="Look up coordinates",
    )

    def raise_missing_location(entrypoint, args):
        del entrypoint, args
        raise __import__(
            "aifn.runner", fromlist=["InvocationArgumentError"]
        ).InvocationArgumentError("missing a required argument: 'location'")

    monkeypatch.setattr("aifn.cli.init_store", lambda **kwargs: None)
    monkeypatch.setattr("aifn.cli.find_similar", lambda registry, name: [])
    monkeypatch.setattr(
        "aifn.cli.get_provider",
        lambda name=None, model=None, fast_model=None: provider,
    )
    monkeypatch.setattr("aifn.cli.Registry.load", lambda: registry)
    monkeypatch.setattr(
        "aifn.cli.write_generated_function", lambda generated, registry: record
    )
    monkeypatch.setattr("aifn.cli.run_entrypoint", raise_missing_location)

    result = runner.invoke(app, ["call", "get_coordinates", "--yes"])

    assert result.exit_code == 0
    assert "needs different arguments before it can run" in result.output
    assert "The function was created successfully" in result.output


def test_call_exits_cleanly_when_existing_function_needs_arguments(
    monkeypatch, tmp_path
):
    registry = Registry(path=tmp_path / "registry.json")
    registry.provider_name = "openai"
    record = FunctionRecord(
        canonical_name="get_coordinates",
        entrypoint="functions/get_coordinates.py:get_coordinates",
        description="Look up coordinates",
    )
    registry.add(record)

    def raise_missing_location(entrypoint, args):
        del entrypoint, args
        raise __import__(
            "aifn.runner", fromlist=["InvocationArgumentError"]
        ).InvocationArgumentError("missing a required argument: 'location'")

    monkeypatch.setattr("aifn.cli.init_store", lambda **kwargs: None)
    monkeypatch.setattr("aifn.cli.Registry.load", lambda: registry)
    monkeypatch.setattr("aifn.cli.run_entrypoint", raise_missing_location)

    result = runner.invoke(app, ["call", "get_coordinates"])

    assert result.exit_code == 1
    assert "needs different arguments before it can run" in result.output


def test_call_exits_when_user_declines_new_function_after_similar_match(
    monkeypatch, tmp_path
):
    class FakeProvider:
        def resolve_missing_function(self, **kwargs):
            return ResolutionDecision(action="generate", review_required=True)

        def generate_function(self, **kwargs):
            raise AssertionError("generate_function should not be called")

    provider = FakeProvider()
    registry = Registry(path=tmp_path / "registry.json")
    registry.provider_name = "openai"
    registry.add(
        FunctionRecord(
            canonical_name="closest_city",
            entrypoint="functions/closest_city.py:closest_city",
            description="Find a nearby city from coordinates",
        )
    )

    monkeypatch.setattr("aifn.cli.init_store", lambda **kwargs: None)
    monkeypatch.setattr(
        "aifn.cli.find_similar",
        lambda registry, name: [(0.85, registry.records["closest_city"])],
    )
    monkeypatch.setattr(
        "aifn.cli.get_provider",
        lambda name=None, model=None, fast_model=None: provider,
    )
    monkeypatch.setattr("aifn.cli.Registry.load", lambda: registry)

    result = runner.invoke(app, ["call", "get_coordinates"], input="n\n")

    assert result.exit_code == 1
    assert "Generate a new function instead?" in result.output


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


def test_config_without_subcommand_shows_saved_values(monkeypatch, tmp_path):
    registry = Registry(path=tmp_path / "registry.json")
    registry.provider_name = "openai"
    registry.main_model = "gpt-main"
    registry.fast_model = "gpt-fast"

    monkeypatch.setattr("aifn.cli.init_store", lambda **kwargs: None)
    monkeypatch.setattr("aifn.cli.Registry.load", lambda: registry)

    result = runner.invoke(app, ["config"])

    assert result.exit_code == 0
    assert "openai" in result.output
    assert "gpt-main" in result.output
    assert "gpt-fast" in result.output


def test_config_set_models_persists_project_models(monkeypatch, tmp_path):
    registry = Registry(path=tmp_path / "registry.json")

    saved_calls = []

    def fake_init_store(provider_name=None, main_model=None, fast_model=None):
        saved_calls.append((provider_name, main_model, fast_model))
        if main_model is not None:
            registry.main_model = main_model
        if fast_model is not None:
            registry.fast_model = fast_model

    monkeypatch.setattr("aifn.cli.init_store", fake_init_store)
    monkeypatch.setattr("aifn.cli.Registry.load", lambda: registry)

    result = runner.invoke(
        app, ["config", "set-models", "--main", "gpt-main", "--fast", "gpt-fast"]
    )

    assert result.exit_code == 0
    assert saved_calls == [(None, "gpt-main", "gpt-fast")]
    assert registry.main_model == "gpt-main"
    assert registry.fast_model == "gpt-fast"


def test_doctor_reports_openai_setup(monkeypatch, tmp_path):
    registry = Registry(path=tmp_path / "registry.json")
    registry.provider_name = "openai"
    registry.main_model = "gpt-main"
    registry.fast_model = "gpt-fast"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    aifn_state_dir = project_dir / ".aifn"
    aifn_state_dir.mkdir()
    functions_dir = aifn_state_dir / "functions"
    functions_dir.mkdir()
    slugify_file = functions_dir / "slugify.py"
    registry.add(
        FunctionRecord(
            canonical_name="slugify",
            entrypoint=".aifn/functions/slugify.py:slugify",
        )
    )
    slugify_file.write_text("def slugify(*args):\n    return ''\n", encoding="utf-8")

    monkeypatch.setattr("aifn.cli.init_store", lambda **kwargs: None)
    monkeypatch.setattr("aifn.cli.Registry.load", lambda: registry)
    monkeypatch.setattr("aifn.cli.importlib.util.find_spec", lambda name: object())
    monkeypatch.setattr(
        "aifn.cli.os.getenv",
        lambda name: "test-key" if name == "OPENAI_API_KEY" else None,
    )
    monkeypatch.setattr("aifn.cli.aifn_dir", lambda: aifn_state_dir)
    monkeypatch.setattr("aifn.runner.project_root", lambda: project_dir)
    monkeypatch.setattr(
        "aifn.cli.resolve_entrypoint_path", lambda entrypoint: (slugify_file, "slugify")
    )

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "OPENAI_API_KEY" in result.output
    assert "Installed" in result.output


def test_edit_previews_changes_without_writing(monkeypatch, tmp_path):
    class FakeProvider:
        def edit_function(self, **kwargs):
            return GeneratedFunction(
                canonical_name="slugify",
                code="def slugify(*args: str) -> str:\n    return 'updated'\n",
                tests="def test_slugify():\n    assert True\n",
                description="Updated slugify",
                signature="slugify(*args: str) -> str",
                tags=["text"],
            )

    provider = FakeProvider()
    registry = Registry(path=tmp_path / "registry.json")
    registry.provider_name = "openai"
    record = FunctionRecord(
        canonical_name="slugify",
        entrypoint="functions/slugify.py:slugify",
        description="Original slugify",
        version=1,
    )
    registry.add(record)

    function_file = tmp_path / "slugify.py"
    function_file.write_text(
        "def slugify(*args: str) -> str:\n    return 'original'\n",
        encoding="utf-8",
    )
    test_file = tmp_path / "test_slugify.py"
    test_file.write_text("def test_slugify():\n    assert False\n", encoding="utf-8")

    monkeypatch.setattr("aifn.cli.init_store", lambda **kwargs: None)
    monkeypatch.setattr("aifn.cli.Registry.load", lambda: registry)
    monkeypatch.setattr(
        "aifn.cli.get_provider",
        lambda name=None, model=None, fast_model=None: provider,
    )
    monkeypatch.setattr(
        "aifn.cli.resolve_entrypoint_path",
        lambda entrypoint: (function_file, "slugify"),
    )
    monkeypatch.setattr(
        "aifn.scaffold.resolve_entrypoint_path",
        lambda entrypoint: (function_file, "slugify"),
    )
    monkeypatch.setattr("aifn.cli.tests_dir", lambda: tmp_path)
    monkeypatch.setattr("aifn.scaffold.tests_dir", lambda: tmp_path)
    monkeypatch.setattr("aifn.cli.resolve_call_args", lambda args: list(args or []))

    result = runner.invoke(app, ["edit", "slugify"], input="n\n")

    assert result.exit_code == 0
    assert "before/slugify.py" in result.output
    assert "Apply these changes?" in result.output
    assert "Preview only. No files were changed." in result.output
    assert function_file.read_text(encoding="utf-8").endswith("return 'original'\n")
    assert test_file.read_text(encoding="utf-8").endswith("assert False\n")
    assert registry.records["slugify"].version == 1


def test_edit_apply_updates_files_and_version(monkeypatch, tmp_path):
    class FakeProvider:
        def edit_function(self, **kwargs):
            return GeneratedFunction(
                canonical_name="slugify",
                code="def slugify(*args: str) -> str:\n    return 'updated'\n",
                tests="def test_slugify():\n    assert True\n",
                description="Updated slugify",
                signature="slugify(*args: str) -> str",
                tags=["text"],
            )

    provider = FakeProvider()
    registry = Registry(path=tmp_path / "registry.json")
    registry.provider_name = "openai"
    record = FunctionRecord(
        canonical_name="slugify",
        entrypoint="functions/slugify.py:slugify",
        description="Original slugify",
        version=1,
    )
    registry.add(record)

    function_file = tmp_path / "slugify.py"
    function_file.write_text(
        "def slugify(*args: str) -> str:\n    return 'original'\n",
        encoding="utf-8",
    )
    test_file = tmp_path / "test_slugify.py"
    test_file.write_text("def test_slugify():\n    assert False\n", encoding="utf-8")

    monkeypatch.setattr("aifn.cli.init_store", lambda **kwargs: None)
    monkeypatch.setattr("aifn.cli.Registry.load", lambda: registry)
    monkeypatch.setattr(
        "aifn.cli.get_provider",
        lambda name=None, model=None, fast_model=None: provider,
    )
    monkeypatch.setattr(
        "aifn.cli.resolve_entrypoint_path",
        lambda entrypoint: (function_file, "slugify"),
    )
    monkeypatch.setattr(
        "aifn.scaffold.resolve_entrypoint_path",
        lambda entrypoint: (function_file, "slugify"),
    )
    monkeypatch.setattr("aifn.cli.tests_dir", lambda: tmp_path)
    monkeypatch.setattr("aifn.scaffold.tests_dir", lambda: tmp_path)

    result = runner.invoke(app, ["edit", "slugify", "--apply"])

    assert result.exit_code == 0
    assert function_file.read_text(encoding="utf-8").endswith("return 'updated'\n")
    assert test_file.read_text(encoding="utf-8").endswith("assert True\n")
    assert registry.records["slugify"].version == 2


def test_remove_deletes_function_files_and_registry_record(monkeypatch, tmp_path):
    registry = Registry(path=tmp_path / "registry.json")
    record = FunctionRecord(
        canonical_name="slugify",
        entrypoint="functions/slugify.py:slugify",
        description="Convert text to a slug",
    )
    registry.add(record)

    function_file = tmp_path / "slugify.py"
    function_file.write_text("def slugify(*args):\n    return ''\n", encoding="utf-8")
    test_file = tmp_path / "test_slugify.py"
    test_file.write_text("def test_slugify():\n    assert True\n", encoding="utf-8")

    monkeypatch.setattr("aifn.cli.Registry.load", lambda: registry)
    monkeypatch.setattr(
        "aifn.scaffold.resolve_entrypoint_path",
        lambda entrypoint: (function_file, "slugify"),
    )
    monkeypatch.setattr("aifn.scaffold.tests_dir", lambda: tmp_path)

    result = runner.invoke(app, ["remove", "slugify", "--yes"])

    assert result.exit_code == 0
    assert "Removed" in result.output
    assert "slugify" not in registry.records
    assert function_file.exists() is False
    assert test_file.exists() is False


def test_remove_respects_confirmation_decline(monkeypatch, tmp_path):
    registry = Registry(path=tmp_path / "registry.json")
    record = FunctionRecord(
        canonical_name="slugify",
        entrypoint="functions/slugify.py:slugify",
        description="Convert text to a slug",
    )
    registry.add(record)

    function_file = tmp_path / "slugify.py"
    function_file.write_text("def slugify(*args):\n    return ''\n", encoding="utf-8")
    test_file = tmp_path / "test_slugify.py"
    test_file.write_text("def test_slugify():\n    assert True\n", encoding="utf-8")

    monkeypatch.setattr("aifn.cli.Registry.load", lambda: registry)
    monkeypatch.setattr(
        "aifn.scaffold.resolve_entrypoint_path",
        lambda entrypoint: (function_file, "slugify"),
    )
    monkeypatch.setattr("aifn.scaffold.tests_dir", lambda: tmp_path)

    result = runner.invoke(app, ["remove", "slugify"], input="n\n")

    assert result.exit_code == 1
    assert "No files were removed." in result.output
    assert "slugify" in registry.records
    assert function_file.exists() is True
    assert test_file.exists() is True


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
