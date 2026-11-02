import { useEffect, useId, useRef, useState } from "react";
import type { UsageRecord, UsageSnapshot, UsageSummary } from "./types";

const modeLabels: Record<string, string> = { economy: "절약", balanced: "균형", focused: "집중", legacy: "모드 기록 없음" };
const purposeLabels: Record<string, string> = {
  planning: "계획 생성", chat: "기획 대화", execute: "작업 실행", review: "리뷰", revise: "리뷰 수정",
  recovery_planning: "복구 재계획", conflict_resolution: "충돌 해결", verification_repair: "검증 수정", result_revision: "결과 수정 제안",
};
const outcomeLabels: Record<UsageRecord["outcome"], string> = {
  running: "실행 결과 대기", completed: "응답 완료", failed: "실패", cancelled: "중지", interrupted: "시간 초과·중단",
};
const missingLabels: Record<string, string> = {
  usage_pending: "사용량 수신 대기", provider_not_reported: "공급자가 사용량을 제공하지 않았습니다",
  baseline_missing: "이전 누적 사용량을 확인할 수 없습니다", intervening_turn: "다른 호출이 섞여 사용량을 구분할 수 없습니다",
  invalid_cumulative_total: "누적 사용량이 초기화되었거나 유효하지 않습니다", provider_total_mismatch: "공급자 보고량이 일치하지 않습니다",
};

export function usageAmount(summary: UsageSummary): string {
  if (!summary.call_count) return "기록된 AI 호출이 없습니다";
  if (summary.total_tokens === null) {
    if (summary.reported_call_count) return "일부 사용량 보고 · 총량 미제공";
    return summary.running_call_count ? "사용량 수신 대기" : "사용량 미제공";
  }
  const tokens = `${summary.total_tokens.toLocaleString("ko-KR")}토큰`;
  return summary.coverage === "complete" ? `${tokens} · 집계 완료` : `현재 보고량 ${tokens} · 일부 미집계`;
}

function tokenCount(value: number | null): string {
  return value === null ? "미제공" : value.toLocaleString("ko-KR");
}

export function mergeUsageSnapshot(current: UsageSnapshot | undefined, result: UsageSnapshot, append: boolean, preservePages: boolean): UsageSnapshot {
  if (!current || (!append && !preservePages)) return result;
  const refreshedIds = new Set(result.records.map((row) => row.invocation_id));
  return { ...result,
    records: append ? [...current.records, ...result.records]
      : [...result.records, ...current.records.filter((row) => !refreshedIds.has(row.invocation_id))],
    next_cursor: preservePages && current.records.length > result.records.length ? current.next_cursor : result.next_cursor,
  };
}

function Summary({ title, value }: { title: string; value: UsageSummary }) {
  return <div className="usage-panel__summary">
    <strong>{title}</strong><span>{usageAmount(value)}</span>
    <small>전체 호출 {value.call_count} · 사용량 보고 {value.reported_call_count} · 집계 완료 {value.complete_call_count}</small>
    {value.call_count > 0 ? <small>입력 {tokenCount(value.input_tokens)} · 출력 {tokenCount(value.output_tokens)}</small> : null}
  </div>;
}

