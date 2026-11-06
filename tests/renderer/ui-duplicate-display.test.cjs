const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');
const { createElement } = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const root = resolve(__dirname, '../..'), temp = join(root, '.tmp');
mkdirSync(temp, { recursive: true });
const output = mkdtempSync(join(temp, 'ui-duplicate-display-'));
process.on('exit', () => { assert.equal(dirname(output), temp); rmSync(output, { recursive: true, force: true }); });
const pkg = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(pkg), require(pkg).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
  'desktop/renderer/src/App.tsx', 'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });
const modulePath = (file) => join(output, 'renderer/src', file);
function exported(file, names, hooks = false, initialStates = []) {
  const path = modulePath(file), local = createRequire(path), result = {};
  let stateIndex = 0;
  runInNewContext(readFileSync(path, 'utf8') + names.map(name => `\nexports.${name}=${name};`).join(''), {
    exports: result, require: name => hooks && name === 'react' ? { ...local(name),
      useEffect() {}, useLayoutEffect() {}, useRef: current => ({ current }),
      useState(value) {
        const index = stateIndex++;
        return [index in initialStates ? initialStates[index] : typeof value === 'function' ? value() : value, () => {}];
      },
      useMemo: callback => callback(), useCallback: callback => callback,
      useSyncExternalStore(subscribe, snapshot) { return snapshot(); },
    } : local(name),
  });
  return result;
}
const results = exported('ResultReview.js', ['FinalFiles', 'TaskResultCard', 'ResultReview'], true);
const app = exported('App.js', ['RunNextActionBanner', 'PlanningWorkbench', 'TaskWorkbench', 'TaskRow', 'profileOverrides', 'ApplicationErrorBanner'], true);
const { AiBadge } = require(modulePath('AiBadge.js'));
const { GreenfieldFlowPanel } = require(modulePath('GreenfieldFlowPanel.js'));
const html = renderToStaticMarkup;
function nodes(tree) { if (!tree || typeof tree !== 'object') return []; return Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)]; }
function text(tree) { if (typeof tree === 'string' || typeof tree === 'number') return String(tree); return Array.isArray(tree) ? tree.map(text).join('') : text(tree?.props?.children || ''); }

test('provider request limit banner keeps raw errors in collapsed details and shows a short next step', () => {
  for (const [message, expected] of [
    ['exceeded retry limit, last status: 429 Too Many Requests', 'AI 요청이 제한되었습니다. 잠시 후 다시 시도해 주세요.'],
    ['HTTP 429: insufficient_quota', 'AI 사용 한도에 도달했습니다. AI 사용 한도와 갱신 시점을 확인한 뒤 다시 시도해 주세요.'],
  ]) {
    const tree = app.ApplicationErrorBanner({ message });
    const detail = nodes(tree).find(node => node.type === 'details');
    assert.ok(detail); assert.ok(!detail.props.open); assert.ok(text(detail).includes(message));
    assert.equal(text(nodes(tree).find(node => node.type === 'p')), expected);
  }
  const other = app.ApplicationErrorBanner({ message: 'unrelated failure' });
  assert.ok(text(other).includes('unrelated failure'));
});
const task = (extra = {}) => ({ id: 'task', title: '변경 작업', status: 'completed', description: '설명', completed_commit: 'commit',
  dependencies: [], conflict_dependencies: [], conflict_group: [], action_results: [], result_history: [], acceptance_criteria: [], ...extra });

