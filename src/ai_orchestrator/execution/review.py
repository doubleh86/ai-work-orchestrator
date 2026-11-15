from __future__ import annotations

import json
import re
from dataclasses import dataclass


REVIEW_MARKER = "AI_REVIEW_RESULT:"


class ReviewProtocolError(RuntimeError):
    """The reviewer response violates the result contract."""


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    run_id: str
    task_id: str
    cycle: int
    title: str
    capabilities: tuple[str, ...]
    risk_level: str
    expected_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    verify_commands: tuple[tuple[str, ...], ...]
    acceptance_criteria: tuple[str, ...]
    main_branch: str
    code_style_snapshot: str
    changed_path_evidence: str
    worktree_contract: str
    manual_verification: bool = False


def render_review_prompt(request: ReviewRequest) -> str:
    criteria = "\n".join(f"- {criterion}" for criterion in request.acceptance_criteria) or "- No explicit criteria in the legacy Markdown plan."
    expected = ", ".join(request.expected_paths) or "not specified"
    forbidden = ", ".join(request.forbidden_paths) or "none specified"
    commands = json.dumps(request.verify_commands, ensure_ascii=False)
    review_scope = (
        "The operator is recording a manual check against the existing commit. Review the implementation relevant to this Task's "
        "acceptance criteria at HEAD. Assess repository-observable criteria and report any concrete blockers. "
        "The operator records live-environment results separately."
        if request.manual_verification else
        f"Review the committed diff from `{request.main_branch}` to `HEAD` in the current\n"
        "worktree. Check correctness, regressions, tests, security, and scope."
    )
    return f"""# Independent code review

Run: {request.run_id}
Task: {request.task_id}
Review cycle: {request.cycle}
Assignment: {request.title}
Capabilities: {', '.join(request.capabilities)}
Risk: {request.risk_level}
Expected paths: {expected}
Forbidden paths: {forbidden}
Verification commands: {commands}

Acceptance criteria:
{criteria}

Fixed project code style snapshot:
{request.code_style_snapshot}

Actual changed-path code style evidence:
{request.changed_path_evidence}

{review_scope}
Do not edit, create, delete, stage, or commit any file. Do not merge, push, or deploy.

Worktree safety contract:
{request.worktree_contract}

Your final output must contain exactly one single-line result in this form:

{REVIEW_MARKER} {{"verdict":"approved|changes_requested","summary":"short summary"\
,"findings":["actionable finding"]}}

Use `approved` only when there are no blocking findings. Keep every finding
specific and actionable. The orchestrator treats a missing or malformed result
as a review failure.
"""


def render_revision_prompt(original_prompt: str, review: dict[str, object], cycle: int, *, worktree_contract: str) -> str:
    feedback = json.dumps(review, ensure_ascii=False, indent=2)
    return f"""{original_prompt}

## Review revision {cycle}

An independent reviewer requested changes:

{feedback}

Address every actionable finding, update focused tests, and run relevant checks.
Leave the worktree ready for another review.

## Orchestrator worktree contract

{worktree_contract}
"""


def parse_review(output: str) -> dict[str, object]:
    pattern = rf"^{re.escape(REVIEW_MARKER)}\s*(\{{.*\}})\s*$"
    matches = re.findall(pattern, output, flags=re.MULTILINE)
    if len(matches) != 1:
        raise ReviewProtocolError("review output must contain exactly one AI_REVIEW_RESULT line")
    try:
        raw = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise ReviewProtocolError(f"invalid review JSON: {exc}") from exc
    verdict = raw.get("verdict")
    summary = raw.get("summary")
    findings = raw.get("findings")
    if not isinstance(verdict, str) or verdict not in {"approved", "changes_requested"}:
        raise ReviewProtocolError(f"invalid review verdict: {verdict}")
    if not isinstance(summary, str) or not summary.strip():
        raise ReviewProtocolError("review summary must be a non-empty string")
    if not isinstance(findings, list) or not all(isinstance(item, str) and item.strip() for item in findings):
        raise ReviewProtocolError("review findings must be an array of strings")
    if verdict == "approved" and findings:
        raise ReviewProtocolError("approved review cannot contain blocking findings")
    if verdict == "changes_requested" and not findings:
        raise ReviewProtocolError("changes_requested review requires findings")
    return {
        "verdict": verdict,
        "summary": summary.strip(),
        "findings": [item.strip() for item in findings],
    }
