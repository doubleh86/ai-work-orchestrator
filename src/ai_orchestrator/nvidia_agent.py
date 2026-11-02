"""NVIDIA coding through the existing external-agent process boundary."""

from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from typing import Iterator, Mapping

from .config import AgentConfig, Config, NVIDIA_MODEL_PRESETS
from .usage import TokenCounts, UsageObservation, usage_now


NVIDIA_AGENT_ID = "nvidia-experimental"
NVIDIA_SETUP = "OpenCode CLI를 설치하고 설정 → AI 연결에서 NVIDIA API 키를 등록해 주세요. NVIDIA_API_KEY 환경 변수도 지원합니다."
_NONEMPTY_CONTENT_MODELS = frozenset({"nvidia/nemotron-3-super-120b-a12b", "nvidia/nemotron-3-ultra-550b-a55b"})
_request_api_key: ContextVar[str | None] = ContextVar("nvidia_api_key", default=None)
_request_model_keys: ContextVar[dict[str, str] | None] = ContextVar("nvidia_model_api_keys", default=None)


class NvidiaAgentError(ValueError):
    pass


class NvidiaCompletionError(NvidiaAgentError):
    """The agent did not supply an acceptable final answer."""


@contextmanager
def nvidia_credential_scope(value: object, model_keys: object = None) -> Iterator[None]:
    if value is not None and (
        not isinstance(value, str) or not value.strip() or len(value) > 4096 or re.search(r"[\x00-\x1f\x7f]", value)
    ):
        raise NvidiaAgentError("Invalid NVIDIA credential")
    selected: dict[str, str] = {}
    if model_keys is not None:
        if not isinstance(model_keys, dict) or len(model_keys) > 128:
            raise NvidiaAgentError("Invalid NVIDIA model credentials")
        for model, key in model_keys.items():
            if (not isinstance(model, str) or len(model) > 200 or not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._/-]+", model)
                    or not isinstance(key, str) or not key.strip() or len(key) > 4096 or re.search(r"[\x00-\x1f\x7f]", key)):
                raise NvidiaAgentError("Invalid NVIDIA model credentials")
            selected[model] = key.strip()
    token = _request_api_key.set(value.strip() if isinstance(value, str) else None)
    model_token = _request_model_keys.set(selected)
    try:
        yield
    finally:
        _request_model_keys.reset(model_token)
        _request_api_key.reset(token)


def current_nvidia_api_key() -> str | None:
    return _request_api_key.get()


def current_nvidia_model_keys() -> dict[str, str]:
    return dict(_request_model_keys.get() or {})


def with_nvidia_agent(config: Config) -> Config:
    """Expose a manual trial profile without changing project configuration."""
    if any(agent.provider_id == "nvidia" or agent.id == NVIDIA_AGENT_ID for agent in config.agents):
        return config
    agent = AgentConfig(
        id=NVIDIA_AGENT_ID, provider_id="nvidia", model=NVIDIA_MODEL_PRESETS[0],
        capabilities=("general", "review"), command=(), max_tasks=1, manual_only=True,
    )
    return replace(config, agents=(*config.agents, agent))


def nvidia_command(model: str) -> tuple[str, ...]:
    # OpenCode splits at the first slash: provider / model identifier.
    selected = model.strip() or NVIDIA_MODEL_PRESETS[0]
    if any(character in selected for character in ("\x00", "\n", "\r")):
        raise NvidiaAgentError("NVIDIA 모델 이름은 한 줄이어야 합니다.")
    return ("opencode", "--pure", "run", "--format", "json", "--agent", "orchestrator", "--model", f"nvidia/{selected}")


def nvidia_key_configured(environment: Mapping[str, str] | None = None, *, api_key: str | None = None) -> bool:
    selected = os.environ if environment is None else environment
    return bool((api_key if api_key is not None else selected.get("NVIDIA_API_KEY", "")).strip())