test('NVIDIA coding is explicitly selectable and produces a saved task override', () => {
  const model = 'nvidia/nemotron-3-super-120b-a12b';
  const profiles = [
    { provider_id: 'codex', agent_id: 'worker', model: 'gpt-6.1-sol', reasoning_efforts: [] },
    { provider_id: 'nvidia', agent_id: 'nvidia-experimental', model, configured_model: model, reasoning_efforts: [] },
  ];
  const item = task({ status: 'pending', readiness: 'ready', agent_id: 'worker', provider_id: 'codex', model: 'gpt-6.1-sol', reasoning_effort: 'high' });
  let selected;
  const props = { profileOnly: true, task: item, sequence: 1, busy: false, profileEditable: true, profileEditorOpen: true,
    profile: { agentId: 'worker', model: 'gpt-6.1-sol', reasoningEffort: '' }, options: profiles,
    onProfileChange(value) { selected = value; } };
  const tree = app.TaskRow(props);
  const select = nodes(tree).find(node => node.type === 'select' && node.props['aria-label'] === '변경 작업 실행 모델');
  assert.ok(select && !select.props.disabled);
  const option = nodes(select).find(node => node.type === 'option' && text(node).includes('NVIDIA'));
  assert.ok(option);
  select.props.onChange({ target: { value: option.props.value } });
  assert.equal(selected.agentId, 'nvidia-experimental'); assert.equal(selected.model, model);
  const changes = app.profileOverrides({ tasks: [item] }, { task: selected });
  assert.equal(changes.agentOverrides.task, 'nvidia-experimental');
  assert.equal(changes.modelOverrides.task, model);
  assert.equal(changes.reasoningEffortOverrides.task, '');
  const changedTree = app.TaskRow({ ...props, profile: selected });
  const reasoning = nodes(changedTree).find(node => node.type === 'select' && node.props['aria-label'] === '변경 작업 추론 강도');
  assert.equal(text(reasoning), '자동 선택 · NVIDIA · 시험');
  assert.match(html(AiBadge({ provider: 'nvidia', requestedModel: model, planned: true, compact: true })), /NVIDIA · 시험/);
  const running = app.TaskRow({ ...props, task: { ...item, status: 'running' } });
  assert.equal(nodes(running).filter(node => node.type === 'select').length, 0);
});
const record = (extra = {}) => ({ result_commit: 'commit', files_state: 'confirmed', files: [{ change: 'modified', path: 'file-a.ts' }],
  captured_at: '2026-10-08T00:00:00Z', verification_status: 'passed', passed_commands: [], self_report: '만든 내용', ...extra });

test('one file summary owns each result and the collapsed file record preserves every path once', () => {
  const files = Array.from({ length: 5 }, (_, i) => ({ change: 'modified', path: `unique-file-${i}.ts` }));
  const markup = html(results.FinalFiles({ state: 'confirmed', files }));
  assert.equal((markup.match(/파일 5개 변경/g) || []).length, 1);
  for (const file of files) assert.equal(markup.split(file.path).length - 1, 1);
  assert.match(markup, /변경 파일 보기/);
  for (const state of ['none', 'unavailable', 'confirmed']) {
    const current = record({ files_state: state, error: state === 'unavailable' ? '파일 조회 실패 원문' : '' });
    const card = html(results.TaskResultCard({ task: task({ result_history: [current] }), onOpenTask() {} }));
    const label = state === 'none' ? '파일 변경 없음' : state === 'unavailable' ? '최종 변경 파일 확인 불가' : '파일 1개 변경';
    assert.equal(card.split(label).length - 1, 1, state);
    assert.match(card, /Task 상세·로그/);
    if (state === 'unavailable') assert.match(card, /파일 조회 실패 원문/);
  }
});

test('single-page result views group records and keep one outcome with an explicit chat return', () => {
  const { ResultRevisionRequests } = require(modulePath('resultRevisionRequests.js'));
  const completed = task({ result_history: [record()] });
  const run = { id: 'group', summary: '반복하지 않을 긴 그룹 목표', stage: 'verified', tasks: [completed], planning_request: '반복하지 않을 처음 요청',
    verification_attempts: [{ status: 'succeeded', verified_integration_head: 'head', passed_commands: [['test']] }],
    verified_integration_head: 'head', group_result_history: [record({ result_commit: 'head' })] };
  for (const focusTaskId of ['task', '']) {
    const actions=[];
    const tree = results.ResultReview({ projectName: 'mock', run, focusTaskId, requests: new ResultRevisionRequests(),
      onDraftChange() {}, onNavigate() {}, onOpenTask() {}, onOpenOperations() {actions.push('operations');}, onDiscuss() {actions.push('chat');} });
    const markup = html(tree);
    assert.doesNotMatch(markup,/요청한 내용|직접 확인할 부분|반복하지 않을 처음 요청/);
    assert.equal(nodes(tree).filter(node=>node.props.className==='result-review__outcome').length,1);
    assert.equal(nodes(tree).filter(node=>node.props.className==='result-review__summary').length,1);
    const records=nodes(tree).find(node=>node.props.className==='result-review__details');
    assert.equal(records.type,'details'); assert.equal(records.props.open,false);
    const files=nodes(tree).find(node=>node.props.className==='result-review__files');
    assert.equal(files.type,'details');assert.notEqual(files.props.open,true);
    assert.equal((html(files).match(/파일 1개 변경/g)||[]).length,1,focusTaskId);
    assert.match(html(files),/file-a.ts/);assert.match(html(files),/commit/);
    assert.ok(nodes(tree).some(node=>node.props.className==='result-review__verification'));
    const request=nodes(tree).find(node=>node.props.className==='result-review__request');
    assert.equal(request.type,'details');assert.equal(request.props.open,false);
    assert.equal(nodes(tree).some(node=>node.props.className==='result-review__related'),false);
    const summary=nodes(tree).find(node=>node.props.className==='result-review__summary');
    assert.doesNotMatch(html(summary),/file-a.ts/);
    const verification=nodes(tree).find(node=>node.type==='button'&&text(node)==='최종 검증 기록');
    assert.deepEqual(actions,[]);verification.props.onClick();assert.deepEqual(actions,['operations']);
    const chat=nodes(tree).find(node=>node.type==='button'&&text(node)==='채팅에서 이어가기');
    chat.props.onClick();assert.deepEqual(actions,['operations','chat']);
  }
});

