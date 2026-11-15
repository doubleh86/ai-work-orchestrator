from __future__ import annotations

from ..application.errors import ApplicationError as RpcError
from ..code_style import ProjectCodeStylePreference


def object_params(params: object) -> dict[str, object]:
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise RpcError("invalid_params", "params must be an object")
    return params


def required_string(params: dict[str, object], name: str) -> str:
    value = params.get(name)
    if not isinstance(value, str) or not value.strip():
        raise RpcError("invalid_params", f"{name} must be a non-empty string")
    return value.strip()


def required_path_string(params: dict[str, object], name: str) -> str:
    value = params.get(name)
    if not isinstance(value, str) or not value:
        raise RpcError("invalid_params", f"{name} must be a non-empty string")
    return value


def main_change_selections(params: dict[str, object]) -> list[tuple[str, str]]:
    raw = params.get("selections")
    if not isinstance(raw, list) or not raw:
        raise RpcError("invalid_params", "selections must be a non-empty array")
    selections: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise RpcError("invalid_params", "each Main change selection must be an object")
        path = item.get("path")
        mode = item.get("mode")
        if not isinstance(path, str) or not path or not isinstance(mode, str) or mode not in {"staged", "whole"}:
            raise RpcError("invalid_params", "Main change selection requires path and staged/whole mode")
        selections.append((path, mode))
    return selections


def code_style_preference(params: dict[str, object]) -> ProjectCodeStylePreference:
    try:
        return ProjectCodeStylePreference.from_dict(params.get("preference"))
    except ValueError as exc:
        raise RpcError("invalid_params", str(exc)) from exc


def required_integer(params: dict[str, object], name: str) -> int:
    value = params.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RpcError("invalid_params", f"{name} must be a non-negative integer")
    return value


def optional_string(params: dict[str, object], name: str) -> str:
    value = params.get(name, "")
    if not isinstance(value, str):
        raise RpcError("invalid_params", f"{name} must be a string")
    return value.strip()


def nullable_string(params: dict[str, object], name: str) -> str | None:
    if name not in params:
        return None
    return optional_string(params, name)


def string_list(params: dict[str, object], name: str, *, required: bool = False) -> list[str]:
    value = params.get(name, [])
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise RpcError("invalid_params", f"{name} must be an array of non-empty strings")
    result = [item.strip() for item in value]
    if required and not result:
        raise RpcError("invalid_params", f"{name} must not be empty")
    return result


def boolean(params: dict[str, object], name: str, *, default: bool) -> bool:
    value = params.get(name, default)
    if not isinstance(value, bool):
        raise RpcError("invalid_params", f"{name} must be a boolean")
    return value


def string_map(params: dict[str, object], name: str) -> dict[str, str] | None:
    if name not in params:
        return None
    value = params[name]
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and key.strip() and isinstance(item, str)
        for key, item in value.items()
    ):
        raise RpcError("invalid_params", f"{name} must be an object with string values")
    return {str(key).strip(): str(item).strip() for key, item in value.items()}


def object_list(params: dict[str, object], name: str, *, required: bool = False) -> list[dict[str, object]]:
    value = params.get(name, [])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise RpcError("invalid_params", f"{name} must be an array of objects")
    if required and not value:
        raise RpcError("invalid_params", f"{name} must not be empty")
    return [dict(item) for item in value]


def required_approval(params: dict[str, object]) -> bool:
    if params.get("approved") is not True:
        raise RpcError("approval_required", "this operation requires explicit native approval")
    return True
