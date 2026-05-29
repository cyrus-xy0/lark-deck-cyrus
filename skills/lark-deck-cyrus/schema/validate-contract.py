#!/usr/bin/env python3
"""Validate Cyrus JSON handoff artifacts with the local schema subset."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
VALIDATE_DECK = REPO / "skills/deck-renderer/deck-json/validate-deck.py"


def load_validator_module():
    spec = importlib.util.spec_from_file_location("deck_json_validator", VALIDATE_DECK)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load validator module from {VALIDATE_DECK}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--instance", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        schema = read_json(args.schema)
        instance = read_json(args.instance)
    except Exception as exc:  # noqa: BLE001 - CLI should show parse/load failures.
        print(f"validate-contract: failed to load JSON: {exc}", file=sys.stderr)
        return 2

    module = load_validator_module()
    result = module.Result()
    module.SchemaValidator(schema).validate(instance, result)
    if result.ok:
        print(f"validate-contract: PASS {args.instance} against {args.schema}")
        return 0
    print(f"validate-contract: FAIL {args.instance} against {args.schema}", file=sys.stderr)
    for path, message in result.errors:
        print(f"- {path}: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
