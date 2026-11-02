const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const { renderToStaticMarkup } = require('react-dom/server');

const root = resolve(__dirname, '../..');
const tempRoot = join(root, '.tmp');
mkdirSync(tempRoot, { recursive: true });
const output = mkdtempSync(join(tempRoot, 'guided-flow-'));
const cleanup = () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); };
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  execFileSync(process.execPath, [resolve(dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig',
    '--strict', '--target', 'ES2022', '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/GreenfieldFlowPanel.tsx', 'desktop/renderer/src/greenfieldActions.ts'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);
const { GreenfieldFlowPanel } = require(join(output, 'renderer/src/GreenfieldFlowPanel.js'));
const flow = require(join(output, 'renderer/src/greenfieldFlow.js'));
const actions = require(join(output, 'renderer/src/greenfieldActions.js'));

function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
function text(tree) {
  if (typeof tree === 'string' || typeof tree === 'number') return String(tree);
  if (Array.isArray(tree)) return tree.map(text).join('');
  return tree ? text(tree.props?.children) : '';
}
function option(id = 'ts', rank = 1) {
  return { option_id: id, label: `${id} 메모 앱`, recommendation_rank: rank, requirement_fit: ['오프라인 메모 저장', 'Windows 지원', '로컬 실행'],
    tradeoffs: ['런타임 필요'], unresolved_constraints: [], version_policy: [], required_external_dependencies: [],
    components: { languages: [id], runtimes: [], application_frameworks: [], ui_frameworks: [], persistence: [],
      package_and_build_tools: [], test_tools: [], style_and_analysis: [], packaging_and_deployment: [] } };
}
function fixture(changes = {}) {
  return { id: 'same-group', repository_intent: 'new_project', stage: 'needs_clarification', greenfield_phase: 'options_ready',
    tech_stack_confirmation_allowed: true, summary: '개인 메모 앱', planning_request: '메모 앱을 만들어줘',
    planning_questions: [], planning_conversation_revision: 7, planning_apply_requests: [], plan_revision: 3, tasks: [],
    tech_stack_decisions: [{ decision_id: 'choice', revision: 2, status: 'options_ready', selected_option_id: '',
      requirement_sources: ['Plan.md'], options: [option(), option('cs', 2)] }], ...changes };
}
function panel(run = fixture(), changes = {}) {
  const calls = [];
  const tree = GreenfieldFlowPanel({ run, selectedOptionId: '', answer: 'Windows에서 씁니다.', busy: false, active: false,
    available: true, elapsed: 42, interruptible: true,
    onSelect: (id) => calls.push(['select', id]), onAnswer: (value) => calls.push(['answer', value]),
    onConfirm: (id, revision) => calls.push(['confirm', id, revision]), onRetry: () => calls.push(['retry']),
    onAnswerChange: (value) => calls.push(['change', value]), onStart: () => calls.push(['start']),
    onFeaturePlan: () => calls.push(['feature']), onInterrupt: () => calls.push(['interrupt']), ...changes });
  return { tree, calls, buttons: nodes(tree).filter((node) => node.type === 'button') };
}

test('recommendation is actionable without radio selection and alternatives are collapsed', () => {
  const current = panel();
  assert.deepEqual(current.calls, []);
  assert.equal(nodes(current.tree).filter((node) => node.type === 'input' && node.props.type === 'radio').length, 0);
  const confirm = current.buttons.find((node) => text(node) === '추천 구성으로 진행');
  assert.equal(confirm.props.disabled, false);
  confirm.props.onClick();
  assert.deepEqual(current.calls, [['confirm', 'ts', 2]]);
  const alternatives = nodes(current.tree).find((node) => node.props?.className === 'greenfield-flow__alternatives');
  assert.equal(alternatives.props.open, undefined);
  current.buttons.find((node) => text(node) === '이 구성 검토').props.onClick();
  assert.deepEqual(current.calls.at(-1), ['select', 'cs']);
});

test('real questions and answer input share one action and waiting has no operation timer or stop', () => {
  const current = panel(fixture({ tech_stack_confirmation_allowed: false, planning_questions: ['어디서 실행하나요?'] }));
  assert.match(renderToStaticMarkup(current.tree), /어디서 실행하나요/);
  assert.doesNotMatch(text(current.tree), /초 경과|기획 중지/);
  assert.equal(nodes(current.tree).find((node) => node.type === 'textarea').props.value, 'Windows에서 씁니다.');
  current.buttons.find((node) => text(node) === '답변하고 추천 받기').props.onClick();
  assert.deepEqual(current.calls, [['answer', 'Windows에서 씁니다.']]);
  assert.ok(!current.buttons.some((node) => /구성으로 진행/.test(text(node))));
});

test('busy, unavailable, read-only and empty answer cannot submit a guided answer', () => {
  for (const changes of [{ busy: true }, { active: true }, { available: false }, { answer: ' ' }]) {
    const current = panel(fixture({ tech_stack_confirmation_allowed: false, planning_questions: ['목표는?'] }), changes);
    const submit = current.buttons.find((node) => text(node) === '답변하고 추천 받기');
    assert.equal(submit.props.disabled, true);
    submit.props.onClick();
    assert.deepEqual(current.calls, []);
  }
});

test('choice-only questions obey the backend confirmation flag and explicit consent binds option and revision', () => {
  const run = fixture({ planning_questions: ['추천한 구성을 선택할까요?'] });
  assert.equal(flow.greenfieldConsentOption(run, 'ㅇㅇ 진행해').option_id, 'ts');
  assert.equal(flow.greenfieldConsentOption(run, 'ㅇㅇ 진행해', 'cs').option_id, 'cs');
  for (const message of ['왜 이 구성이야?', '실행하지 마', '파일 만들고 진행해', 'ㅇㅇ']) assert.equal(flow.greenfieldConsentOption(run, message), undefined);
  assert.equal(flow.greenfieldConsentOption({ ...run, tech_stack_confirmation_allowed: false }, 'ㅇㅇ 진행해'), undefined);
  assert.equal(flow.greenfieldConsentOption({ ...run, repository_intent: 'existing_structure' }, 'ㅇㅇ 진행해'), undefined);
  assert.equal(flow.greenfieldConsentOption(fixture({ tech_stack_decisions: [{ ...run.tech_stack_decisions[0], options: [option(), option('other', 1)] }] }), 'ㅇㅇ 진행해'), undefined);
  assert.equal(flow.greenfieldConsentOption({ ...run, greenfield_phase: 'feature_plan_ready' }, 'ㅇㅇ 진행해'), undefined);
});

test('actual AI activity shows elapsed and stop while failures preserve saved answer and retry stage', () => {
  assert.match(text(panel(fixture(), { active: true }).tree), /추천 구성 작성 중42초 경과기획 중지/);
  const request = { request_id: 'saved-answer', status: 'failed', plan_revision: 3, conversation_revision: 6,
    answer_conversation_revision: 7, tech_stack_revision: 2, answer_message: '메모 앱', error: 'AI 응답 실패' };
  const current = panel(fixture({ planning_apply_requests: [request], tech_stack_confirmation_allowed: false, planning_questions: ['목표는?'] }));
  assert.match(text(current.tree), /답변은 저장됐습니다/);
  current.buttons.find((node) => text(node) === '저장한 답변으로 다시 추천 받기').props.onClick();
  assert.deepEqual(current.calls, [['retry']]);
  assert.equal(flow.greenfieldRetry(fixture({ planning_apply_requests: [request], planning_conversation_revision: 8 })), undefined);
});

test('bootstrap and features require separate explicit start actions and completed initialization is not repeated', () => {
  const spec = { planned_paths: ['src/main.ts'], required_tools: ['Node.js'], verified_integration_head: '', feature_plan_error: '' };
  const bootstrap = panel(fixture({ stage: 'planned', greenfield_phase: 'bootstrap_ready', bootstrap_spec: spec }));
  bootstrap.buttons.find((node) => text(node) === '기본 구조 만들기').props.onClick();
  assert.deepEqual(bootstrap.calls, [['start']]);
  const features = panel(fixture({ stage: 'planned', greenfield_phase: 'feature_plan_ready', bootstrap_spec: { ...spec, verified_integration_head: 'verified' }, tasks: [{ id: 'memo', title: '메모 저장' }] }));
  features.buttons.find((node) => text(node) === '이 계획으로 작업 시작').props.onClick();
  assert.deepEqual(features.calls, [['start']]);
  assert.ok(!features.buttons.some((node) => text(node) === '기본 구조 만들기'));
  const failed = panel(fixture({ stage: 'failed', greenfield_phase: 'bootstrap_verifying', bootstrap_spec: spec }));
  assert.ok(!failed.buttons.some((node) => /작업 시작|기본 구조 만들기/.test(text(node))));
});

test('single answer action binds the current group, revisions and selected profile', async () => {
  const calls = [], updated = [];
  const run = fixture();
  await actions.requestGreenfieldPlan({ projectName: 'empty', run, requestId: 'answer-1', profile: { planningModel: 'model' },
    request: async (method, params) => { calls.push([method, params]); return { ...run, id: 'same-group' }; }, onUpdate: (value) => updated.push(value) }, '  Windows  ');
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0], ['runs.applyPlanningConversation', { projectName: 'empty', runId: 'same-group', requestId: 'answer-1',
    expectedRevision: 3, conversationRevision: 7, expectedTechStackRevision: 2, answer: 'Windows', retryFailed: false, planningModel: 'model' }]);
  assert.equal(updated.length, 1);
});

