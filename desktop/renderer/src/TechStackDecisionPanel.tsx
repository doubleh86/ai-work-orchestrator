import type { TechStackDecision } from "./types";
import { techStackCoreItems, techStackDevelopmentItems } from "./techStackDecision";

export interface TechStackDecisionPanelProps {
  decision: TechStackDecision;
  selectedOptionId: string;
  busy: boolean;
  confirming: boolean;
  confirmationAllowed?: boolean;
  questions: string[];
  answeringAllowed: boolean;
  onSelect(optionId: string): void;
  onConfirm(): void;
  onAnswerQuestions(): void;
}

function ListSection(props: { title: string; items: string[] }) {
  if (!props.items.length) return null;
  return (
    <div className="tech-stack-option__section">
      <strong>{props.title}</strong>
      <ul>{props.items.map((item) => <li key={item}>{item}</li>)}</ul>
    </div>
  );
}

export function TechStackDecisionPanel(props: TechStackDecisionPanelProps) {
  const confirmed = props.decision.status === "confirmed";
  const questionsRequired = props.decision.status === "questions_required" && !props.confirmationAllowed;
  const selectedOption = props.decision.options.find((option) => option.option_id === props.selectedOptionId);
  const selectOption = (optionId: string) => {
    if (!props.busy && !confirmed) props.onSelect(optionId);
  };
  return (
    <section className="tech-stack-decision" aria-labelledby="tech-stack-decision-title">
      <header className="tech-stack-decision__heading">
        <div>
          <span className="eyebrow">TECHNOLOGY CHOICE · REVISION {props.decision.revision}</span>
          <h3 id="tech-stack-decision-title" tabIndex={-1}>
            {confirmed ? "기술 구성을 결정했습니다" : `기술 구성 ${props.decision.options.length}개를 비교할 수 있습니다`}
          </h3>
          <p>
            {confirmed
              ? "결정만 저장했습니다. 프로젝트 파일과 기본 구조는 아직 만들지 않았습니다."
              : questionsRequired
                ? "구성을 결정하기 전에 확인할 내용이 있습니다. 아래 질문에 답한 뒤 후보를 갱신해 주세요."
                : "요구사항에 맞는 구성을 선택하세요. 확정해도 프로젝트 파일은 만들지 않습니다."}
          </p>
        </div>
      </header>
      <fieldset
        className="tech-stack-options"
        data-option-count={Math.min(props.decision.options.length, 3)}
        disabled={props.busy || confirmed}
      >
        <legend className="sr-only">기술 구성 후보</legend>
        {props.decision.options.map((option) => {
          const selected = props.selectedOptionId === option.option_id;
          const inputId = `tech-stack-${props.decision.decision_id}-${props.decision.revision}-${option.option_id}`;
          const coreItems = techStackCoreItems(option);
          const developmentItems = techStackDevelopmentItems(option);
          return (
            <div
              className="tech-stack-option"
              data-selected={selected}
              key={option.option_id}
              onClick={() => selectOption(option.option_id)}
            >
              <input
                id={inputId}
                type="radio"
                name={`tech-stack-${props.decision.decision_id}-${props.decision.revision}`}
                checked={selected}
                onChange={() => selectOption(option.option_id)}
                onClick={(event) => event.stopPropagation()}
              />
              <div className="tech-stack-option__body">
                <label className="tech-stack-option__header" htmlFor={inputId} onClick={(event) => event.stopPropagation()}>
                  <strong className="tech-stack-option__title">{option.label}</strong>
                  {option.recommendation_rank === 1 ? <small>추천</small> : <small>대안 {option.recommendation_rank - 1}</small>}
                </label>
                <ListSection title="추천 이유" items={option.requirement_fit} />
                {coreItems.length ? <p className="tech-stack-option__core"><strong>핵심 구성</strong><span>{coreItems.join(" · ")}</span></p> : null}
                <ListSection title="단점·미결정" items={[...option.tradeoffs, ...option.unresolved_constraints]} />
                <details className="tech-stack-option__details" onClick={(event) => event.stopPropagation()}>
                  <summary>구성 상세 보기</summary>
                  <ListSection title="핵심 구성 전체" items={coreItems} />
                  <ListSection title="개발 기준" items={developmentItems} />
                  <ListSection title="배포 대상" items={option.components.packaging_and_deployment} />
                  <ListSection title="비용과 운영" items={option.required_external_dependencies} />
                  <ListSection title="버전 정책" items={option.version_policy} />
                </details>
              </div>
            </div>
          );
        })}
      </fieldset>
      <div className="tech-stack-decision__actions">
        {confirmed ? (
          <p role="status">선택한 구성 · <strong>{selectedOption?.label || props.decision.selected_option_id}</strong></p>
        ) : questionsRequired ? (
          <section className="tech-stack-decision__questions" aria-labelledby="tech-stack-questions-title">
            <h4 id="tech-stack-questions-title">먼저 확인할 내용</h4>
            {props.questions.length ? <ol>{props.questions.map((question, index) => <li key={index}>{question}</li>)}</ol>
              : <p>저장된 질문 내용을 찾지 못했습니다. 기획 대화에서 확인하고 후보를 갱신해 주세요.</p>}
            {selectedOption ? <p>검토 중인 구성 · <strong>{selectedOption.label}</strong></p> : null}
            <p id="tech-stack-questions-help">아래 기획 대화에 답변을 전송하고 ‘답변으로 후보 갱신’을 누르면, 갱신된 후보에서 구성을 결정할 수 있습니다.</p>
            {!props.answeringAllowed ? <p>현재 단계와 기획 모델 설정을 확인한 뒤 답변해 주세요.</p> : null}
            <button className="button button--primary" type="button" aria-describedby="tech-stack-questions-help"
              disabled={props.busy || !props.answeringAllowed} onClick={() => {
                if (!props.busy && props.answeringAllowed) props.onAnswerQuestions();
              }}>질문에 답하기</button>
          </section>
        ) : selectedOption ? (
          <div className="tech-stack-decision__selection">
            <p>선택한 구성 · <strong>{selectedOption.label}</strong></p>
            <button
              className="button button--primary"
              type="button"
              disabled={props.busy}
              onClick={() => { if (!props.busy) props.onConfirm(); }}
            >
              {props.confirming ? "결정 저장 중…" : "선택한 구성으로 결정"}
            </button>
          </div>
        ) : (
          <p className="tech-stack-decision__prompt" role="status">
            먼저 기술 구성을 선택해 주세요.
          </p>
        )}
      </div>
    </section>
  );
}
