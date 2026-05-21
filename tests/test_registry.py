from aifn.registry import FunctionRecord, Registry


def test_registry_alias_lookup(tmp_path):
    registry = Registry(path=tmp_path / "registry.json")
    record = FunctionRecord(
        canonical_name="slugify",
        entrypoint="functions/slugify.py:slugify",
        aliases=["make_slug"],
    )
    registry.add(record)

    assert registry.find("slugify") == record
    assert registry.find("make_slug") == record
    assert registry.find("missing") is None


def test_registry_persists_provider_name(tmp_path):
    registry = Registry(path=tmp_path / "registry.json")
    registry.provider_name = "openai"

    registry.save()

    loaded = Registry(path=tmp_path / "registry.json").load()

    assert loaded.provider_name == "openai"