test('AI badge owns its amount once while errors retain the previous amount and separate scopes', () => {
  const usage = { call_count: 1, total_tokens: 35, coverage: 'partial', reported_call_count: 1, complete_call_count: 0, running_call_count: 0 };
  for (const usageError of ['', '조회 실패']) {
    const markup = html(AiBadge({ provider: 'codex', requestedModel: 'configured', usage, usageError }));
    assert.equal((markup.match(/현재 보고량 35토큰/g) || []).length, 1);
    if (usageError) assert.match(markup, /이전 기록 보존|조회 실패/);
    assert.match(markup, /기록된 호출의 공급자 보고량/);
  }
});

const option = (id, rank) => ({ option_id: id, label: `구성 ${id}`, recommendation_rank: rank, requirement_fit: ['요구 충족'],
  tradeoffs: [], unresolved_constraints: [], components: { languages: [id], runtimes: [], application_frameworks: [], ui_frameworks: [], persistence: [], package_and_build_tools: [], test_tools: [], style_and_analysis: [], packaging_and_deployment: [] } });
const decision = { status: 'options_ready', decision_id: 'choice', revision: 1, requirement_sources: [], options: [option('a', 1), option('b', 2)] };
const run = (extra = {}) => ({ id: 'group', summary: '그룹 목표', repository_intent: 'new_project', stage: 'needs_clarification',
  tasks: [], events: [], planning_questions: ['어떤 환경인가요?'], planning_messages: [], planning_follow_up_requests: [], tech_stack_decisions: [decision], ...extra });

test('current technology is shown once and another option can still return to the original recommendation', () => {
  for (const selectedOptionId of ['a', 'b']) {
    const calls = [];
    const tree = GreenfieldFlowPanel({ run: run({ planning_questions: [], tech_stack_confirmation_allowed: true, greenfield_phase: 'options_ready' }),
      selectedOptionId, answer: '', busy: false, active: false, available: true, elapsed: 0,
      onSelect: id => calls.push(id), onConfirm() {}, onRetry() {}, onFeaturePlan() {}, onStart() {} });
    const markup = html(tree);
    assert.equal((markup.match(/구성 a/g) || []).length, 1); assert.equal((markup.match(/구성 b/g) || []).length, 1);
    assert.doesNotMatch(markup, /그룹 목표/);
    nodes(tree).find(node => node.type === 'button' && text(node) === '이 구성 검토').props.onClick();
    assert.deepEqual(calls, [selectedOptionId === 'a' ? 'b' : 'a']);
  }
});

const workbench = (current, extra = {}) => app.PlanningWorkbench({ project: { name: 'mock' }, run: current, message: '', messageViews: {},
  path: '', request: '', mode: 'directed', profiles: [], providerStatuses: [], reasoningOptions: [], effortMode: 'balanced',
  planningElapsed: 0, indexElapsed: 0, preparationMessage: '', busyAction: '', bodyVisible: true, ...extra });
