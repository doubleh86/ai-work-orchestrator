
from ai_orchestrator.execution.task_workflows import TaskWorkflows
import json

import pytest

from ai_orchestrator.execution import REVIEW_MARKER, ReviewProtocolError, ReviewRequest, parse_review, render_review_prompt, render_revision_prompt
from ai_orchestrator.pipeline import Pipeline, PipelineError


@pytest.mark.parametrize(("verdict", "findings"), [("approved", []), ("changes_requested", ["  오류 수정  "])])
def test_review_result_preserves_dictionary_contract_and_normalizes_feedback(verdict, findings):
    payload = {"verdict": verdict, "summary": "  검토 완료  ", "findings": findings, "additional": "ignored"}
    output = "review progress\n" + REVIEW_MARKER + " " + json.dumps(payload, ensure_ascii=False) + "\n"
    expected = {"verdict": verdict, "summary": "검토 완료", "findings": [item.strip() for item in findings]}
    assert parse_review(output) == expected and TaskWorkflows.parse_review(output) == expected


@pytest.mark.parametrize(("body", "message"), [
    ("no review result", "exactly one"),
    (f'{REVIEW_MARKER} {{}}\n{REVIEW_MARKER} {{}}', "exactly one"),
    (f'{REVIEW_MARKER} {{"verdict": }}', "invalid review JSON"),
    ({"verdict": [], "summary": "ok", "findings": []}, "invalid review verdict"),
    ({"verdict": {}, "summary": "ok", "findings": []}, "invalid review verdict"),
    ({"verdict": "unknown", "summary": "ok", "findings": []}, "invalid review verdict"),
    ({"verdict": "approved", "summary": "  ", "findings": []}, "non-empty string"),
    ({"verdict": "approved", "summary": "ok", "findings": "issue"}, "array of strings"),
    ({"verdict": "changes_requested", "summary": "ok", "findings": [" "]}, "array of strings"),
    ({"verdict": "approved", "summary": "ok", "findings": ["blocking issue"]}, "cannot contain blocking findings"),
    ({"verdict": "changes_requested", "summary": "ok", "findings": []}, "requires findings"),
])
def test_invalid_review_is_a_protocol_error_and_facade_preserves_message_and_json_cause(body, message):
    output = body if isinstance(body, str) else f"{REVIEW_MARKER} {json.dumps(body)}"
    with pytest.raises(ReviewProtocolError, match=message) as direct:
        parse_review(output)
    with pytest.raises(PipelineError, match=message) as adapted:
        TaskWorkflows.parse_review(output)
    assert type(adapted.value) is PipelineError and str(adapted.value) == str(direct.value)
    if message == "invalid review JSON":
        assert isinstance(direct.value.__cause__, json.JSONDecodeError)
        assert isinstance(adapted.value.__cause__, json.JSONDecodeError)
        assert str(adapted.value.__cause__) == str(direct.value.__cause__)
    else:
        assert adapted.value.__cause__ is None


@pytest.mark.parametrize("manual", [False, True])
def test_standalone_review_request_and_revision_preserve_scope_style_and_feedback(manual):
    request = ReviewRequest(
        run_id="run", task_id="task", cycle=2, title="로그인 수정", capabilities=("general",), risk_level="high",
        expected_paths=("src/login.py",), forbidden_paths=("data/",), verify_commands=(("python", "-m", "pytest", "tests/login"),),
        acceptance_criteria=("로그인이 성공한다",), main_branch="main", code_style_snapshot="fixed style",
        changed_path_evidence="changed style", worktree_contract="keep isolated worktree", manual_verification=manual,
    )
    prompt = render_review_prompt(request)
    assert "src/login.py" in prompt and "data/" in prompt and "로그인이 성공한다" in prompt
    assert "fixed style" in prompt and "changed style" in prompt and "keep isolated worktree" in prompt
    assert ("The operator is recording a manual check" in prompt) == manual
    assert ("Review the committed diff from `main`" in prompt) == (not manual)
    feedback = {"verdict": "changes_requested", "summary": "수정 필요", "findings": ["오류를 수정하세요"]}
    revision = render_revision_prompt("approved task prompt", feedback, 2, worktree_contract=request.worktree_contract)
    assert revision.startswith("approved task prompt") and "Review revision 2" in revision
    assert "오류를 수정하세요" in revision and "keep isolated worktree" in revision