def nvidia_environment(environment: Mapping[str, str], *, model: str, action: str, api_key: str | None = None) -> dict[str, str]:
    """Configure tools without putting credentials into config or argv."""
    selected = model.strip() or NVIDIA_MODEL_PRESETS[0]
    file_rules = {"*": "allow"}
    for pattern in ("*.env", "*.env.*", ".env", ".env.*", "**/.env", "**/.env.*", "*.pem", "*.key", "**/.git/**",
                    "**/.aws/**", "**/.ssh/**", "**/.codex/**", "**/auth.json", "**/credentials*", "**/secrets*"):
        file_rules[pattern] = "deny"
    commands = {"*": "deny", "pwd": "allow", "git status*": "allow", "git diff*": "allow", "git log*": "allow",
                "git ls-files*": "allow"}
    if action != "review":
        for pattern in ("dotnet build*", "dotnet test*", "dotnet restore*", "python -m pytest*", "python -m compileall*",
                        "npm test*", "npm run build*", "npm run typecheck*", "node --test*"):
            commands[pattern] = "allow"
    permission: dict[str, object] = {
        "*": "deny", "read": file_rules, "glob": "allow", "grep": "allow", "list": "allow",
        "edit": "deny" if action == "review" else file_rules, "bash": commands, "external_directory": "deny",
        "task": "deny", "question": "deny", "webfetch": "deny", "websearch": "deny", "skill": "deny",
    }
    model_settings: dict[str, object] = {"name": selected, "tool_call": True}
    if selected in _NONEMPTY_CONTENT_MODELS:
        model_settings["options"] = {"chat_template_kwargs": {"force_nonempty_content": True}}
    config = {
        "$schema": "https://opencode.ai/config.json", "enabled_providers": ["nvidia"],
        "share": "disabled", "autoupdate": False, "snapshot": False, "lsp": False, "formatter": False,
        "provider": {"nvidia": {
            "npm": "@ai-sdk/openai-compatible", "name": "NVIDIA",
            "options": {"baseURL": "https://integrate.api.nvidia.com/v1", "apiKey": "{env:NVIDIA_API_KEY}"},
            "models": {selected: model_settings},
        }},
        "permission": permission,
        "agent": {"orchestrator": {"mode": "primary", "steps": 60, "permission": permission,
            "prompt": "Follow the supplied task. Reply in Korean. Never read secrets, commit, merge, push, or deploy. "
                      "Do not request interactive approval. Report unavailable tools or incomplete work explicitly. "
                      "If an edit cannot match the file, reread the relevant lines and use the exact current text. "
                      "End with a nonempty Korean final answer describing completed work, checks, and any remaining work. "
                      "Never claim success for a failed tool or an unperformed check."}},
    }
    result = dict(environment)
    if api_key is not None:
        result["NVIDIA_API_KEY"] = api_key
    result.update({
        "OPENCODE_CONFIG_CONTENT": json.dumps(config, ensure_ascii=False),
        "OPENCODE_PERMISSION": json.dumps(permission), "OPENCODE_DISABLE_AUTOUPDATE": "true",
        "OPENCODE_DISABLE_DEFAULT_PLUGINS": "true", "OPENCODE_DISABLE_LSP_DOWNLOAD": "true",
        "OPENCODE_DISABLE_MODELS_FETCH": "true", "OPENCODE_DISABLE_CLAUDE_CODE": "true",
    })
    return result


def redact_nvidia_output(output: str, environment: Mapping[str, str]) -> str:
    key = environment.get("NVIDIA_API_KEY", "").strip()
    if key:
        output = output.replace(key, "[REDACTED]")
    return re.sub(r"nvapi-[A-Za-z0-9_-]+", "[REDACTED]", output)


def parse_nvidia_output(output: str) -> tuple[str, UsageObservation | None]:
    """Do not accept OpenCode's zero exit code as proof of a finished turn."""
    texts: list[str] = []
    finished = False
    totals: dict[str, int] = {}
    seen_steps: set[str] = set()
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "step_start":
            texts = []
            finished = False
        if kind == "error":
            error = event.get("error")
            data = error.get("data", {}) if isinstance(error, dict) else {}
            message = data.get("message") if isinstance(data, dict) else None
            status_code = data.get("statusCode") if isinstance(data, dict) else None
            if type(status_code) is int:
                message = f"HTTP {status_code}: {message or 'NVIDIA 요청 실패'}"
            raise NvidiaAgentError(str(message or "NVIDIA 에이전트 실행에 실패했습니다."))
        part = event.get("part")
        if not isinstance(part, dict):
            continue
        if kind == "text" and isinstance(part.get("text"), str):
            texts.append(part["text"])
        if kind != "step_finish":
            continue
        reason = part.get("reason")
        if reason in {"stop", "end_turn"}:
            finished = True
        elif reason not in {"tool-calls", "tool_calls"}:
            raise NvidiaCompletionError(f"NVIDIA 응답이 완료되지 않았습니다: {reason or '종료 사유 없음'}")
        else:
            finished = False
        step_id = str(part.get("id") or "")
        if step_id and step_id in seen_steps:
            continue
        if step_id:
            seen_steps.add(step_id)
        tokens = part.get("tokens")
        if not isinstance(tokens, dict):
            continue
        for source, target in (("input", "input_tokens"), ("output", "output_tokens"), ("reasoning", "reasoning_output_tokens")):
            value = tokens.get(source)
            if type(value) is int and value >= 0:
                totals[target] = totals.get(target, 0) + value
    if not finished:
        raise NvidiaCompletionError("NVIDIA의 완료 응답을 확인하지 못했습니다. 실행 로그를 확인해 주세요.")
    if not texts or not "".join(texts).strip():
        raise NvidiaCompletionError("NVIDIA가 응답을 종료했지만 최종 답변을 보내지 않았습니다. 변경된 파일을 확인한 뒤 다시 시도해 주세요.")
    usage = None
    # OpenCode may emit zero placeholders when the backend omits usage.
    if any(totals.values()):
        usage = UsageObservation(
            1, counts=TokenCounts(**totals), source_kind="turn_total", missing_reason="", observed_at=usage_now(), finalized=True,
        )
    return "\n".join(texts), usage
