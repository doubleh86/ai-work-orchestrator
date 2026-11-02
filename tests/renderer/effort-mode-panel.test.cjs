const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');
const { renderToStaticMarkup } = require('react-dom/server');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(root, '.tmp');
mkdirSync(tempRoot, { recursive: true });
const output = resolve(mkdtempSync(join(tempRoot, 'effort-mode-panel-')));
const cleanup = () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); };
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  execFileSync(process.execPath, [resolve(dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig',
    '--strict', '--target', 'ES2022', '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/EffortModePanel.tsx', 'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

function find(element, predicate) {
  if (!element || typeof element !== 'object') return undefined;
  if (predicate(element)) return element;
  const children = element.props?.children;
  for (const child of Array.isArray(children) ? children.flat() : [children]) {
    const found = find(child, predicate);
    if (found) return found;
  }
}
const button = (tree, label) => find(tree, (node) => node.type === 'button' && node.props.children === label);
const tick = () => new Promise((done) => setImmediate(done));

function run(overrides = {}) {
  return { id: 'group', stage: 'planned', plan_revision: 1, planning_reasoning_effort: 'medium',
    tasks: [{ id: 'task', title: 'Update app' }], effort_control: {
      consistent: true, policy_revision: 1, selected_mode: 'balanced', pending_execution_mode: null,
      current_policy: null, can_select_plan: true, can_apply_plan: true, can_reserve: true, can_cancel_reservation: false,
    }, ...overrides };
}
function preview(mode = 'balanced') {
  return { mode, policy_revision: 1, plan_revision: 1, can_apply: true, requires_plan_review: true,
    planning_reasoning: null, unsupported_effects: [], tasks: [{ task_id: 'task', current_reasoning_effort: 'medium',
      reasoning: { reasoning_effort: 'medium', profile_source: 'manual' }, current_reviewer_agent_id: '',
      review: { required: true, policy_added: false }, reviewer_options: [] }] };
}

function harness(initialRun, request, extraProps = {}) {
  const path = join(output, 'renderer/src/EffortModePanel.js');
  const localRequire = createRequire(path);
  const slots = [];
  let cursor = 0;
  const hooks = {
    useEffect: () => {}, useId: () => 'effort-field',
    useRef(initial) { const index = cursor++; return slots[index] ||= { current: initial }; },
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = initial;
      return [slots[index], (value) => { slots[index] = typeof value === 'function' ? value(slots[index]) : value; }];
    },
  };
  const exports = {};
  let sequence = 0;
  runInNewContext(readFileSync(path, 'utf8'), { exports, crypto: { randomUUID: () => `request-${++sequence}` },
    window: { orchestrator: { request } }, require: (dependency) => dependency === 'react' ? hooks : localRequire(dependency) });
  const props = { projectName: 'project', run: initialRun, planDirty: false,
    onUpdated: (updated) => { props.run = updated; }, ...extraProps };
  const fixture = { props, render() { cursor = 0; return exports.EffortModePanel(props); } };
  button(fixture.render(), '강도 변경').props.onClick();
  return fixture;
}

test('opening and selecting a mode make no AI or RPC request', () => {
  const calls = [];
  const fixture = harness(run(), (...args) => calls.push(args));
  const input = find(fixture.render(), (node) => node.type === 'input' && node.props.value === 'economy');
  input.props.onChange();
  const markup = renderToStaticMarkup(fixture.render());
  assert.match(markup, /수동 설정·필수 리뷰·검증은 유지/);
  assert.equal(calls.length, 0);
  assert.equal(find(fixture.render(), (node) => node.type === 'input' && node.props.value === 'economy').props.checked, true);
});

test('selection saves only policy, then refreshes without applying or starting tasks', async () => {
  const calls = [];
  const original = run();
  const fixture = harness(original, async (method, params) => {
    calls.push([method, params]);
    return method === 'runs.get' ? run({ effort_control: { ...original.effort_control, selected_mode: 'economy', policy_revision: 2 } }) : {};
  });
  find(fixture.render(), (node) => node.type === 'input' && node.props.value === 'economy').props.onChange();
  button(fixture.render(), '선택 저장').props.onClick();
  await tick();
  assert.deepEqual(calls.map(([method]) => method), ['runs.setEffortMode', 'runs.get']);
  assert.equal(calls[0][1].target, 'planning');
  assert.equal(calls[0][1].expectedPolicyRevision, 1);
  assert.match(renderToStaticMarkup(fixture.render()), /선택을 저장했습니다/);
});

test('running policy remains distinct from reservation and duplicate clicks submit once', async () => {
  let finish;
  const calls = [];
  const original = run({ stage: 'executing' });
  original.effort_control = { ...original.effort_control, can_select_plan: false, can_apply_plan: false,
    current_policy: { mode: 'focused' }, current_binding_status: 'started' };
  const fixture = harness(original, async (method, params) => {
    calls.push([method, params]);
    if (method === 'runs.setEffortMode') return new Promise((done) => { finish = done; });
    return run({ ...original, effort_control: { ...original.effort_control, pending_execution_mode: 'balanced', can_cancel_reservation: true } });
  });
  const reserve = button(fixture.render(), '다음 실행에 예약');
  reserve.props.onClick(); reserve.props.onClick();
  assert.equal(calls.length, 1);
  assert.equal(calls[0][1].target, 'next_execution');
  finish({}); await tick();
  const markup = renderToStaticMarkup(fixture.render());
  assert.match(markup, /현재 실행.*집중/);
  assert.match(markup, /다음 실행 예약.*균형/);
  assert.equal(button(fixture.render(), '선택 저장'), undefined);
});

test('dirty or changed plans cannot apply even through a captured old button', async () => {
  const calls = [];
  const fixture = harness(run(), async (method, params) => { calls.push([method, params]); return preview(); });
  button(fixture.render(), '변경 비교').props.onClick(); await tick();
  const apply = button(fixture.render(), '계획에 반영');
  assert.equal(apply.props.disabled, false);
  assert.match(renderToStaticMarkup(fixture.render()), /수동 설정 유지/);
  fixture.props.planDirty = true;
  assert.equal(button(fixture.render(), '계획에 반영').props.disabled, true);
  apply.props.onClick(); await tick();
  assert.deepEqual(calls.map(([method]) => method), ['runs.previewEffortMode']);
  fixture.props.planDirty = false;
  fixture.props.run = run({ plan_revision: 2 }); fixture.render();
  apply.props.onClick(); await tick();
  assert.equal(calls.length, 1);
  assert.match(renderToStaticMarkup(fixture.render()), /변경 비교를 다시 확인/);
});

test('focused review requires explicit reviewer before plan application', async () => {
  const original = run(); original.effort_control.selected_mode = 'focused';
  const candidate = preview('focused');
  candidate.tasks[0].review = { policy_added: true };
  candidate.tasks[0].reviewer_options = [{ agent_id: 'reviewer', provider_id: 'local', model: '' }];
  const calls = [];
  const fixture = harness(original, async (method, params) => { calls.push([method, params]);
    return method === 'runs.previewEffortMode' ? candidate : method === 'runs.get' ? { ...original, plan_revision: 2, plan_approved_revision: 1 } : {}; });
  button(fixture.render(), '변경 비교').props.onClick(); await tick();
  assert.equal(button(fixture.render(), '계획에 반영').props.disabled, true);
  find(fixture.render(), (node) => node.type === 'select').props.onChange({ target: { value: 'reviewer' } });
  const apply = button(fixture.render(), '계획에 반영');
  assert.equal(apply.props.disabled, false);
  apply.props.onClick(); await tick();
  assert.deepEqual(calls.map(([method]) => method), ['runs.previewEffortMode', 'runs.applyEffortModeToPlan', 'runs.get']);
  assert.equal(calls[1][1].reviewerAgentIds.task, 'reviewer');
  assert.equal(calls[1][1].expectedPlanRevision, 1);
  assert.match(renderToStaticMarkup(fixture.render()), /계획을 확정하세요/);
});

test('same Codex review is a separate explicit choice and invalid options cannot apply', async () => {
  const original = run(); original.effort_control.selected_mode = 'focused';
  const candidate = preview('focused');
  candidate.tasks[0].reasoning.provider_id = 'codex';
  candidate.tasks[0].review = { policy_added: true };
  candidate.tasks[0].reviewer_options = [{ agent_id: 'worker', provider_id: 'codex', model: 'gpt-6.1-sol' }];
  const calls = [];
  const fixture = harness(original, async (method, params) => { calls.push([method, params]);
    return method === 'runs.previewEffortMode' ? candidate : original; });
  button(fixture.render(), '변경 비교').props.onClick(); await tick();
  assert.match(renderToStaticMarkup(fixture.render()), /별도 리뷰/);
  const select = find(fixture.render(), (node) => node.type === 'select');
  assert.equal(select.props.value, '');
  assert.equal(button(fixture.render(), '계획에 반영').props.disabled, true);
  select.props.onChange({ target: { value: 'not-a-current-option' } });
  const invalid = button(fixture.render(), '계획에 반영');
  assert.equal(invalid.props.disabled, true);
  invalid.props.onClick(); await tick();
  assert.deepEqual(calls.map(([method]) => method), ['runs.previewEffortMode']);
  select.props.onChange({ target: { value: 'worker' } });
  const apply = button(fixture.render(), '계획에 반영');
  assert.equal(apply.props.disabled, false);
  assert.equal(calls.length, 1);
  apply.props.onClick(); await tick();
  assert.deepEqual(calls.map(([method]) => method), ['runs.previewEffortMode', 'runs.applyEffortModeToPlan', 'runs.get']);
  assert.equal(calls[1][1].reviewerAgentIds.task, 'worker');
});

test('no reviewer candidates shows a direct explanation instead of an empty selector', async () => {
  const original = run(); original.effort_control.selected_mode = 'focused';
  const candidate = preview('focused');
  candidate.can_apply = false;
  candidate.tasks[0].review = { policy_added: true };
  candidate.unsupported_effects = ['task:reviewer_unavailable'];
  const calls = [];
  const fixture = harness(original, async (method) => { calls.push(method); return candidate; });
  button(fixture.render(), '변경 비교').props.onClick(); await tick();
  assert.equal(find(fixture.render(), (node) => node.type === 'select'), undefined);
  assert.match(renderToStaticMarkup(fixture.render()), /추가 가능한 리뷰 AI가 없습니다/);
  const apply = button(fixture.render(), '계획에 반영');
  assert.equal(apply.props.disabled, true);
  apply.props.onClick(); await tick();
  assert.deepEqual(calls, ['runs.previewEffortMode']);
});

test('lost mutation response checks persisted receipt without automatically resubmitting', async () => {
  const original = run();
  const calls = [];
  const fixture = harness(original, async (method) => {
    calls.push(method);
    if (method === 'runs.setEffortMode') throw new Error('response lost');
    return run({ effort_control: { ...original.effort_control, last_mutation: { request_id: 'request-1' } } });
  });
  button(fixture.render(), '다음 실행에 예약').props.onClick(); await tick();
  assert.deepEqual(calls, ['runs.setEffortMode', 'runs.get']);
  assert.match(renderToStaticMarkup(fixture.render()), /저장 기록을 확인했습니다/);
});

test('unknown and locked controls do not allow plan changes or assume balanced was saved', () => {
  const missing = harness(run({ effort_control: undefined }), () => assert.fail('no request'));
  assert.match(renderToStaticMarkup(missing.render()), /상태 확인 필요/);
  assert.equal(button(missing.render(), '변경 비교').props.disabled, true);
  const legacy = run(); legacy.effort_control.selected_mode = null;
  assert.match(renderToStaticMarkup(harness(legacy, () => {}).render()), /기존 작업 설정/);
});

test('draft mode is restored after navigation without changing persisted selection', () => {
  const saved = run();
  saved.tasks[0].profile_source = 'manual';
  const drafts = {};
  let fixture = harness(saved, () => assert.fail('no request'), { onDraftMode: (mode) => { drafts.projectGroup = mode; } });
  find(fixture.render(), (node) => node.type === 'input' && node.props.value === 'economy').props.onChange();
  fixture = harness(saved, () => assert.fail('no request'), { draftMode: drafts.projectGroup });
  assert.equal(find(fixture.render(), (node) => node.type === 'input' && node.props.value === 'economy').props.checked, true);
  const markup = renderToStaticMarkup(fixture.render());
  assert.match(markup, /작업 강도 · 균형/);
  assert.match(markup, /미저장 선택 · 절약/);
  assert.match(markup, /수동 설정 유지 · 작업 1개/);
});