export function UsagePanel({ projectName, runId, running, refreshKey, onSnapshot, onError }: {
  projectName: string; runId: string; running: boolean; refreshKey: string;
  onSnapshot?(snapshot: UsageSnapshot): void; onError?(error: string): void;
}) {
  const [snapshot, setSnapshot] = useState<UsageSnapshot>();
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const pending = useRef(false);
  const scope = `${projectName}\0${runId}\0${filter}`;
  const latestScope = useRef(scope);
  latestScope.current = scope;
  const fieldId = useId();

  async function load(cursor = "", append = false, preservePages = false) {
    if (pending.current) return;
    const token = ++generation.current;
    pending.current = true; setBusy(true); setError("");
    try {
      const result = await window.orchestrator.request<UsageSnapshot>("runs.usage", {
        projectName, runId, executionRequestId: filter, cursor, limit: 50,
      });
      if (token === generation.current && latestScope.current === scope) {
        setSnapshot((current) => mergeUsageSnapshot(current, result, append, preservePages));
        onSnapshot?.(result);
      }
    } catch (cause) {
      if (token === generation.current && latestScope.current === scope) { setError(String(cause)); onError?.(String(cause)); }
    } finally {
      if (token === generation.current && latestScope.current === scope) { pending.current = false; setBusy(false); }
    }
  }

  useEffect(() => {
    generation.current += 1; pending.current = false; setSnapshot(undefined); setError("");
    void load();
    return () => { generation.current += 1; pending.current = false; };
  }, [projectName, runId, filter]);

  useEffect(() => {
    void load("", false, true);
    if (!running) return;
    const timer = window.setInterval(() => void load("", false, true), 5000);
    return () => window.clearInterval(timer);
  }, [running, refreshKey, projectName, runId, filter]);

  return <section className="usage-panel" aria-label="AI 사용량">
    <div className="usage-panel__heading">
      <strong>AI 사용량</strong>
      <button type="button" className="button button--quiet" aria-expanded={open} aria-controls={`${fieldId}-details`}
        onClick={() => setOpen((current) => !current)}>{open ? "사용량 상세 접기" : "사용량 상세"}</button>
      <button type="button" className="button button--quiet" disabled={busy} onClick={() => void load()}>{busy ? "사용량 조회 중…" : "사용량 새로 확인"}</button>
    </div>
    {error ? <p role="alert">사용량을 확인하지 못했습니다. {error}</p> : null}
    {snapshot ? <>
      <Summary title="그룹 전체 기록" value={snapshot.summary} />
      <p className="usage-panel__scope">{snapshot.recording_started_at
        ? `${new Date(snapshot.recording_started_at).toLocaleString("ko-KR")} 이후 기록된 호출만 집계합니다.`
        : "이 그룹에는 사용량 기록이 없습니다. 이전 로그의 사용량은 자동으로 합산하지 않습니다."}</p>
      {snapshot.summary.latest_observed_at ? <p className="usage-panel__scope">
        최근 사용량 보고 {new Date(snapshot.summary.latest_observed_at).toLocaleString("ko-KR")}
      </p> : null}
      <div id={`${fieldId}-details`} hidden={!open}>
        <p>요금이나 계정 사용 한도가 아닌 공급자 보고량입니다. 사용량 갱신으로 작업 진행 여부를 판단하지 않습니다.</p>
        <label htmlFor={fieldId}>호출 상세 범위</label>
        <select id={fieldId} value={filter} disabled={busy} onChange={(event) => setFilter(event.target.value)}>
          <option value="">그룹 전체</option>
          {snapshot.execution_requests.map((id, index) => <option key={id} value={id}>실행 {snapshot.execution_requests.length - index} · {id.slice(0, 8)}</option>)}
        </select>
        {snapshot.execution_request_id ? <Summary title={filter ? "선택한 실행 기록" : snapshot.execution_is_active ? "이번 실행 기록" : "최근 실행 기록"}
          value={snapshot.execution_summary} /> : null}
        {snapshot.by_mode.length ? <div className="usage-panel__groups" aria-label="모드별 사용량">
          {snapshot.by_mode.map((group) => <Summary key={group.key} title={modeLabels[group.key] || group.key} value={group} />)}
        </div> : null}
        {snapshot.by_purpose.length ? <div className="usage-panel__groups" aria-label="목적별 사용량">
          {snapshot.by_purpose.map((group) => <Summary key={group.key} title={purposeLabels[group.key] || group.key} value={group} />)}
        </div> : null}
        <p>미제공 호출은 0으로 계산하지 않습니다. 캐시·추론 토큰은 입력·출력과 별도로 보고하며 총량에 더하지 않습니다.</p>
        <ol className="usage-panel__records">
          {snapshot.records.map((row) => <li key={row.invocation_id}>
            <strong>{purposeLabels[row.purpose] || row.purpose}{row.task_id ? ` · ${row.task_id}` : ""}</strong>
            <span>{outcomeLabels[row.outcome]} · {row.total_tokens === null ? "사용량 미제공" : `${tokenCount(row.total_tokens)}토큰`}
              {row.coverage === "partial" ? " · 일부 미집계" : ""}</span>
            <small>{row.provider} · 요청 {row.model_requested || "자동"} · 실제 {row.model_effective || "확인되지 않음"}
              {` · ${modeLabels[row.mode || "legacy"]}`}</small>
            <small>입력 {tokenCount(row.input_tokens)} · 출력 {tokenCount(row.output_tokens)} · 캐시 입력 {tokenCount(row.cached_input_tokens)}
              {` · 캐시 쓰기 ${tokenCount(row.cache_write_input_tokens)} · 추론 출력 ${tokenCount(row.reasoning_output_tokens)}`}</small>
            {row.missing_reason ? <small>{missingLabels[row.missing_reason] || row.missing_reason}</small> : null}
            <small>호출 {row.invocation_id} · {new Date(row.created_at).toLocaleString("ko-KR")}</small>
          </li>)}
        </ol>
        {snapshot.next_cursor ? <button type="button" className="button button--quiet" disabled={busy}
          onClick={() => void load(snapshot.next_cursor, true)}>이전 호출 더 보기</button> : null}
      </div>
    </> : <p role="status">{busy ? "사용량 조회 중…" : "사용량을 확인해 주세요."}</p>}
  </section>;
}
