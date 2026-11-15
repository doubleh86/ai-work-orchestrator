"""Planning conversation intent, recovery context and response representations."""

from __future__ import annotations

import re
from pathlib import Path

from ..models import PlanningMessageRole, RunState, RunStep, Stage, TechStackDecisionStatus, WorkTask
from .contracts import Plan


PLANNING_CONVERSATION_CONTEXT_CHARACTERS = 32_000


PLANNING_APPLY_TARGET_PATTERN = re.compile("(?:계획|플랜|태스크|테스크|작업\\s*목록|\\bplans?(?=\\b|[가-힣])|\\btasks?(?=\\b|[가-힣]))", re.IGNORECASE)


PLANNING_APPLY_COMMAND_PATTERN = re.compile(
    r"(?:반영|적용|갱신|업데이트|생성|수정|변경|추가|정리|만들|넣|바꾸)"
    r"\s*(?:해\s*줘|해\s*주세요|해주세요|해줘|해|하자|하라|해라|"
    r"어\s*줘|어\s*주세요|어줘|어주세요|어|자|시켜\s*줘|"
    r"부탁(?:해|합니다)?|해\s*줄\s*수\s*있|어\s*줄\s*수\s*있)",
    re.IGNORECASE,
)


PLANNING_APPLY_SHORT_PATTERN = re.compile(
    r"(?:계획|플랜|태스크|테스크|작업\s*목록|"
    r"\bplans?(?=\b|[가-힣])|\btasks?(?=\b|[가-힣]))"
    r".{0,24}(?:반영|적용|갱신|업데이트|생성|변경|추가)\s*[.!~]*$",
    re.IGNORECASE,
)


PLANNING_APPLY_ENGLISH_PATTERN = re.compile(
    r"(?:\b(?:apply|update|create|generate|revise)\b.{0,32}"
    r"\b(?:plans?|tasks?)\b|\b(?:plans?|tasks?)\b.{0,32}"
    r"\b(?:apply|update|create|generate|revise)\b)",
    re.IGNORECASE,
)


PLANNING_APPLY_META_PATTERN = re.compile(
    r"(?:[`'\"‘’“”]|라고\s*(?:말|하|쓰)|문구|예시|방법|버튼|어떻게\s*(?:말|요청)|"
    r"하면\s*(?:돼|되|됩)|해도\s*(?:돼|되|됩)|"
    r"\b(?:how|example|button|what\s+if)\b)",
    re.IGNORECASE,
)


PLANNING_APPLY_BARE_PATTERN = re.compile(
    r"^반영(?:\s*해\s*(?:줘|주세요)|\s*해주세요|\s*해줘)?\s*[.!！~～]*$",
    re.IGNORECASE,
)


PLANNING_APPLY_NEGATIVE_PATTERN = re.compile(
    r"(?:반영|적용|갱신|업데이트).{0,12}(?:하지\s*마|하지\s*말|말아|금지|제외|취소)|"
    r"(?:안|못)\s*(?:반영|적용|갱신|업데이트)",
    re.IGNORECASE,
)


PLANNING_APPLY_OTHER_TARGET_PATTERN = re.compile(
    r"(?:문서|README|파일|코드|커밋|브랜치|main|메인)\s*(?:에|으로)?\s*만\s*(?:반영|적용|갱신|업데이트)",
    re.IGNORECASE,
)


PLANNING_APPLY_CONTROL_PATTERN = re.compile(
    r"(?:(?:지금까지(?:의)?|기존|현재|방금|앞서|이전(?:의)?|위(?:의)?|논의한|정리한|결정한|합의한|대화한|이렇게|그렇게|이|그|해당)\s*)*"
    r"(?:(?:내용|논의|대화|방향|결정|요청|사항|결론|요구\s*사항|(?:검증|완료|수용|실행|테스트)\s*(?:조건|기준))"
    r"(?:들)?(?:을|를|으로|로|대로|에)?\s*)?"
    + PLANNING_APPLY_TARGET_PATTERN.pattern
    + r"\s*(?:에|을|를|으로|로)?\s*(?:"
    + PLANNING_APPLY_COMMAND_PATTERN.pattern
    + r"|반영|적용|갱신|업데이트|생성|수정|변경|추가|정리)\s*[.!！~～]*",
    re.IGNORECASE,
)