test('saved-answer retry reuses original request and pre-answer revision without appending again', async () => {
  const run = fixture({ planning_apply_requests: [{ request_id: 'failed-1', status: 'failed', plan_revision: 3, conversation_revision: 6,
    answer_conversation_revision: 7, tech_stack_revision: 2, answer_message: 'Windows' }] });
  let params;
  await actions.requestGreenfieldPlan({ projectName: 'empty', run, requestId: 'new-id', profile: {}, onUpdate() {},
    request: async (_, value) => { params = value; return run; } }, 'Windows');
  assert.equal(params.requestId, 'failed-1'); assert.equal(params.conversationRevision, 6); assert.equal(params.retryFailed, true);
});

test('confirmation persists its successful result before bootstrap planning fails and grants no execution', async () => {
  const run = fixture(), confirmed = { ...run, planning_conversation_revision: 8,
    tech_stack_decisions: [{ ...run.tech_stack_decisions[0], status: 'confirmed', selected_option_id: 'ts' }] };
  const calls = [], saved = [];
  await assert.rejects(actions.confirmGreenfieldOption({ projectName: 'empty', run, requestId: 'bootstrap-1', profile: {},
    onUpdate: (value) => saved.push(value), request: async (method, params) => {
      calls.push([method, params]); if (method === 'runs.confirmTechStack') return confirmed; throw new Error('plan failed');
    } }, 'ts', 2), /plan failed/);
  assert.deepEqual(saved, [confirmed]);
  assert.deepEqual(calls.map(([method]) => method), ['runs.confirmTechStack', 'runs.applyPlanningConversation']);
  assert.equal(calls[1][1].conversationRevision, 8);
  assert.equal(calls[1][1].answer, '');
});

test('reviewed execution passes atomic plan and bootstrap guards and rejects another stage', async () => {
  const calls = [];
  const context = { projectName: 'empty', requestId: 'unused', profile: {}, onUpdate() {},
    run: fixture({ stage: 'planned', greenfield_phase: 'bootstrap_ready', bootstrap_spec: { digest: 'reviewed' }, tasks: [{ id: 'project-bootstrap' }] }),
    request: async (method, params) => { calls.push([method, params]); throw new Error('stale plan'); } };
  await assert.rejects(actions.confirmGreenfieldExecution(context), /stale plan/);
  assert.deepEqual(calls, [['runs.confirmPlan', { projectName: 'empty', runId: 'same-group', expectedRevision: 3, bootstrapDigest: 'reviewed' }]]);
  calls.length = 0;
  await assert.rejects(actions.confirmGreenfieldExecution({ ...context, run: fixture() }), /현재 단계/);
  assert.deepEqual(calls, []);
});
