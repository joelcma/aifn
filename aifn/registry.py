from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .paths import functions_dir, registry_path, tests_dir


@dataclass
class FunctionRecord:
    canonical_name: str
    entrypoint: str
    description: str = ""
    signature: str = ""
    aliases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    version: int = 1

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FunctionRecord":
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_name": self.canonical_name,
            "entrypoint": self.entrypoint,
            "description": self.description,
            "signature": self.signature,
            "aliases": self.aliases,
            "tags": self.tags,
            "version": self.version,
        }


class Registry:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or registry_path()
        self.records: dict[str, FunctionRecord] = {}
        self.provider_name = "placeholder"
        self.main_model: str | None = None
        self.fast_model: str | None = None

    @classmethod
    def load(cls) -> "Registry":
        registry = cls()
        if not registry.path.exists():
            return registry

        raw = json.loads(registry.path.read_text(encoding="utf-8"))
        registry.provider_name = raw.get("provider", "placeholder")
        registry.main_model = raw.get("main_model")
        registry.fast_model = raw.get("fast_model")
        for name, data in raw.get("functions", {}).items():
            registry.records[name] = FunctionRecord.from_dict(data)
        return registry

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "provider": self.provider_name,
            "main_model": self.main_model,
            "fast_model": self.fast_model,
            "functions": {
                name: record.to_dict() for name, record in sorted(self.records.items())
            },
        }
        self.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def find(self, name_or_alias: str) -> FunctionRecord | None:
        if name_or_alias in self.records:
            return self.records[name_or_alias]

        for record in self.records.values():
            if name_or_alias in record.aliases:
                return record
        return None

    def add(self, record: FunctionRecord) -> None:
        self.records[record.canonical_name] = record

    def add_alias(self, alias: str, canonical_name: str) -> FunctionRecord:
        record = self.records[canonical_name]
        if alias not in record.aliases and alias != canonical_name:
            record.aliases.append(alias)
        return record


def init_store(
    provider_name: str | None = None,
    main_model: str | None = None,
    fast_model: str | None = None,
) -> None:
    functions_dir().mkdir(parents=True, exist_ok=True)
    tests_dir().mkdir(parents=True, exist_ok=True)
    registry = Registry.load()
    if provider_name is not None:
        registry.provider_name = provider_name
    if main_model is not None:
        registry.main_model = main_model
    if fast_model is not None:
        registry.fast_model = fast_model
    registry.save()
