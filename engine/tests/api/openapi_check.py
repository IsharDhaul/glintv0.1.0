# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""A strict validator for the JSON Schema subset FastAPI/pydantic emit in `contracts/openapi.json`.

It knows exactly the keywords that file uses and fails on any it doesn't, so a new keyword in
the contract can't be silently skipped.
"""

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from glint.core.settings import REPO_ROOT

OPENAPI_PATH = REPO_ROOT / "contracts" / "openapi.json"
_ANNOTATIONS = frozenset({"title", "description", "default"})
_KNOWN = _ANNOTATIONS | {
    "$ref", "type", "properties", "required", "additionalProperties", "anyOf", "oneOf",
    "const", "enum", "items", "format", "minimum", "maximum", "exclusiveMinimum",
    "minItems", "maxItems", "minLength", "maxLength", "propertyNames",
}  # fmt: skip
_TYPES: dict[str, Any] = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def load_openapi(path: Path = OPENAPI_PATH) -> dict[str, Any]:
    return json.loads(path.read_text())


class SchemaError(AssertionError):
    pass


def _is_type(value: Any, t: str) -> bool:
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    return isinstance(value, _TYPES[t])


def _check_format(value: str, fmt: str, where: str) -> None:
    try:
        if fmt == "date":
            date.fromisoformat(value)
        elif fmt == "date-time":
            datetime.fromisoformat(value)
        elif fmt != "uri":
            raise SchemaError(f"{where}: unknown format {fmt!r}")
    except ValueError as exc:
        raise SchemaError(f"{where}: {value!r} is not a {fmt}") from exc


def validate(value: Any, schema: dict[str, Any], spec: dict[str, Any], where: str = "$") -> None:
    unknown = set(schema) - _KNOWN
    if unknown:
        raise SchemaError(f"{where}: validator doesn't know {sorted(unknown)}")
    if "$ref" in schema:
        name = schema["$ref"].removeprefix("#/components/schemas/")
        validate(value, spec["components"]["schemas"][name], spec, where)
        return
    for key in ("anyOf", "oneOf"):
        if key in schema:
            passed = 0
            for sub in schema[key]:
                try:
                    validate(value, sub, spec, where)
                    passed += 1
                except SchemaError:
                    pass
            if passed == 0 or (key == "oneOf" and passed > 1):
                raise SchemaError(f"{where}: {passed} of the {key} branches match {value!r:.80}")
    if "const" in schema and value != schema["const"]:
        raise SchemaError(f"{where}: {value!r} != const {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise SchemaError(f"{where}: {value!r} not in {schema['enum']}")
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(value, t) for t in types):
            raise SchemaError(f"{where}: {value!r:.80} is not {types}")
    if isinstance(value, str):
        if "format" in schema:
            _check_format(value, schema["format"], where)
        if len(value) < schema.get("minLength", 0):
            raise SchemaError(f"{where}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise SchemaError(f"{where}: longer than {schema['maxLength']}")
    if _is_type(value, "number"):
        if "minimum" in schema and value < schema["minimum"]:
            raise SchemaError(f"{where}: {value} < {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise SchemaError(f"{where}: {value} > {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            raise SchemaError(f"{where}: {value} <= {schema['exclusiveMinimum']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise SchemaError(f"{where}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise SchemaError(f"{where}: more than {schema['maxItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                validate(item, schema["items"], spec, f"{where}[{i}]")
    if isinstance(value, dict):
        _validate_object(value, schema, spec, where)


def _validate_object(
    value: dict[str, Any], schema: dict[str, Any], spec: dict[str, Any], where: str
) -> None:
    props: dict[str, Any] = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in value:
            raise SchemaError(f"{where}: missing required {key!r}")
    extra = schema.get("additionalProperties", True)
    for key, item in value.items():
        if "propertyNames" in schema:
            validate(key, schema["propertyNames"], spec, f"{where}<key {key!r}>")
        if key in props:
            validate(item, props[key], spec, f"{where}.{key}")
        elif extra is False:
            raise SchemaError(f"{where}: unexpected property {key!r}")
        elif isinstance(extra, dict):
            validate(item, extra, spec, f"{where}.{key}")


def response_schema(
    spec: dict[str, Any], method: str, url_path: str, status: int
) -> dict[str, Any] | None:
    """The JSON schema the contract declares for this response, or None for non-JSON ones."""
    for template, ops in spec["paths"].items():
        pattern = "^" + re.sub(r"\{[^/]+\}", "[^/]+", template) + "$"
        if re.match(pattern, url_path) and method.lower() in ops:
            responses = ops[method.lower()]["responses"]
            declared = responses.get(str(status))
            if declared is None:
                raise SchemaError(f"{method} {template}: status {status} not in the contract")
            content = declared.get("content", {})
            return content["application/json"]["schema"] if "application/json" in content else None
    raise SchemaError(f"{method} {url_path}: no such path in the contract")
