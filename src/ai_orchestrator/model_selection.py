from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from .models import EffortMode, ProfileSource, RiskLevel, WorkTask


CODEX_SOL_MODEL = "gpt-6.1-sol"
CODEX_TERRA_MODEL = "gpt-6.1-terra"
CODEX_LUNA_MODEL = "gpt-6-luna"
AUTOMATIC_CODEX_MODELS = (CODEX_SOL_MODEL, CODEX_TERRA_MODEL, CODEX_LUNA_MODEL)
CLAUDE_SONNET_MODEL = "sonnet"
CLAUDE_OPUS_MODEL = "opus"
AUTOMATIC_CLAUDE_MODELS = (CLAUDE_SONNET_MODEL, CLAUDE_OPUS_MODEL)

_SENSITIVE_WORDS = (
    "auth", "security", "permission", "database", "migration", "schema", "contract", "state transition",
    "concurren", "race condition", "conflict", "sdk", "timeout", "credential", "payment", "public api",
    "인증", "권한", "보안", "데이터베이스", "마이그레이션", "스키마", "계약", "상태 전이", "동시",
    "충돌", "시간 초과", "결제", "잠금", "실패 원인", "검증 실패", "범위 검사",
)
_SMALL_EDIT_WORDS = (
    "문구", "오탈자", "맞춤법", "라벨", "색상", "간격", "문서", "툴팁", "반복 치환",
    "typo", "documentation", "readme", "tooltip", "copy text", "wording", "stylesheet",
)
_SMALL_EDIT_CAPABILITIES = {"general", "frontend", "ui", "docs", "documentation", "style"}


@dataclass(frozen=True, slots=True)
class ModelSelection:
    model: str
    reasoning_effort: str
    reason: str


def small_codex_task(task: WorkTask) -> bool:
    """Require affirmative, bounded evidence before using the smaller model."""
    text = " ".join((task.title, task.description, *task.acceptance_criteria)).casefold()
    paths = [path.replace("\\", "/").casefold() for path in task.expected_paths]
    return bool(
        task.risk_level == RiskLevel.LOW
        and not task.is_prerequisite and not task.conflict_group
        and task.capabilities
        and set(task.capabilities) <= _SMALL_EDIT_CAPABILITIES
        and 0 < len(paths) <= 3
        and all(not any(mark in path for mark in ("*", "?", "..")) for path in paths)
        and all(PurePosixPath(path).suffix in {".md", ".txt", ".rst", ".css", ".scss", ".tsx", ".jsx", ".html"} for path in paths)
        and not any(word in " ".join((text, *paths)) for word in _SENSITIVE_WORDS)
        and any(word in text for word in _SMALL_EDIT_WORDS)
    )


def select_codex_model(
    mode: EffortMode, *, purpose: str, task: WorkTask | None = None, reasoning_effort: str = "",
) -> ModelSelection:
    if purpose != "task":
        return ModelSelection(CODEX_SOL_MODEL, "high", "기획·원인 판단은 6.1 Sol 유지")
    if (mode == EffortMode.ECONOMY and task is not None and small_codex_task(task)
            and reasoning_effort not in {"xhigh", "max", "ultra"}):
        return ModelSelection(CODEX_LUNA_MODEL, "high", "절약 · 범위가 명확한 낮은 위험의 작은 수정")
    if task is not None:
        text = " ".join((task.title, task.description, *task.acceptance_criteria, *task.expected_paths)).casefold()
        important = task.risk_level == RiskLevel.HIGH or any(word in text for word in _SENSITIVE_WORDS)
    else:
        important = True
    if (mode == EffortMode.BALANCED and task is not None and small_codex_task(task)
            and reasoning_effort not in {"xhigh", "max", "ultra"}):
        decision = ModelSelection(CODEX_TERRA_MODEL, "medium", "균형 · 6.1 Terra로 범위가 명확한 낮은 위험의 작은 수정")
    elif mode == EffortMode.FOCUSED:
        decision = ModelSelection(CODEX_SOL_MODEL, "xhigh" if important else "high", "집중 · 6.1 Sol 추론 강화")
    else:
        decision = ModelSelection(CODEX_SOL_MODEL, "high" if important else "medium",
                                  "중요 계약·불확실한 작업은 6.1 Sol" if important else "일반 구현은 6.1 Sol")
    efforts = ("low", "medium", "high", "xhigh", "max", "ultra")
    if mode != EffortMode.ECONOMY and reasoning_effort in efforts and efforts.index(reasoning_effort) > efforts.index(decision.reasoning_effort):
        return ModelSelection(decision.model, reasoning_effort, f"{decision.reason} · 권장 추론 유지")
    return decision


def automatic_codex_profile(source: ProfileSource, model: str) -> bool:
    return source not in {ProfileSource.MANUAL, ProfileSource.LEGACY} or source == ProfileSource.MANUAL and not model.strip()


def automatic_claude_profile(source: ProfileSource, model: str) -> bool:
    return (source not in {ProfileSource.MANUAL, ProfileSource.LEGACY} and model.strip() in {"", *AUTOMATIC_CLAUDE_MODELS}
            or source == ProfileSource.MANUAL and not model.strip())


def select_claude_model(
    mode: EffortMode, *, purpose: str, task: WorkTask | None = None, reasoning_effort: str = "",
) -> ModelSelection:
    if purpose != "task":
        return ModelSelection(CLAUDE_OPUS_MODEL, "high", "기획·원인 판단은 Opus")
    important = task is None
    if task is not None:
        text = " ".join((task.title, task.description, *task.acceptance_criteria, *task.expected_paths)).casefold()
        paths = [path.replace("\\", "/") for path in task.expected_paths]
        important = bool(
            task.risk_level == RiskLevel.HIGH or task.is_prerequisite or task.conflict_group
            or set(task.capabilities) & {"architecture", "security", "concurrency", "migration"}
            or any(word in text for word in (*_SENSITIVE_WORDS, "architecture", "아키텍처", "설계", "복잡", "대규모", "cross-module"))
            or not paths or len(paths) >= 6 or any(any(mark in path for mark in ("*", "?", "..")) for path in paths)
            or reasoning_effort in {"xhigh", "max"}
        )
    if mode == EffortMode.FOCUSED:
        decision = ModelSelection(CLAUDE_OPUS_MODEL, "xhigh" if important else "high", "집중 · Opus로 추론 강화")
    elif important:
        decision = ModelSelection(CLAUDE_OPUS_MODEL, "high", "중요 계약·복잡하거나 범위가 불명확한 작업은 Opus")
    else:
        decision = ModelSelection(CLAUDE_SONNET_MODEL, "low" if mode == EffortMode.ECONOMY else "medium",
                                  "절약 · 일반 구현은 Sonnet" if mode == EffortMode.ECONOMY else "일반 구현은 Sonnet")
    efforts = ("low", "medium", "high", "xhigh", "max")
    if mode != EffortMode.ECONOMY and reasoning_effort in efforts and efforts.index(reasoning_effort) > efforts.index(decision.reasoning_effort):
        return ModelSelection(decision.model, reasoning_effort, f"{decision.reason} · 권장 추론 유지")
    return decision
