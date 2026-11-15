"""Compose provider arguments without running commands or owning sessions."""

from __future__ import annotations

import uuid
from typing import Callable

from ..config import AgentConfig
from ..errors import PipelineError
from ..nvidia_agent import nvidia_command


def agent_command(agent: AgentConfig, action: str) -> tuple[str, ...]:
    if agent.provider_id == "nvidia":
        return nvidia_command(agent.model)
    if action == "review" and agent.review_command:
        return agent.review_command
    return agent.command


def command_with_model(agent: AgentConfig, command_template: tuple[str, ...], model: str) -> tuple[str, ...]:
    if agent.provider_id == "nvidia":
        return nvidia_command(model or agent.model)
    if not model:
        return command_template
    if agent.provider_id == "codex":
        return command_template
    if agent.provider_id != "claude":
        if model == agent.model:
            return command_template
        raise PipelineError(f"model override is supported only for SDK Codex or Claude providers: {agent.provider_id}")

    command: list[str] = []
    skip_next = False
    for argument in command_template:
        if skip_next:
            skip_next = False
            continue
        if argument in {"-m", "--model"}:
            skip_next = True
            continue
        if argument.startswith("--model="):
            continue
        command.append(argument)
    if skip_next:
        raise PipelineError("provider command has model flag without a value")

    insert_at = 1
    command[insert_at:insert_at] = ["--model", model]
    return tuple(command)


def command_with_reasoning_effort(
    agent: AgentConfig, command_template: tuple[str, ...], effort: str, model: str = "", *,
    validate_effort: Callable[[AgentConfig, str, str], None],
) -> tuple[str, ...]:
    if not effort:
        return command_template
    validate_effort(agent, effort, model)
    if agent.provider_id == "codex":
        return command_template
    if agent.provider_id != "claude":
        raise PipelineError(f"reasoning effort override is supported only for SDK Codex or claude providers: {agent.provider_id}")

    command: list[str] = []
    index = 0
    while index < len(command_template):
        argument = command_template[index]
        if argument == "--effort":
            if index + 1 >= len(command_template):
                raise PipelineError("Claude command has effort flag without a value")
            index += 2
            continue
        if argument.startswith("--effort="):
            index += 1
            continue
        command.append(argument)
        index += 1

    insert_at = 1
    override = ["--effort", effort]
    command[insert_at:insert_at] = override
    return tuple(command)


def command_with_claude_session(
    agent: AgentConfig, command_template: tuple[str, ...], session_id: str, *, resume: bool,
) -> tuple[str, ...]:
    if agent.provider_id != "claude":
        raise PipelineError("Claude session flags require a Claude provider")
    try:
        normalized_session_id = str(uuid.UUID(session_id))
    except (AttributeError, TypeError, ValueError) as exc:
        raise PipelineError("Claude session id must be a valid UUID") from exc
    if normalized_session_id != session_id.casefold():
        raise PipelineError("Claude session id must use canonical UUID format")

    owned_flags = {"-c", "--continue", "-r", "--resume", "--session-id", "--fork-session", "--no-session-persistence"}
    for argument in command_template:
        normalized_argument = argument.casefold()
        if (
            normalized_argument in owned_flags
            or normalized_argument.startswith("--resume=")
            or normalized_argument.startswith("--session-id=")
        ):
            raise PipelineError("Claude planning command must not define session flags; the orchestrator owns the Planning chat session")

    command = list(command_template)
    flag = "--resume" if resume else "--session-id"
    command[1:1] = [flag, normalized_session_id]
    return tuple(command)
