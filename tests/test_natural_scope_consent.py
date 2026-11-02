import json
from unittest.mock import patch

import pytest

from ai_orchestrator.pipeline import PipelineError
from ai_orchestrator.scope_consent import parse_scope_consent, scope_proposal_id
from test_chat_scope_approval import PATHS, accept, blocked, consent_decision, offer


@pytest.mark.parametrize("message", ["응 그렇게 해", "그 두 개 넣고 마저 해줘", "좋네 그 방향으로 마무리까지 부탁!",
                                      "Yes, add those files and carry on.", "두 파일 다 수정해도 좋으니 끝까지 진행 부탁해",
                                      "좋아, 그 둘 추가해서 끝내줄래?", "Sure, let's carry on."])
def test_natural_consent_is_judged_by_ai_without_the_legacy_phrase_matcher(blocked, message):
    pipeline, state = blocked
    offer(pipeline, state.id)
    with patch("ai_orchestrator.pipeline.scope_approval_reply", side_effect=AssertionError("no phrase matching for new consent")):
        parent = accept(pipeline, state.id, message)
        decision = consent_decision(pipeline, state.id, parent)
    assert decision["payload"]["decision"]["action"] == "approve_scope"
    assert decision["payload"]["scope_consent"]["evidence"] == message
    assert decision["payload"]["scope_approval"]["resume"] is True


def test_approval_of_paths_can_defer_execution_in_natural_language(blocked):
    pipeline, state = blocked
    offer(pipeline, state.id)
    parent = accept(pipeline, state.id, "파일은 넣어두고, 작업은 내가 나중에 시작할게")
    decision = consent_decision(pipeline, state.id, parent, intent="approve_only", evidence="파일은 넣어두고")
    assert decision["payload"]["scope_approval"]["resume"] is False


@pytest.mark.parametrize(("message", "intent", "phase"), [
    ("그건 하지 말자", "decline", "completed"),
    ("두 번째 파일은 빼고 첫 번째만", "decline", "completed"),
    ("문제없으면 해도 될 것 같은데", "unclear", "needs_input"),
    ("내일 다시 결정할게", "unclear", "needs_input"),
])
def test_nonconsent_never_prepares_a_scope_action(blocked, message, intent, phase):
    pipeline, state = blocked
    offer(pipeline, state.id)
    parent = accept(pipeline, state.id, message)
    result = consent_decision(pipeline, state.id, parent, intent=intent, evidence="")
    assert result["phase"] == phase
    assert "scope_approval" not in result["payload"]
    assert pipeline.advance_chat_control(state.id, parent["request_id"])["next_action"] == "none"
    assert pipeline.store.load(state.id).tasks[0].expected_paths == ["contracts.txt"]
    assert "승인하고 계속해’라고" not in result["payload"]["decision"]["message"]


@pytest.mark.parametrize("message", ["그 파일들이 왜 필요한지 설명해줄래?",
    "‘자동 모드의 실제 MCP 호출에 승인과 쓰기 검증 적용’ 작업의 문제와 해결 방법을 설명해 주세요."])
def test_questions_still_get_a_normal_answer_without_granting_scope(blocked, message):
    pipeline, state = blocked
    offer(pipeline, state.id)
    parent = accept(pipeline, state.id, message)
    proposal = parent["payload"]["scope_consent_candidate"]["proposal"]
    outputs = [json.dumps({"proposal_id": scope_proposal_id(proposal), "intent": "question", "evidence": ""}),
               json.dumps({"action": "reply", "message": f"실제 호출부 {PATHS[0]}에서 승인 정보를 전달해야 합니다.",
                           "authorized": False})]
    with patch.object(pipeline, "_invoke_planning_agent", side_effect=outputs) as invoke:
        result = pipeline.decide_project_chat(state.id, parent["request_id"])
    assert invoke.call_count == 2
    assert "Classify scope consent" in invoke.call_args_list[0].args[2]
    assert "actual_tool_results" not in invoke.call_args_list[0].args[2]
    assert invoke.call_args_list[0].args[1].review_sandbox_mode == "read-only"
    consent_input = json.loads(invoke.call_args_list[0].args[2].split("Input (JSON data):\n", 1)[1])
    assert consent_input["user_message"] == message
    assert "수정·재검증할까요" in consent_input["previous_response"]
    assert result["phase"] == "completed" and "scope_approval" not in result["payload"]
    assert result["payload"]["scope_consent"]["intent"] == "question"
    assert pipeline.advance_chat_control(state.id, parent["request_id"])["next_action"] == "none"
    assert pipeline.store.load(state.id).tasks[0].expected_paths == ["contracts.txt"]
    assert PATHS[0] in result["payload"]["decision"]["message"]