PLANNING_APPLY_ENGLISH_CONTROL_PATTERN = re.compile(
    r"(?:please\s+)?(?:apply|update|create|generate|revise)\s+(?:(?:the|this|current|existing)\s+)?(?:plans?|tasks?)"
    r"(?:\s+(?:with|from|using)\s+(?:(?:this|that|the|our|previous)\s+)?(?:decision|discussion|conversation|changes|content))?\s*[.!~]*",
    re.IGNORECASE,
)


def planning_message_requests_initial_tasks(state: RunState, message: str) -> bool:
    if state.tasks or state.archive is not None or state.repository_intent == "new_project":
        return False
    if state.stage not in {Stage.NEEDS_CLARIFICATION, Stage.PLANNED} and not (
        state.stage == Stage.FAILED and state.failed_step == RunStep.PLANNING
    ):
        return False
    normalized = " ".join(message.strip().split())
    if (PLANNING_APPLY_META_PATTERN.search(normalized) or PLANNING_APPLY_NEGATIVE_PATTERN.search(normalized)
            or re.search(r"[?？]|(?:하지|추지|치지)\s*(?:마|말)|나중에|내일|되면|하면|(?:알려|설명|보여)\s*줘", normalized)):
        return False
    if planning_message_requests_apply(message):
        return True
    return bool(re.search(r"(?:합의|논의|정리|결정)한\s*(?:\d+\s*개\s*)?(?:작업|태스크|테스크|tasks?)", normalized, re.IGNORECASE)
                and re.search(r"(?:이어서|계속)?\s*진행\s*(?:해\s*(?:줘|주세요)|하자|부탁(?:해|합니다)?)[.!~！～]*$", normalized))


def planning_message_requests_apply(message: str) -> bool:
    normalized = " ".join(message.strip().split())
    if (
        not normalized
        or PLANNING_APPLY_META_PATTERN.search(normalized)
        or PLANNING_APPLY_NEGATIVE_PATTERN.search(normalized)
        or PLANNING_APPLY_OTHER_TARGET_PATTERN.search(normalized)
    ):
        return False
    if PLANNING_APPLY_BARE_PATTERN.fullmatch(normalized):
        return True
    if not PLANNING_APPLY_TARGET_PATTERN.search(normalized):
        return False
    return bool(
        PLANNING_APPLY_COMMAND_PATTERN.search(normalized)
        or PLANNING_APPLY_SHORT_PATTERN.search(normalized)
        or PLANNING_APPLY_ENGLISH_PATTERN.search(normalized)
    )


def planning_message_is_apply_control(message: str) -> bool:
    """기존 논의를 반영하는 제어 문장과 구체적인 새 요구를 구분한다."""
    normalized = " ".join(message.strip().split())
    if not planning_message_requests_apply(normalized):
        return False
    return bool(
        PLANNING_APPLY_BARE_PATTERN.fullmatch(normalized)
        or PLANNING_APPLY_CONTROL_PATTERN.fullmatch(normalized)
        or PLANNING_APPLY_ENGLISH_CONTROL_PATTERN.fullmatch(normalized)
    )