test('archived conversations allow explicit messages without exposing plan mutation actions', () => {
  const current = run({ stage: 'pushed', archive: { cleanup_status: 'completed' }, repository_intent: 'existing_structure',
    planning_questions: [], planning_messages: [{role:'assistant', text:'완료된 작업', at:'2026-10-20T00:00:00Z'}] });
  const calls = [];
  const tree = workbench(current, { message: '이 작업 다음에는 무엇을 하면 좋을까?', onSend: () => calls.push('send') });
  const input = nodes(tree).find(node => node.type === 'textarea');
  assert.equal(input.props.disabled, false); assert.match(input.props.placeholder, /다음 작업을 논의/);
  const buttons = nodes(tree).filter(node => node.type === 'button');
  assert.ok(!buttons.some(node => /수정안 확인|작업에 반영/.test(text(node))));
  const send = buttons.find(node => text(node) === '전송');
  assert.equal(send.props.disabled, false); send.props.onClick();
  assert.deepEqual(calls, ['send']); assert.match(text(tree), /보관된 결과는 유지/);
  const busy = workbench(current, {message:'질문',busyAction:'runs.sendPlanningMessage'});
  assert.equal(nodes(busy).find(node => node.type === 'button' && text(node) === '전송 중').props.disabled, true);
});
test('central questions suppress only synthetic chat copies and preserve real conversation and ordinary questions', () => {
  const current = run();
  const tree = workbench(current);
  assert.equal(nodes(tree).filter(node => node.type === 'article' && node.props['data-central-question'] === true).length, 1);
  const original = workbench({ ...current, planning_messages: [{ role: 'assistant', text: current.planning_questions[0], at: '2026-10-08T00:00:00Z' }] });
  assert.equal(nodes(original).filter(node => node.type === 'article' && node.props.className === 'chat-message chat-message--assistant').length, 1);
  const plain = workbench({ ...current, repository_intent: 'existing_structure', tech_stack_decisions: [] });
  const fallback = nodes(plain).filter(node => node.type === 'article' && node.props.className === 'chat-message chat-message--assistant');
  assert.equal(fallback.length, 1);
  assert.equal(fallback[0].props['data-central-question'], undefined);
});

test('task failures omit the duplicate recovery banner while keeping chat status and raw failure evidence', () => {
  const { runNextAction } = require(modulePath('runNextAction.js'));
  const { runRecoveryGuidance } = require(modulePath('runRecoveryGuidance.js'));
  const { ChatWorkActivity, ChatWorkStatus } = require(modulePath('ChatWorkActivity.js'));
  for (const error of ['task_scope_review_required: {"reason":"범위 확인","paths":["src/Adapter.cs"]}',
    'agent worker produced no commit', 'verification command failed']) {
    const current = run({ stage: 'failed', failed_step: 'agent_execution', repository_intent: 'existing_structure', workspace_mode: 'shared',
      execution_control: { situation: 'attention_required', action: 'none', lock_state: 'unlocked', reason: '실패 기록 확인' },
      tasks: [task({ id: 'failed-task', title: '실패한 작업', status: 'failed', completed_commit: '', error })], planning_questions: [] });
    const action = runNextAction(current, { planDirty: false, pendingAction: '' });
    const recovery = runRecoveryGuidance(current);
    assert.equal(recovery.taskId, 'failed-task'); assert.equal(action.tone, 'danger');
    for (const expanded of [false, true]) {
      assert.equal(app.RunNextActionBanner({ action, recovery, busy: false, expanded,
        onToggle() { assert.fail('removed banner'); }, onInvoke() { assert.fail('render cannot invoke recovery'); } }), null);
    }
    const chat = html(ChatWorkActivity({ run: current, action, busy: false, repairing: false,
      onAction() { assert.fail('render cannot execute'); }, onDiscuss() {}, onTasks() {} }));
    assert.match(chat, /오류 상세/); assert.ok(chat.includes(error.replaceAll('"', '&quot;')));
    const status = html(ChatWorkStatus({ run: current, action }));
    assert.match(status, /수정 범위 확인 대기|실패 · 복구 확인 필요/);
    const cards = app.TaskWorkbench({ run: current, cardsOnly: true,
      selectedTaskId: '', selectedTaskIds: [], profiles: {}, profileOptions: {}, planDirty: false,
      draftConflict: false, draftErrorCount: 0, busyAction: '', executionAction: '',
      nextAction: createElement(app.RunNextActionBanner, { action, recovery, busy: false, expanded: false,
        onToggle() {}, onInvoke() { assert.fail('render cannot invoke recovery'); } }),
      onAddTask() {}, onResetPlan() {}, onSavePlan() {} });
    const cardsMarkup = html(cards);
    assert.match(cardsMarkup, /실패한 작업/);
    assert.doesNotMatch(cardsMarkup, /run-next-action|실패 복구|실패 위치|수정 범위 논의|안내 펼치기/);
    assert.equal(current.tasks[0].status, 'failed'); assert.equal(current.tasks[0].error, error);
  }
});

