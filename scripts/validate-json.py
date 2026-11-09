#!/usr/bin/env python3
"""Validate media jobs against schemas/media-job.schema.json and cross-check the contracts.

Stdlib only: a small JSON Schema validator covering the keywords this repo's schema uses
(type, enum, pattern, required, properties, additionalProperties, items, minItems,
minimum, maximum, format=date-time). No `jsonschema` package, no network.
"""

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys

TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "null": lambda v: v is None,
}


def is_date_time(value):
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return "T" in value
    except ValueError:
        return False


def validate(value, schema, path="$"):
    errors = []
    wanted = schema.get("type")
    if wanted:
        names = wanted if isinstance(wanted, list) else [wanted]
        if not any(TYPES[name](value) for name in names):
            return [f"{path}: expected {'|'.join(names)}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: {value!r} does not match {schema['pattern']}")
        if schema.get("format") == "date-time" and not is_date_time(value):
            errors.append(f"{path}: {value!r} is not a date-time")
    if TYPES["number"](value):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: {value} > maximum {schema['maximum']}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        errors += [f"{path}: missing required '{key}'" for key in schema.get("required", []) if key not in value]
        for key, item in value.items():
            if key in props:
                errors += validate(item, props[key], f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected property '{key}'")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: needs at least {schema['minItems']} item(s)")
        if "items" in schema:
            for index, item in enumerate(value):
                errors += validate(item, schema["items"], f"{path}[{index}]")
    return errors


def cross_check(root):
    """Warnings (not failures): drift between the schema, routing config and pattern registry."""
    warnings = []
    schema = json.loads((root / "schemas/media-job.schema.json").read_text(encoding="utf-8"))
    providers = set(schema["properties"]["routing"]["properties"]["primaryProvider"]["enum"])
    config = json.loads((root / "configs/provider-routing.default.json").read_text(encoding="utf-8"))
    for route in config.get("routes", []):
        used = {route.get("primaryProvider")} | set(route.get("fallbackProviders", []))
        for provider in sorted(p for p in used if p and p not in providers):
            warnings.append(f"routing route '{route.get('intent')}': provider '{provider}' is not in the job schema enum")
    registry = json.loads((root / "patterns/motion-pattern-registry.json").read_text(encoding="utf-8"))
    ids = [pattern.get("id") for pattern in registry.get("patterns", [])]
    warnings += [f"pattern registry: duplicate id '{i}'" for i in sorted({i for i in ids if ids.count(i) > 1})]
    return warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("files", nargs="*", type=Path, help="job files (default: examples/media-jobs/*.json)")
    parser.add_argument("--expect-invalid", action="store_true", help="succeed only if every file is rejected")
    args = parser.parse_args()
    root = args.root.resolve()
    schema = json.loads((root / "schemas/media-job.schema.json").read_text(encoding="utf-8"))
    files = args.files or sorted((root / "examples/media-jobs").glob("*.json"))
    failures = 0
    for file in files:
        errors = validate(json.loads(file.read_text(encoding="utf-8")), schema)
        ok = bool(errors) if args.expect_invalid else not errors
        failures += 0 if ok else 1
        label = "rejected as expected" if (args.expect_invalid and errors) else ("valid" if not errors else "INVALID")
        print(f"{'OK ' if ok else 'ERR'} {file.name}: {label}")
        if not ok or (args.expect_invalid and errors):
            for error in errors[:4]:
                print(f"      {error}")
    if not args.files:
        for warning in cross_check(root):
            print(f"WARN {warning}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
