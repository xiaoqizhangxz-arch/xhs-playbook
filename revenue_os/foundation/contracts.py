from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

from revenue_os.foundation.config import CONTRACTS_ROOT


TYPE_MAP = {
    "string": str,
    "array": list,
    "object": dict,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
}


class ContractValidationError(ValueError):
    pass


@lru_cache(maxsize=None)
def load_contract(object_type: str) -> dict[str, Any]:
    path = CONTRACTS_ROOT / f"{object_type}.json"
    if not path.exists():
        raise FileNotFoundError(f"Contract not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _merge_defaults(payload: Any, shape: dict[str, Any]) -> Any:
    if isinstance(payload, dict):
        result = deepcopy(payload)
        for key, default in shape.get("defaults", {}).items():
            result.setdefault(key, deepcopy(default))
        for key, child_shape in shape.get("properties", {}).items():
            if key in result:
                result[key] = _merge_defaults(result[key], child_shape)
        if isinstance(shape.get("item_shape"), dict):
            for key, value in list(result.items()):
                if isinstance(value, list):
                    result[key] = [_merge_defaults(item, shape["item_shape"]) for item in value]
        return result
    if isinstance(payload, list) and isinstance(shape.get("item_shape"), dict):
        return [_merge_defaults(item, shape["item_shape"]) for item in payload]
    return payload


def apply_defaults(document: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(document)
    for field, default in contract.get("field_defaults", {}).items():
        payload.setdefault(field, deepcopy(default))
    for field, shape in contract.get("field_shapes", {}).items():
        if field in payload:
            payload[field] = _merge_defaults(payload[field], shape)
    return payload


def _validate_type(field_path: str, value: Any, expected_type: str, errors: list[str]) -> None:
    py_type = TYPE_MAP[expected_type]
    if not isinstance(value, py_type):
        if expected_type == "number" and isinstance(value, bool):
            errors.append(f"field {field_path} expected number got bool")
        else:
            errors.append(f"field {field_path} expected {expected_type} got {type(value).__name__}")


def _validate_shape(field_path: str, value: Any, shape: dict[str, Any], errors: list[str]) -> None:
    expected_type = shape.get("type")
    if value is None:
        if not shape.get("nullable", False):
            errors.append(f"field {field_path} not nullable")
        return
    if expected_type:
        _validate_type(field_path, value, expected_type, errors)
        if errors and errors[-1].startswith(f"field {field_path} expected"):
            return
    if "enum" in shape and value not in shape["enum"]:
        errors.append(f"field {field_path} must be one of {shape['enum']}, got {value}")
    if isinstance(value, dict):
        properties = shape.get("properties", {})
        required = set(shape.get("required", []))
        allow_unknown = shape.get("allow_unknown", True)
        for key in required:
            if key not in value:
                errors.append(f"missing required field: {field_path}.{key}")
        if not allow_unknown:
            unknown = set(value.keys()) - set(properties.keys()) - set(shape.get("nullable", []))
            for key in sorted(unknown):
                errors.append(f"unknown field: {field_path}.{key}")
        for key, child_value in value.items():
            if key in properties:
                _validate_shape(f"{field_path}.{key}", child_value, properties[key], errors)
    if isinstance(value, list):
        min_items = shape.get("min_items")
        if min_items is not None and len(value) < min_items:
            errors.append(f"field {field_path} must have at least {min_items} items")
        item_shape = shape.get("item_shape")
        item_enum = shape.get("item_enum")
        item_type = shape.get("item_type")
        for index, item in enumerate(value):
            item_path = f"{field_path}[{index}]"
            if item_type:
                _validate_type(item_path, item, item_type, errors)
            if item_enum and item not in item_enum:
                errors.append(f"field {item_path} must be one of {item_enum}, got {item}")
            if item_shape:
                _validate_shape(item_path, item, item_shape, errors)


def validate_contract_document(object_type: str, document: dict[str, Any]) -> dict[str, Any]:
    contract = load_contract(object_type)
    payload = apply_defaults(document, contract)
    errors: list[str] = []

    if payload.get("object_type") != contract["object_type"]:
        errors.append(f"object_type mismatch: expected {contract['object_type']} got {payload.get('object_type')}")
    if payload.get("schema_version") != contract["schema_version"]:
        errors.append(f"schema_version mismatch: expected {contract['schema_version']} got {payload.get('schema_version')}")

    required = set(contract.get("required_fields", []))
    nullable = set(contract.get("nullable_fields", []))
    field_types = contract.get("field_types", {})
    enum_constraints = contract.get("enum_constraints", {})
    allow_unknown = contract.get("unknown_fields_policy", "reject") != "reject"

    for field in required:
        if field not in payload:
            errors.append(f"missing required field: {field}")

    if not allow_unknown:
        known = set(required) | set(nullable) | set(field_types.keys()) | set(contract.get("field_defaults", {}).keys()) | set(contract.get("field_shapes", {}).keys())
        for field in sorted(set(payload.keys()) - known):
            errors.append(f"unknown field: {field}")

    for field, expected_type in field_types.items():
        if field not in payload:
            continue
        value = payload[field]
        if value is None:
            if field not in nullable:
                errors.append(f"field not nullable: {field}")
            continue
        _validate_type(field, value, expected_type, errors)

    for field, allowed in enum_constraints.items():
        if field in payload and payload[field] is not None and payload[field] not in allowed:
            errors.append(f"field {field} must be one of {allowed}, got {payload[field]}")

    for field, shape in contract.get("field_shapes", {}).items():
        if field in payload:
            _validate_shape(field, payload[field], shape, errors)

    if errors:
        raise ContractValidationError("; ".join(errors))
    return payload


def contract_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for path in sorted(Path(CONTRACTS_ROOT).glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        versions[doc["object_type"]] = doc["schema_version"]
    return versions