test('expanded current activity does not repeat the same purpose sentence', () => {
  for (const expanded of [false, true]) {
    const markup = html(app.RunNextActionBanner({ action: { kind: 'none', tone: 'active', status: '준비 중', description: '현재 작업을 준비합니다.' },
      busy: false, expanded, onToggle() {}, onInvoke() {} }));
    assert.equal((markup.match(/현재 작업을 준비합니다\./g) || []).length, 1);
    assert.doesNotMatch(markup, /안내 펼치기|안내 접기|run-next-action-details/);
  }
});

test('blank guidance has no disclosure while real pre-action instructions retain toggling and action guards', () => {
  for (const description of ['', '  \n']) {
    const tree = app.RunNextActionBanner({ action: { kind:'execute', tone:'neutral', status:'실행 가능', label:'작업 시작', description },
      busy:false, expanded:true, onToggle(){ assert.fail('no empty disclosure'); }, onInvoke(){} });
    assert.doesNotMatch(html(tree), /안내 펼치기|안내 접기|run-next-action-details/);
    assert.equal(nodes(tree).filter(node => node.type === 'button').length,1);
  }
  for (const expanded of [false,true]) {
    let toggled=0, invoked=0;
    const tree = app.RunNextActionBanner({ action: { kind:'confirm_plan', tone:'warning', status:'계획 검토', label:'계획 확정',
      description:'확정 후 작업 실행은 별도로 시작합니다.' }, busy:true, expanded, onToggle(){toggled++;}, onInvoke(){invoked++;} });
    const toggle=nodes(tree).find(node => node.props.className === 'run-next-action__toggle');
    assert.ok(toggle); assert.equal(toggle.props['aria-expanded'],expanded);
    assert.equal(toggle.props['aria-controls'],'run-next-action-details');
    const details=nodes(tree).find(node => node.props.id === 'run-next-action-details');
    assert.equal(details.props.hidden,!expanded); assert.match(text(details),/별도로 시작/);
    assert.equal(nodes(tree).find(node => node.props.className === 'button button--primary').props.disabled,true);
    assert.equal(invoked,0); toggle.props.onClick(); assert.equal(toggled,1); assert.equal(invoked,0);
  }
});

test('recovery instructions remain available even when active status already owns its short description', () => {
  const recovery={location:'실패 작업', cause:'제공자 혼잡', recommendation:'잠시 후 다시 시도', effect:'완료 작업 보존', evidence:'원문 오류'};
  for(const expanded of [false,true]) {
    const tree=app.RunNextActionBanner({action:{kind:'none',tone:'active',status:'확인 중',description:'현재 상태를 확인합니다.'},
      recovery,busy:false,expanded,onToggle(){},onInvoke(){assert.fail('render cannot execute');}});
    const details=nodes(tree).find(node => node.props.id === 'run-next-action-details');
    assert.ok(details); assert.equal(details.props.hidden,!expanded);
    for(const value of Object.values(recovery).slice(1)) assert.ok(text(details).includes(value));
    assert.match(html(tree),/안내 펼치기|안내 접기/);
    assert.equal((text(tree).match(/현재 상태를 확인합니다\./g)||[]).length,1);
  }
});