def planning_response_text(plan: Plan) -> str:
    lines = [plan.summary.strip() or "계획을 검토했습니다."]
    if plan.tech_stack_options:
        lines.extend(["", f"기술 구성 {len(plan.tech_stack_options)}개를 비교할 수 있습니다."])
    if plan.questions:
        lines.extend(["", "확인이 필요한 내용"])
        lines.extend(f"• {question}" for question in plan.questions)
    else:
        lines.extend(["", f"Task {len(plan.tasks)}개로 계획했습니다."])
        recommended = [task for task in plan.tasks if task.provider_id]
        if recommended:
            lines.extend(["", "추천 실행 프로필"])
            lines.extend(
                f"• {task.title}: {task.model or 'provider 설정'} · {task.provider_id} · {task.reasoning_effort or 'provider 설정'}"
                for task in recommended
            )
    return "\n".join(lines)


def clarification_context(state: RunState) -> str:
    sections: list[str] = []
    plan_path = Path(state.structured_plan_path) if state.structured_plan_path else None
    if plan_path is not None and plan_path.is_file():
        previous_plan = plan_path.read_text(encoding="utf-8").strip()
        sections.append(f"### Previous structured plan\n\n```json\n{previous_plan}\n```")
    transcript_lines = [
        ("User" if message.role == PlanningMessageRole.USER else "Planning AI") + ": " + message.text.strip()
        for message in state.planning_messages
        if message.text.strip()
        and not (
            message.role == PlanningMessageRole.USER
            and planning_message_is_apply_control(message.text)
        )
    ]
    transcript = "\n\n".join(transcript_lines)
    if len(transcript) > PLANNING_CONVERSATION_CONTEXT_CHARACTERS:
        transcript = "[Earlier conversation omitted to fit the recovery context.]\n\n" + transcript[-PLANNING_CONVERSATION_CONTEXT_CHARACTERS:]
    if transcript:
        sections.append(f"### Saved Planning conversation\n\n{transcript}")
    elif state.clarification_paths:
        latest_user_message = Path(state.clarification_paths[-1]).read_text(encoding="utf-8").strip()
        if latest_user_message:
            sections.append(f"### Latest user message\n\n{latest_user_message}")
    return "\n\n".join(sections)


def planning_materialization_prompt(state: RunState) -> str:
    latest_user_message = next(
        (
            message.text.strip()
            for message in reversed(state.planning_messages)
            if message.role == PlanningMessageRole.USER
            and message.text.strip()
            and not planning_message_requests_apply(message.text)
        ),
        "",
    )
    latest_instruction = "\n\nLatest user instruction submitted with this action:\n\n" + latest_user_message if latest_user_message else ""
    stack_guidance = ""
    decision = state.current_tech_stack_decision()
    if state.repository_intent == "new_project" and (decision is None or decision.status != TechStackDecisionStatus.CONFIRMED):
        stack_guidance = """

Technology candidate refresh: choosing or approving a displayed stack is handled
by the explicit user selection UI. Do not repeat that choice in questions or
unresolved_constraints. Use the user's answers to resolve previous questions.
If only the stack choice remains, return questions: [] with technology options
and no Tasks so the user can confirm a candidate. Still ask about genuinely
missing product requirements, target environments, or other necessary constraints.
"""
    return f"""Continue the existing Planning conversation.

Materialize the decisions and constraints discussed so far into an updated
structured implementation plan. Reuse the planning documents and repository
context already inspected; perform additional discovery only when the conversation
genuinely requires it. A follow-up may return clarification questions without a
task draft when the user's decision is still required. Return exactly one
single-line AI_PLAN_RESULT payload and no Markdown fences.{stack_guidance}{latest_instruction}
"""


def task_plan_draft(task: WorkTask) -> dict[str, object]:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "capabilities": task.capabilities,
        "depends_on": task.dependencies,
        "is_prerequisite": task.is_prerequisite,
        "acceptance_criteria": task.acceptance_criteria,
        "expected_paths": task.expected_paths,
        "forbidden_paths": task.forbidden_paths,
        "verify_commands": task.verify_commands,
        "risk_level": task.risk_level.value,
        "provider_id": task.provider_id,
        "model": task.model,
        "reasoning_effort": task.reasoning_effort,
    }


def planning_conversation_id(state: RunState) -> str:
    return f"planning:{state.id}"
