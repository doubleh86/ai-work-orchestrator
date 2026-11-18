"""App-wide Codex model choices shared by the desktop, CLI, and MCP."""

from __future__ import annotations

import json
from pathlib import Path

from .app_paths import application_config_root
from .file_lock import exclusive_file_lock
from .persistence.atomic import write_json_atomic


CODEX_SOL_MODEL = "gpt-6.2-sol"
CODEX_ASTRA_MODEL = "gpt-6.2-astra"
CODEX_TERRA_MODEL = "gpt-6.1-terra"
CODEX_LUNA_MODEL = "gpt-6-luna"
CODEX_LEGACY_SOL_MODEL = "gpt-6.1-sol"
CODEX_LEGACY_ASTRA_MODEL = "gpt-6-astra"
DEFAULT_CODEX_MODELS = (CODEX_SOL_MODEL, CODEX_ASTRA_MODEL, CODEX_TERRA_MODEL, CODEX_LUNA_MODEL)
CODEX_MODEL_PRESETS = (*DEFAULT_CODEX_MODELS, CODEX_LEGACY_SOL_MODEL, CODEX_LEGACY_ASTRA_MODEL)
CODEX_SOL_MODELS = (CODEX_SOL_MODEL, CODEX_LEGACY_SOL_MODEL)
CODEX_ASTRA_MODELS = (CODEX_ASTRA_MODEL, CODEX_LEGACY_ASTRA_MODEL)


class CodexModelPreferenceError(ValueError):
    pass


def _settings_path() -> Path:
    return application_config_root() / "codex-models.json"


def _validated_models(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise CodexModelPreferenceError("사용할 Codex 모델을 하나 이상 선택해 주세요.")
    if any(not isinstance(model, str) or model not in CODEX_MODEL_PRESETS for model in value) or len(set(value)) != len(value):
        raise CodexModelPreferenceError("Codex 모델 목록을 다시 불러와 선택해 주세요.")
    return tuple(model for model in CODEX_MODEL_PRESETS if model in value)


def _read_models(path: Path) -> tuple[str, ...]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return DEFAULT_CODEX_MODELS
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CodexModelPreferenceError("Codex 모델 설정을 읽지 못했습니다.") from exc
    if not isinstance(raw, dict) or type(raw.get("schema_version")) is not int or raw["schema_version"] != 1:
        raise CodexModelPreferenceError("Codex 모델 설정 형식이 올바르지 않습니다.")
    return _validated_models(raw.get("enabled_models"))


def enabled_codex_models() -> tuple[str, ...]:
    return _read_models(_settings_path())


def codex_model_order(*, preferred: str = CODEX_SOL_MODEL, enabled: tuple[str, ...] | None = None) -> tuple[str, ...]:
    allowed = enabled_codex_models() if enabled is None else enabled
    primary = (*CODEX_ASTRA_MODELS, *CODEX_SOL_MODELS) if preferred in CODEX_ASTRA_MODELS else (*CODEX_SOL_MODELS, *CODEX_ASTRA_MODELS)
    compact = (CODEX_TERRA_MODEL, CODEX_LUNA_MODEL)
    alternatives = (*compact, *primary) if preferred in compact else (*primary, *compact)
    return tuple(model for model in dict.fromkeys((preferred, *alternatives)) if model in allowed)


def save_codex_models(models: list[str], *, expected_models: list[str]) -> tuple[str, ...]:
    selected = _validated_models(models)
    expected = _validated_models(expected_models)
    path = _settings_path()
    with exclusive_file_lock(path.with_suffix(".lock")):
        current = _read_models(path)
        if selected == current:
            return current
        if current != expected:
            raise CodexModelPreferenceError("다른 곳에서 모델 설정이 바뀌었습니다. 다시 불러와 주세요.")
        write_json_atomic(path, {"schema_version": 1, "enabled_models": list(selected)})
    return selected