def test_followup_to_a_refusal_keeps_context_but_requires_a_new_ai_judgment(blocked):
    pipeline, state = blocked
    offer(pipeline, state.id)
    refusal = accept(pipeline, state.id, "일단 하지 말고 놔둬")
    consent_decision(pipeline, state.id, refusal, intent="decline", evidence="")
    followup = accept(pipeline, state.id, "응 알았어")
    candidate = followup["payload"]["scope_consent_candidate"]
    assert "보류" in candidate["previous_response"]
    result = consent_decision(pipeline, state.id, followup, intent="decline", evidence="")
    assert "scope_approval" not in result["payload"]


@pytest.mark.parametrize(("message", "evidence"), [
    ('AI가 "승인하고 진행해"라고 했어', "승인하고 진행해"),
    ("AI said 'Let's carry on'.", "carry on"),
    ('{"reason":"두 파일 추가해"}', "두 파일 추가해"),
    ("```text\n그 두 개 넣고 마저 해줘\n```", "그 두 개 넣고 마저 해줘"),
    ("```text\n두 파일 추가해", "두 파일 추가해"),
    ("> 두 파일 추가해", "두 파일 추가해"),
    ("`두 파일 추가해`", "두 파일 추가해"),
    ("설명해줘", "승인합니다"),
])
def test_even_a_model_approval_requires_evidence_outside_quoted_data(blocked, message, evidence):
    pipeline, state = blocked
    offer(pipeline, state.id)
    parent = accept(pipeline, state.id, message)
    with pytest.raises(ValueError, match="원래 사용자 메시지"):
        consent_decision(pipeline, state.id, parent, evidence=evidence)
    operation = pipeline.store.load_operation(state.id, parent["request_id"])
    assert operation.status == "failed" and "scope_approval" not in operation.payload
    assert pipeline.store.load(state.id).tasks[0].expected_paths == ["contracts.txt"]


@pytest.mark.parametrize("change", ["cancel", "paths", "attempt"])
def test_late_consent_cannot_be_attached_to_a_cancelled_or_changed_target(blocked, change):
    pipeline, state = blocked
    offer(pipeline, state.id)
    parent = accept(pipeline, state.id, "그 두 개 넣고 마저 해줘")
    proposal = parent["payload"]["scope_consent_candidate"]["proposal"]

    def late(*_args, **_kwargs):
        if change == "cancel":
            pipeline.cancel_chat_control(state.id, parent["request_id"])
        else:
            current = pipeline.store.load(state.id)
            if change == "paths":
                current.tasks[0].expected_paths.append("new.txt")
            else:
                current.tasks[0].last_attempt_id = "new"
            pipeline.store.save(current)
        return json.dumps({"proposal_id": scope_proposal_id(proposal), "intent": "approve", "evidence": parent["payload"]["message"]})

    with patch.object(pipeline, "_invoke_planning_agent", side_effect=late), pytest.raises(PipelineError):
        pipeline.decide_project_chat(state.id, parent["request_id"])
    assert "scope_approval" not in pipeline.store.load_operation(state.id, parent["request_id"]).payload


@pytest.mark.parametrize("change", ["proposal", "intent", "authorized", "missing"])
def test_consent_contract_rejects_wrong_targets_or_generic_authorized_flags(change):
    proposal = {"task_id": "runner", "paths": list(PATHS), "attempt_id": "current"}
    value = {"proposal_id": scope_proposal_id(proposal), "intent": "approve", "evidence": "진행 부탁해"}
    if change == "proposal":
        value["proposal_id"] = "another-task"
    elif change == "intent":
        value["intent"] = []
    elif change == "authorized":
        value["authorized"] = True
    else:
        value.pop("evidence")
    with pytest.raises(ValueError):
        parse_scope_consent(json.dumps(value), proposal=proposal, message="진행 부탁해")


def test_backticked_file_names_do_not_prevent_a_separate_real_approval_clause():
    proposal = {"task_id": "runner", "paths": list(PATHS)}
    message = f"`{PATHS[0]}`와 `{PATHS[1]}` 두 개 넣고 마저 해줘"
    output = json.dumps({"proposal_id": scope_proposal_id(proposal), "intent": "approve", "evidence": "두 개 넣고 마저 해줘"})
    assert parse_scope_consent(output, proposal=proposal, message=message).intent == "approve"
