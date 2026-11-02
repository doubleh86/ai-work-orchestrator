import { Bot } from "lucide-react";
import { usageAmount } from "./UsagePanel";
import type { TaskUsageSummary, UsageSummary } from "./types";

const purposeLabels: Record<string, string> = { planning: "계획", chat: "대화", execute: "구현", review: "리뷰", revise: "수정",
  verification_repair: "검증 수정", recovery_planning: "복구 계획", result_revision: "결과 수정", conflict_resolution: "충돌 해결" };
const providerLabels: Record<string, string> = { codex: "Codex", claude: "Claude", nvidia: "NVIDIA · 시험" };

export function aiModelLabel(requested: string, effective: string, planned: boolean): string {
  if (effective) return `${effective} · 실행 기록`;
  return planned ? `${requested || "자동 선택"} · 예정` : `실행 모델 미확인${requested ? ` · 설정 ${requested}` : ""}`;
}

export function aiProfileSummary(requested: string, effective: string, requestedReasoning: string, effectiveReasoning: string, planned: boolean): string {
  const model = effective || requested || "자동 선택";
  const reasoning = effectiveReasoning || (requestedReasoning ? `${requestedReasoning}${planned ? "" : " 설정"}` : planned ? "추론 자동" : "추론 미확인");
  return [model, reasoning, !effective ? planned ? "예정" : "모델 미확인" : requestedReasoning && !effectiveReasoning ? "추론 미확인" : ""].filter(Boolean).join(" · ");
}

export function aiUsageSummary(usage: UsageSummary): string {
  if (!usage.call_count) return "호출 없음";
  if (usage.total_tokens === null) return usage.reported_call_count ? "일부 보고 · 총량 미확인" : usage.running_call_count ? "토큰 수신 대기" : "토큰 미보고";
  return `${usage.total_tokens.toLocaleString("ko-KR")}토큰${usage.coverage === "complete" ? "" : " · 일부 집계"}`;
}

export function AiBadge({ provider, requestedModel = "", effectiveModel = "", requestedReasoning = "", effectiveReasoning = "", planned = false, compact = false, automatic = false,
  usage, usageKnown = false, usageError = "", purposes = [], taskUsage, title = "담당 AI" }: {
  provider: string; requestedModel?: string; effectiveModel?: string; requestedReasoning?: string; effectiveReasoning?: string;
  planned?: boolean; compact?: boolean; automatic?: boolean; usage?: UsageSummary; usageKnown?: boolean; usageError?: string;
  purposes?: (UsageSummary & { key: string })[]; taskUsage?: TaskUsageSummary; title?: string;
}) {
  const name = providerLabels[provider] || provider || "AI 미정";
  const amount = usage ? usageAmount(usage) : purposes.length ? "기획·대화 사용량 상세" : usageKnown ? "기록된 AI 호출 없음" : "사용량 확인 전·집계 미제공";
  const shortAmount = usage ? aiUsageSummary(usage) : purposes.length ? "토큰 상세" : usageKnown ? "호출 없음" : "토큰 미확인";
  const summaryContent = <><Bot size={18} aria-hidden="true" /><span><strong>{name}</strong>
    <span>{automatic ? "자동 · " : ""}{aiProfileSummary(requestedModel, effectiveModel, requestedReasoning, effectiveReasoning, planned)}</span>
    <small>{usageError ? "토큰 조회 실패" : shortAmount}</small></span></>;
  if (compact) return <div className="ai-badge ai-badge--compact" role="group" aria-label={`${title} · ${name}`}>
    <div className="ai-badge__summary">{summaryContent}</div>
  </div>;
  return <details className="ai-badge" aria-label={`${title} · ${name}`}>
    <summary>{summaryContent}</summary>
    <div className="ai-badge__details">
      <p>모델 · {aiModelLabel(requestedModel, effectiveModel, planned)}</p>
      <p>토큰 · {amount}</p>
      <p>추론 · {effectiveReasoning ? `${effectiveReasoning} · 실행 기록` : requestedReasoning ? `${requestedReasoning} · 설정 (실행 확인 전)` : planned ? "자동 선택 예정" : "실행 추론 기록 미보고"}</p>
      {usage?.latest_observed_at ? <p>최근 보고 · <time dateTime={usage.latest_observed_at}>{new Date(usage.latest_observed_at).toLocaleString("ko-KR")}</time></p> : null}
      {usageError ? <p role="alert">조회 실패 · 이전 기록 보존. {usageError}</p> : null}
      {purposes.map((group) => <p key={group.key}>{purposeLabels[group.key] || group.key} · {usageAmount(group)}</p>)}
      {taskUsage?.attempts.map((attempt) => <section key={attempt.attempt_id}><strong>{attempt.attempt_id ? `실행 시도 ${attempt.attempt_id.slice(0, 8)}` : "시도 ID 없는 이전 기록"}</strong>
        <p>{usageAmount(attempt)}</p>
        {attempt.profiles.map((profile, index) => <p key={index}>{profile.provider} · {aiModelLabel(profile.model_requested, profile.model_effective, false)} · 추론 기록 별도 확인</p>)}
        {attempt.by_purpose.map((group) => <p key={group.key}>{purposeLabels[group.key] || group.key} · {usageAmount(group)}</p>)}
      </section>)}
      <p>기록된 호출의 공급자 보고량입니다. 요금·계정 한도 또는 현재 실행 여부를 뜻하지 않습니다.</p>
    </div>
  </details>;
}
