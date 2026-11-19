"""Validate PBIP/PBIR metadata against Microsoft's published JSON schemas."""
import json
from functools import lru_cache
from pathlib import Path
import urllib.request

from jsonschema.validators import validator_for
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "https://developer.microsoft.com/json-schemas/fabric/"


@lru_cache(maxsize=32)
def retrieve(uri):
    if not uri.startswith(PREFIX):
        raise ValueError("Only official Fabric schemas may be retrieved")
    with urllib.request.urlopen(uri, timeout=30) as response:
        content = response.read(2 * 1024 * 1024 + 1)
    if len(content) > 2 * 1024 * 1024:
        raise ValueError("Schema exceeds 2 MiB")
    return Resource.from_contents(json.loads(content))


def main():
    registry = Registry(retrieve=retrieve)
    schemas = {}
    count = 0
    for path in sorted((ROOT / "powerbi").rglob("*")):
        if not path.is_file() or path.suffix not in (".json", ".pbip", ".pbir", ".pbism"):
            continue
        document = json.loads(path.read_text())
        uri = document.get("$schema")
        if not uri:
            continue
        if uri not in schemas:
            schemas[uri] = retrieve(uri).contents
        schema = schemas[uri]
        validator = validator_for(schema)
        validator.check_schema(schema)
        validator(schema, registry=registry).validate(document)
        count += 1
    print(f"PASS: {count} PBIP/PBIR metadata files validated against official schemas")


if __name__ == "__main__":
    main()
