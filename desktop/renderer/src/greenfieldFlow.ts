import type { PlanningApplyRequest, RunState, TechStackOption } from "./types";
import { activeTechStackDecision } from "./techStackDecision";

export function greenfieldStage(run: RunState): number {
  if (run.greenfield_phase === "feature_plan_ready") return 3;
  if (run.bootstrap_spec || activeTechStackDecision(run.tech_stack_decisions)?.status === "confirmed") return 2;
  if (run.stage === "reviewed" || !activeTechStackDecision(run.tech_stack_decisions)?.options.length) return 0;
  return 1;
}

export function greenfieldOption(run: RunState, selectedId = ""): TechStackOption | undefined {
  const decision = activeTechStackDecision(run.tech_stack_decisions);
  if (!decision) return undefined;
  const explicit = decision.status === "confirmed" ? decision.selected_option_id : selectedId;
  if (explicit) return decision.options.find((option) => option.option_id === explicit);
  const recommendations = decision.options.filter((option) => option.recommendation_rank === 1);
  return recommendations.length === 1 ? recommendations[0] : decision.options.length === 1 ? decision.options[0] : undefined;
}

export function greenfieldConsentOption(run: RunState, message: string, selectedId = ""): TechStackOption | undefined {
  if (run.repository_intent !== "new_project" || greenfieldStage(run) !== 1 || !run.tech_stack_confirmation_allowed) return undefined;
  if (!/^(?:ㅇㅇ\s*(?:진행(?:해(?:줘)?)?|진행하자)|(?:네|예|좋아|그래)[,\s]*(?:진행(?:해(?:주세요|줘)?)?|진행하자)|추천\s*구성으로\s*진행(?:해(?:주세요|줘)?)?)[.!~\s]*$/u.test(message.trim())) return undefined;
  return greenfieldOption(run, selectedId);
}

export function greenfieldRetry(run: RunState): PlanningApplyRequest | undefined {
  const last = run.planning_apply_requests?.[run.planning_apply_requests.length - 1];
  const revision = activeTechStackDecision(run.tech_stack_decisions)?.revision || 0;
  return last?.status === "failed" && last.tech_stack_revision === revision
    && last.plan_revision === run.plan_revision
    && last.answer_conversation_revision === run.planning_conversation_revision ? last : undefined;
}

export function greenfieldPlaceholder(run: RunState): string {
  if (run.planning_questions.length && !run.tech_stack_confirmation_allowed) return "필요한 답변은 위 카드에 입력해 주세요. 추가 조건은 여기서 논의할 수 있습니다.";
  return greenfieldStage(run) === 1 ? "추천 구성을 바꾸고 싶으면 말씀해 주세요. 동의하면 ‘ㅇㅇ 진행해’라고 입력하세요."
    : greenfieldStage(run) === 2 ? "기본 구조의 범위나 필요한 도구에 관해 이야기하세요."
      : greenfieldStage(run) === 3 ? "기능 계획에서 바꿀 내용을 말씀해 주세요." : "만들 프로그램과 사용할 환경을 알려주세요.";
}