test('guided feature failure has one retry even after expanding bootstrap details; independent use keeps its own retry', () => {
  const spec = { digest: 'digest', target_root: 'mock', decision_revision: 1, planned_paths: [], required_tools: [], steps: [],
    verify_commands: [], excluded_external_actions: [], verified_integration_head: 'commit', feature_plan_error: '기능 계획 실패' };
  const current = run({ greenfield_phase: 'bootstrap_verified', planning_questions: [], bootstrap_spec: spec,
    tech_stack_decisions: [{ ...decision, status: 'confirmed' }] });
  const guided = nodes(workbench(current)).find(node => node.type === GreenfieldFlowPanel);
  assert.ok(guided.props.bootstrapDetails);
  assert.equal(guided.props.bootstrapDetails.props.onRetry, undefined);
  const markup = html(GreenfieldFlowPanel(guided.props));
  assert.equal((markup.match(/기능 계획 다시 만들기/g) || []).length, 1);
  assert.match(markup, /기능 계획 실패/);
  const callback = () => {};
  const independent = workbench({ ...current, repository_intent: 'existing_structure' }, { onGenerateFeaturePlan: callback });
  const panel = nodes(independent).find(node => node.type?.name === 'BootstrapSpecPanel');
  assert.equal(panel.props.onRetry, callback);
});

test('plan banner owns ordinary confirmation while editing actions, invalid input and unapproved fallback remain', () => {
  const base = { run: run({ stage: 'planned', plan_revision: 1, plan_approved_revision: 0, tasks: [task({ status: 'pending', agent_id: 'codex', model: 'configured' })] }),
    selectedTaskId: '', selectedTaskIds: [], profiles: {}, profileOptions: {}, planDirty: false, draftConflict: false,
    draftErrorCount: 0, busyAction: '', executionAction: '', onAddTask() {}, onResetPlan() {}, onSavePlan() {} };
  const tree = app.TaskWorkbench({ ...base, nextAction: createElement('p', null, '계획을 확정하세요') });
  const review = nodes(tree).find(node => node.props.className?.startsWith('plan-review-state '));
  assert.doesNotMatch(text(review), /계획 확정 필요/);
  assert.equal(review, undefined, 'ordinary confirmation has no duplicate editor toolbar');
  const manual = nodes(tree).find(node => node.type === 'details' && text(node).includes('직접 계획 편집'));
  assert.ok(manual); assert.equal(manual.props.open, undefined);
  assert.equal(nodes(manual).filter(node => node.type === 'button').length, 1);
  const fallback = app.TaskWorkbench(base);
  assert.match(text(fallback), /다음 단계 · 계획 확정 필요/);
  const invalid = app.TaskWorkbench({ ...base, nextAction: createElement('p', null, '계획 확인'), draftErrorCount: 1, planDirty: true });
  assert.match(text(invalid), /입력 오류 1개/);
  const save = nodes(invalid).find(node => node.type === 'button' && text(node) === '변경 저장');
  assert.equal(save.props.disabled, false);
  const conflict = app.TaskWorkbench({ ...base, nextAction: createElement('p', null, '계획 확인'), draftConflict: true, planDirty: true });
  assert.equal(nodes(conflict).find(node => node.type === 'button' && text(node) === '변경 저장').props.disabled, true);
});

test('requested planning policy and current model evidence remain independently labelled when models differ', () => {
  const { PlanningPolicySummary } = require(modulePath('PlanningEffortPicker.js'));
  const markup = html(createElement('div', null,
    PlanningPolicySummary({ control: { planning_policy: { mode: 'balanced', planning_profile: { model: 'request-model', reasoning_effort: 'high' } }, planning_request_status: 'finished' } }),
    AiBadge({ provider: 'codex', requestedModel: 'current-model', planned: false })));
  assert.match(markup, /최근 기획 요청 정책/);
  assert.match(markup, /request-model/); assert.match(markup, /current-model/);
  assert.match(markup, /실행 모델 미확인/);
});

