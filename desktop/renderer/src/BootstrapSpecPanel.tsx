import type { BootstrapSpec } from "./types";

const excludedActionLabels: Readonly<Record<string, string>> = {
  remote_repository_changes: "원격 저장소 생성·변경",
  deployment: "배포",
  global_tool_installation: "전역 도구 설치",
};

function List(props: { items: string[]; empty: string; code?: boolean }) {
  return props.items.length ? (
    <ul>{props.items.map((item, index) => <li key={`${item}-${index}`}>{props.code ? <code>{item}</code> : item}</li>)}</ul>
  ) : <p>{props.empty}</p>;
}

interface BootstrapSpecPanelProps {
  spec: BootstrapSpec;
  phase?: string;
  retrying?: boolean;
  savingInstructions?: boolean;
  onSetCreateInstructions?(create: boolean): void;
  onRetry?(): void;
}

export function BootstrapSpecPanel({
  spec,
  phase,
  retrying = false,
  savingInstructions = false,
  onSetCreateInstructions,
  onRetry,
}: BootstrapSpecPanelProps) {
  const featurePlanReady = phase === "feature_plan_ready";
  const instructions = spec.agent_instructions;
  return (
    <section className="bootstrap-spec" aria-labelledby="bootstrap-spec-title">
      <header className="bootstrap-spec__heading">
        <div>
          <span className="eyebrow">BOOTSTRAP PREVIEW · REVISION {spec.decision_revision}</span>
          <h3 id="bootstrap-spec-title">기본 구조 실행 전 확인</h3>
          <p>아래 범위만 만들거나 수정합니다. 실행 직전에 경로가 바뀌었으면 덮어쓰지 않고 중단합니다.</p>
        </div>
        <code title={spec.digest}>명세 {spec.digest.slice(0, 12)}</code>
      </header>
      <p className="bootstrap-spec__target">대상 폴더 · <code>{spec.target_root}</code></p>
      <div className="bootstrap-spec__grid">
        <section><strong>예상 변경 경로</strong><List items={spec.planned_paths} empty="지정된 경로 없음" code /></section>
        <section><strong>필요한 도구</strong><List items={spec.required_tools} empty="추가 도구 없음" /></section>
        <section><strong>작업 순서</strong><List items={spec.steps} empty="작업 설명을 따릅니다" /></section>
        <section><strong>검증 명령</strong><List items={spec.verify_commands.map((command) => command.join(" "))} empty="지정된 검증 명령 없음" code /></section>
      </div>
      <p className="bootstrap-spec__excluded">
        실행하지 않는 작업 · {spec.excluded_external_actions.map((action) => excludedActionLabels[action] || action).join(" · ")}
      </p>
      {instructions ? (
        <section className="bootstrap-spec__instructions" data-mode={instructions.mode}>
          <div>
            <strong>
              {instructions.mode === "create_from_template"
                ? `${instructions.path} · 새로 생성 · 권장`
                : instructions.mode === "preserve_existing"
                  ? `${instructions.path} · 기존 작업 지침 유지`
                  : `${instructions.path} · 생성 제외`}
            </strong>
            <span>
              {instructions.mode === "create_from_template"
                ? `제품 템플릿 v${instructions.template_version}으로 만들며 실행 전 변경 여부를 다시 확인합니다.`
                : instructions.mode === "preserve_existing"
                  ? "기존 내용을 병합하거나 덮어쓰지 않습니다."
                  : "저장소 작업 지침 없이 앱 공통 규칙만 사용합니다."}
            </span>
          </div>
          {instructions.mode === "create_from_template" ? (
            <details>
              <summary>생성할 전체 내용 보기</summary>
              <pre>{instructions.rendered_content}</pre>
            </details>
          ) : null}
          {instructions.mode !== "preserve_existing" && phase === "bootstrap_ready" && onSetCreateInstructions ? (
            <label className="bootstrap-spec__instructions-toggle">
              <input
                type="checkbox"
                checked={instructions.mode === "create_from_template"}
                disabled={savingInstructions}
                onChange={(event) => onSetCreateInstructions(event.target.checked)}
              />
              <span>
                <strong>{savingInstructions ? "선택 저장 중…" : "프로젝트 작업 지침 만들기"}</strong>
                <small>끄면 이번 초기화에서 AGENTS.md를 만들지 않으며 이후 Agent는 앱 공통 규칙만 사용합니다.</small>
              </span>
            </label>
          ) : null}
        </section>
      ) : null}
      {spec.verified_integration_head ? (
        <div className="bootstrap-spec__verification" data-error={Boolean(spec.feature_plan_error)}>
          <div>
            <strong>{featurePlanReady ? "기능 계획 생성 완료" : spec.feature_plan_error ? "기본 구조 검증 완료 · 기능 계획 재시도 필요" : "기본 구조 검증 완료"}</strong>
            <span>검증 commit · <code>{spec.verified_integration_head.slice(0, 12)}</code>{spec.feature_plan_attempts ? ` · 기능 계획 시도 ${spec.feature_plan_attempts}회` : ""}</span>
            {spec.feature_plan_error ? <small role="alert">{spec.feature_plan_error}</small> : null}
          </div>
          {spec.feature_plan_error && onRetry ? <button className="button button--secondary" type="button" disabled={retrying} onClick={onRetry}>{retrying ? "기능 계획 생성 중…" : "기능 계획 다시 생성"}</button> : null}
        </div>
      ) : null}
    </section>
  );
}
