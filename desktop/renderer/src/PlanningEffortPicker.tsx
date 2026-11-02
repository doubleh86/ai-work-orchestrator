import { useId } from "react";
import { effortModeLabels } from "./EffortModePanel";
import type { EffortControl, EffortMode } from "./types";

export function PlanningEffortPicker(props: { mode: EffortMode; manual: boolean; disabled: boolean; onChange(mode: EffortMode): void }) {
  const name = useId();
  return <fieldset className="planning-effort-picker" disabled={props.disabled}>
    <legend>작업 강도</legend>
    <div>{(["economy", "balanced", "focused"] as const).map((mode) => <label key={mode}>
      <input type="radio" name={name} value={mode} checked={props.mode === mode} onChange={() => props.onChange(mode)} />
      <span>{effortModeLabels[mode]}</span>
    </label>)}</div>
    <p>자동 선택에서는 기획은 6.1 Sol을 유지하고, 절약 모드의 명확한 작은 작업에 6 Luna를 사용합니다. 필수 검증은 유지합니다.</p>
    <small>{props.manual ? "직접 선택한 기획 모델·추론 설정은 유지합니다." : "기획 AI의 권장 추론 강도를 적용합니다. AI 설정에서 직접 변경할 수 있습니다."}</small>
  </fieldset>;
}

export function PlanningPolicySummary({ control }: { control: EffortControl | undefined }) {
  const policy = control?.planning_policy;
  if (!policy) return null;
  const profile = policy.planning_profile;
  const statuses: Record<string, string> = { prepared: "준비", started: "완료 확인 전", finished: "완료", failed: "실패" };
  return <div className="planning-policy-summary" aria-label="최근 기획 요청 정책">
    <strong>최근 기획 정책 · {effortModeLabels[policy.mode]}</strong>
    <span>{profile ? `${profile.profile_source === "mode" ? "자동 · " : ""}${profile.model} · ${profile.reasoning_effort || "자동 추론"}` : "기획 프로필 없음"}</span>
    <span>{statuses[control?.planning_request_status || ""] || "상태 확인 필요"}
      {control?.planning_request_started_at ? " · AI 호출 시작 기록 있음" : " · AI 호출 기록 없음"}</span>
    <small>Task 실행 설정과 다음 실행 예약은 별도로 유지됩니다.</small>
  </div>;
}