test('recovery progress owns the phase while disabled actions preserve their purpose, delay and partial results', () => {
  const { recoveryPhaseLabel } = require(modulePath('recoveryOperation.js'));
  const now = Date.parse('2026-10-08T02:00:00Z');
  const plan = { sources: [], failed_tasks: [], failure: '원래 실패 원인', run_id: 'group' };
  for (const [action, phase, status, elapsed] of [
    ['recovery_preview', 'collecting_sources', 'running', 0], ['recovery_apply', 'replanning', 'running', 20],
    ['recovery_apply', 'integrating_commits', 'running', 70], ['recovery_apply', 'replanning', 'partial', 70],
    ['recovery_apply', 'completed', 'succeeded', 70],
  ]) {
    const operation = { action, phase, status, created_at: new Date(now - elapsed * 1000).toISOString(), updated_at: new Date(now - elapsed * 1000).toISOString(),
      request_id: 'request', result_commit: 'integrated-result', resume_request_id: '', result: null, error: '' };
    const component = exported('RecoveryDialog.js', ['RecoveryDialog'], true, [plan, [], operation, true, undefined, '', false, false, now]);
    const tree = component.RecoveryDialog({ projectName: 'mock', runId: 'group', runTitle: '복구할 그룹', onApplied() {}, onClose() {} });
    const markup = html(tree);
    const label = status === 'succeeded' ? '복구 적용 완료 · 그룹 상태 확인 중' : recoveryPhaseLabel(operation);
    assert.equal(markup.split(label).length - 1, 1, `${action}/${phase}/${status}`);
    if (status === 'running' || status === 'succeeded') assert.equal(nodes(tree).find(node => node.type === 'button' && node.props.className === 'button button--primary').props.disabled, true);
    if (elapsed === 70 && status === 'running') assert.match(markup, /복구 상태 다시 확인/);
    if (status === 'partial') assert.match(markup, /integrated-r/);
  }
});

test('registration separates repository initialization, first commit and registration rather than merging their effects', () => {
  for (const kind of ['not_initialized', 'unborn', 'ready', 'invalid']) {
    const readiness = { kind, diagnostics: [], repository_root: 'mock-only', head_commit: kind === 'ready' ? 'commit' : '', main_branch: 'main' };
    const commit = kind === 'unborn' ? { changes: [], author_name: '', author_email: '', readiness: { author_configured: false } } : undefined;
    const components = exported('App.js', ['ProjectDialog'], true, [readiness, commit]);
    const tree = components.ProjectDialog({ open: true, intent: 'existing', draft: { name: 'mock', repo: 'mock-only' }, busy: false,
      onChange() {}, onChoosePath() {}, onClose() {}, onSubmit() {} });
    const buttons = nodes(tree).filter(node => node.type === 'button');
    assert.equal(nodes(tree).filter(node => node.type === 'h2').length, 1);
    assert.equal(buttons.filter(node => text(node) === '로컬 Git 저장소 만들기').length, kind === 'not_initialized' ? 1 : 0);
    assert.equal(buttons.filter(node => text(node) === '첫 commit 만들기').length, kind === 'unborn' ? 1 : 0);
    const submit = buttons.find(node => node.props.type === 'submit');
    assert.equal(Boolean(submit.props.disabled), kind !== 'ready');
  }
});

test('project settings keep source/workspace, configured checks and independent failures with one control per effect', () => {
  const draft = { mode: 'repository_first', fallback_by_language: { python: 'pep8' }, custom_instruction_paths: [] };
  const profile = { status: 'detected', detected_languages: ['python'], rules: [], checks: [], diagnostics: [], preference: draft };
  for (const failed of [false, true]) {
    const components = exported('App.js', ['ProjectSettingsDialog'], true, ['', false, '', failed ? 'SDK 확인 실패' : '', undefined,
      { repo: 'mock-source', root: 'mock-workspace', created: false }, failed ? '작업공간 조회 실패' : '', profile, draft, false, false, failed ? '규칙 조회 실패' : '']);
    const tree = components.ProjectSettingsDialog({ project: { name: 'mock' }, runId: 'group', taskId: '', onOpenTechStack() {}, onSaved() {}, onClose() {} });
    const markup = html(tree);
    assert.match(markup, /mock-source/); assert.match(markup, /mock-workspace/);
    assert.match(markup, /아직 실행 안 함|자동 검사 없음/);
    const buttons = nodes(tree).filter(node => node.type === 'button');
    assert.equal(buttons.filter(node => text(node) === '저장 후 SDK 확인').length, 1);
    assert.equal(buttons.filter(node => node.props.type === 'submit').length, 1);
    if (failed) for (const message of ['SDK 확인 실패', '작업공간 조회 실패', '규칙 조회 실패']) assert.equal(markup.split(message).length - 1, 1);
  }
});
