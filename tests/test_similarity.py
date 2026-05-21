from aifn.registry import FunctionRecord, Registry
from aifn.similarity import find_similar


def test_find_similar_by_alias(tmp_path):
    registry = Registry(path=tmp_path / "registry.json")
    registry.add(FunctionRecord(
        canonical_name="slugify",
        entrypoint="functions/slugify.py:slugify",
        aliases=["make_slug"],
        description="Convert text to URL slug",
    ))

    matches = find_similar(registry, "make_slug")

    assert matches
    assert matches[0][1].canonical_name == "slugify"
