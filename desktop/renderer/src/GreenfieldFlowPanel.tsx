import type { ReactNode } from "react";
import type { RunState } from "./types";
import { activeTechStackDecision, techStackCoreItems } from "./techStackDecision";
import { greenfieldOption, greenfieldRetry, greenfieldStage } from "./greenfieldFlow";

interface GreenfieldFlowPanelProps {
  run: RunState;
  selectedOptionId: string;
  answer: string;
  busy: boolean;
  available: boolean;
  active: boolean;
  elapsed: number;
  bootstrapDetails?: ReactNode;
  onAnswerChange(value: string): void;
  onSelect(optionId: string): void;
  onAnswer(answer: string): void;
  onConfirm(optionId: string, revision: number): void;
  onRetry(): void;
  onStart(): void;
  onFeaturePlan(): void;
  onInterrupt(): void;
  interruptible: boolean;
}

export function GreenfieldFlowPanel(props: GreenfieldFlowPanelProps) {
  const { run } = props;
  const stage = greenfieldStage(run);
  const decision = activeTechStackDecision(run.tech_stack_decisions);
  const option = greenfieldOption(run, props.selectedOptionId);
  const questions = run.planning_questions.length > 0 && !run.tech_stack_confirmation_allowed && decision?.status !== "confirmed";
  const retry = greenfieldRetry(run);
  const disabled = props.busy || props.active || !props.available;
  const bootstrap = run.bootstrap_spec;
  const features = run.tasks.filter((task) => task.id !== "project-bootstrap");
  const operationLabel = stage === 3 ? "기능 구현 중" : run.stage === "reviewed" ? "기획서와 제품 목표 확인 중" : decision?.status === "confirmed"
    ? bootstrap ? run.greenfield_phase === "feature_planning" ? "기능 계획 작성 중" : "기본 구조 생성·검증 중"
      : "기본 구조 계획 작성 중"
    : "추천 구성 작성 중";
  return (
    <section className="greenfield-flow" aria-labelledby="tech-stack-decision-title" aria-busy={props.active}>
      <ol className="greenfield-flow__steps" aria-label="새 프로젝트 진행 단계">
        {["기획서 확인", "기술 구성", "기본 구조", "기능 계획"].map((label, index) => <li key={label} aria-current={index === stage ? "step" : undefined} data-complete={index < stage}>{label}</li>)}
      </ol>
      <header>
        <span className="eyebrow">{stage + 1} / 4</span>
        <h3 id="tech-stack-decision-title">{questions ? "추천에 필요한 내용을 알려주세요" : ["무엇을 만들지 확인해요", "이 구성으로 시작해 볼까요?", "프로젝트의 기본 구조를 준비해요", "기능 계획을 확인해 주세요"][stage]}</h3>
        {decision?.requirement_sources.length || run.spec_path ? <details><summary>기획 근거 확인</summary>{decision?.requirement_sources.length ? <ul>{decision.requirement_sources.map((source) => <li key={source}>{source}</li>)}</ul> : <p>{run.spec_path}</p>}</details> : null}
      </header>
      {props.active ? <div className="greenfield-flow__progress" role="status"><strong>{operationLabel}</strong><span>{props.elapsed}초 경과</span>{props.interruptible ? <button className="button button--secondary" type="button" onClick={props.onInterrupt}>기획 중지</button> : null}</div> : null}
      {questions ? <div className="greenfield-flow__questions">
        <ol>{run.planning_questions.map((question, index) => <li key={index}>{question}</li>)}</ol>
        <label htmlFor="greenfield-answer">답변</label>
        <textarea id="greenfield-answer" rows={3} value={props.answer} onChange={(event) => props.onAnswerChange(event.target.value)} disabled={props.busy || props.active} placeholder="만들 프로그램과 질문에 대한 답변을 알려주세요." />
        <button className="button button--primary" type="button" disabled={disabled || !props.answer.trim()} onClick={() => { if (!disabled && props.answer.trim()) props.onAnswer(props.answer); }}>답변하고 추천 받기</button>
      </div> : stage === 1 && decision ? <>
        {option ? <article className="greenfield-flow__recommendation">
          <span className="eyebrow">{option.recommendation_rank === 1 ? "추천 구성" : "검토 중인 구성"}</span>
          <h4>{option.label}</h4>
          <p>{option.requirement_fit[0]}</p>
          <p><strong>핵심 구성</strong> · {techStackCoreItems(option).join(" · ")}</p>
          {[...option.tradeoffs, ...option.unresolved_constraints].length ? <p><strong>확인할 점</strong> · {[...option.tradeoffs, ...option.unresolved_constraints].slice(0, 2).join(" · ")}</p> : null}
          <details><summary>구성 상세</summary><ul>{option.requirement_fit.map((reason) => <li key={reason}>{reason}</li>)}</ul><p>확인할 점 · {[...option.tradeoffs, ...option.unresolved_constraints].join(" · ") || "추가 기록 없음"}</p></details>
          <button className="button button--primary" type="button" disabled={disabled || !run.tech_stack_confirmation_allowed} onClick={() => { if (!disabled && run.tech_stack_confirmation_allowed) props.onConfirm(option.option_id, decision.revision); }}>{option.recommendation_rank === 1 ? "추천 구성으로 진행" : "이 구성으로 진행"}</button>
        </article> : <p role="status">비교할 구성을 아래에서 골라 주세요.</p>}
        {decision.options.some((alternative) => alternative.option_id !== option?.option_id) ? <details className="greenfield-flow__alternatives"><summary>다른 구성 보기</summary>{decision.options.filter((alternative) => alternative.option_id !== option?.option_id).sort((left, right) => left.recommendation_rank - right.recommendation_rank).map((alternative) => <article key={alternative.option_id}><h4>{alternative.label}</h4><p>{alternative.requirement_fit.slice(0, 2).join(" · ")}</p><p>{alternative.tradeoffs.slice(0, 2).join(" · ")}</p><button className="button button--secondary" type="button" disabled={disabled} onClick={() => props.onSelect(alternative.option_id)}>이 구성 검토</button></article>)}</details> : null}
      </> : stage === 2 ? <>
        {option ? <p>확정한 구성 · <strong>{option.label}</strong></p> : null}
        {bootstrap ? <>
          <p>{bootstrap.verified_integration_head ? "기본 구조 검증이 완료됐습니다. 기능 계획을 이어서 준비합니다." : `${bootstrap.planned_paths.length}개 경로에 기본 구조를 만들고 빌드·테스트로 확인합니다.`}</p>
          <details><summary>생성 범위·검증·작업 지침 확인</summary><p>필요한 도구 · {bootstrap.required_tools.join(" · ") || "추가 도구 없음"}</p>{props.bootstrapDetails}</details>
          {run.stage === "planned" && run.greenfield_phase === "bootstrap_ready" ? <button className="button button--primary" type="button" disabled={disabled} onClick={props.onStart}>기본 구조 만들기</button> : null}
          {bootstrap.feature_plan_error ? <button className="button button--primary" type="button" disabled={disabled} onClick={props.onFeaturePlan}>기능 계획 다시 만들기</button> : null}
          {run.stage === "failed" && !bootstrap.feature_plan_error ? <p role="alert">기본 구조를 완료하지 못했습니다. 작업 화면에서 변경과 실패 원인을 확인하고 이어서 진행해 주세요.</p> : null}
        </> : <><p>구성 결정이 저장됐습니다. 다음으로 기본 구조 계획을 작성합니다.</p>{!props.active ? <button className="button button--primary" type="button" disabled={disabled} onClick={props.onRetry}>기본 구조 계획 {retry ? "다시 만들기" : "만들기"}</button> : null}</>}
      </> : stage === 3 ? <>
        <p>{bootstrap?.verified_integration_head ? `기본 구조 검증 완료 · 구현할 기능 ${features.length}개` : "기본 구조 검증 기록을 확인해야 기능 작업을 시작할 수 있습니다."}</p>
        <ul>{features.map((task) => <li key={task.id}>{task.title}</li>)}</ul>
        {run.stage === "planned" ? <button className="button button--primary" type="button" disabled={disabled || !bootstrap?.verified_integration_head} onClick={props.onStart}>이 계획으로 작업 시작</button> : <p role="status">작업 화면에서 구현 진행 상황을 확인할 수 있습니다.</p>}
        {props.bootstrapDetails ? <details><summary>기본 구조 검증 결과 확인</summary>{props.bootstrapDetails}</details> : null}
      </> : !questions && !props.active ? <p>기획을 시작하면 문서와 목표를 확인하고 추천을 준비합니다.</p> : null}
      {retry ? <div className="greenfield-flow__error" role="alert"><strong>{retry.answer_message ? "답변은 저장됐습니다. 추천 작성만 다시 시도할 수 있습니다." : "구성은 저장됐습니다. 기본 구조 계획 작성만 다시 시도할 수 있습니다."}</strong><details><summary>실패 이유 확인</summary><p>{retry.error}</p></details>{retry.answer_message ? <button className="button button--secondary" type="button" disabled={disabled} onClick={props.onRetry}>저장한 답변으로 다시 추천 받기</button> : null}</div> : null}
      {!props.available ? <p role="status">기획 모델 연결과 미저장 편집 내용을 확인해 주세요.</p> : null}
    </section>
  );
}
