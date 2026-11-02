const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');
const { renderToStaticMarkup } = require('react-dom/server');

const root = resolve(__dirname, '../..');
const tempRoot = join(root, '.tmp');
mkdirSync(tempRoot, { recursive: true });
const output = mkdtempSync(join(tempRoot, 'conflict-panel-'));
process.on('exit', () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); });
const ts = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(ts), require(ts).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
  'desktop/renderer/src/ConflictResolutionPanel.tsx', 'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });

function fixture(extra = {}) {
  const conflict = { id: 'conflict-test', work_head: 'work-commit', main_head: 'main-commit', fingerprint: 'test-fingerprint',
    files: [{ path: 'example.txt', supported: true, kind: 'content', binary: false }], abort_status: 'verified', abort_error: '', error: '',
    resolution_status: 'candidate_ready', candidate: { id: 'candidate-test', revision: 2, summary: '양쪽 변경을 함께 유지합니다.' }, ...extra };
  const detail = { conflict, can_prepare: true, can_apply: true, attempts: [], selected_file: {
    path: 'example.txt', work: 'WORK-CODE', main: 'MAIN-CODE', candidate: 'CANDIDATE-CODE', candidate_state: 'ready' } };
  return { detail, props: { projectName: 'mock-project', run: { id: 'run-test', updated_at: 'v1', integration_conflict: conflict, recovery_tasks: [] }, onUpdated() {} } };
}

function operations(props, changes = {}) {
  return { projectName: props.projectName, runId: props.run.id, runUpdatedAt: props.run.updated_at,
    mainOperationsSignature: JSON.stringify(props.run.main_operations), status: 'ready', workspaces: [], checkedAt: 'check-1',
    lock: { run_id: props.run.id, state: 'unlocked', operation: '' }, ...changes };
}

// Pure React output and mocked RPC only; no backend, Git, AI or desktop app is started.
function harness(initialDetail, options = {}) {
  const file = join(output, 'renderer/src/ConflictResolutionPanel.js');
  const localRequire = createRequire(file); const exported = {};
  const slots = []; const effects = []; const calls = []; let index = 0; let detail = initialDetail; let failLookup = false;
  const cleanups = new Map(), intervals = new Map(), timeouts = new Map(); let timerId = 0, now = Date.now();
  class Clock extends Date { constructor(...args) { super(...(args.length ? args : [now])); } static now() { return now; } }
  const request = async (method, params) => {
    calls.push({ method, params, approved: false });
    if (method === 'providers.execution') return [{ agent_id: 'codex-general', model: 'gpt-6.1-sol', provider_id: 'codex', is_default: true, reasoning_efforts: ['medium'] }];
    if (method === 'runs.integrationConflict') {
      if (failLookup) throw new Error('RAW-LOOKUP-ERROR');
      return detail;
    }
    if (method === 'runs.prepareConflictResolution') {
      if (options.pendingMutation) return new Promise(() => {});
      detail = { ...detail, attempts: [{ request_id: params.requestId, action: 'conflict_resolution_prepare', status: 'succeeded', phase: 'candidate_ready' }] };
      return detail;
    }
    assert.fail(`unexpected request ${method}`);
  };
  const approve = async (method, params) => {
    calls.push({ method, params, approved: true });
    assert.equal(method, 'runs.applyConflictResolution');
    detail = { ...detail, conflict: { ...detail.conflict, resolution_status: 'applied' },
      attempts: [{ request_id: params.requestId, action: 'conflict_resolution_apply', status: 'succeeded', phase: 'succeeded' }] };
    return { id: 'run-test' };
  };
  runInNewContext(readFileSync(file, 'utf8'), { exports: exported,
    Date: Clock,
    crypto: { randomUUID: () => 'test-operation-id' },
    window: { orchestrator: { request, approve }, setInterval(callback) { intervals.set(++timerId, callback); return timerId; },
      clearInterval(id) { intervals.delete(id); }, setTimeout(callback) { timeouts.set(++timerId, callback); return timerId; },
      clearTimeout(id) { timeouts.delete(id); } },
    require(name) {
      if (name !== 'react') return localRequire(name);
      return { useState(initial) { const i = index++; if (!(i in slots)) slots[i] = initial;
        return [slots[i], (value) => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; }]; },
      useRef(initial) { const i = index++; if (!(i in slots)) slots[i] = { current: initial }; return slots[i]; },
      useMemo: (value) => value(),
      useEffect(effect, deps) { const i = index++; if (JSON.stringify(slots[i]) !== JSON.stringify(deps)) { slots[i] = deps;
        effects.push(() => { cleanups.get(i)?.(); cleanups.set(i, effect()); }); } } };
    } });
  const render = (props) => { index = 0; return exported.ConflictResolutionPanel(props); };
  return { render, calls, failLookup() { failLookup = true; },
    advance(ms) { now += ms; for (const callback of [...intervals.values()]) callback(); },
    poll() { for (const [id, callback] of [...timeouts]) { timeouts.delete(id); callback(); } },
    timers() { return intervals.size + timeouts.size; },
    async settle(props) { let tree = render(props); for (let i = 0; i < 3; i++) {
      while (effects.length) effects.shift()();
      await new Promise((resolve) => setImmediate(resolve)); tree = render(props);
    } return tree; } };
}

function elements(tree, predicate, found = []) {
  if (!tree || typeof tree !== 'object') return found;
  if (predicate(tree)) found.push(tree);
  for (const child of [tree.props?.children].flat(2)) elements(child, predicate, found);
  return found;
}

function visibleText(tree) {
  if (tree == null || typeof tree === 'boolean') return '';
  if (typeof tree === 'string' || typeof tree === 'number') return String(tree);
  if (Array.isArray(tree)) return tree.map(visibleText).join('');
  if (tree.type === 'details' && !tree.props.open) return visibleText(elements(tree, (item) => item.type === 'summary')[0]?.props.children);
  return visibleText(tree.props?.children);
}

const actions = (tree) => elements(tree, (item) => item.type === 'button' && item.props.className?.includes('button--'));

test('conflict panel leads with the resolution method and actions, while source and technical records stay closed', async () => {
  const { detail, props } = fixture(); const h = harness(detail);
  assert.ok(actions(h.render(props)).every((button) => button.props.disabled), 'no action before fresh detail is loaded');
  const tree = await h.settle(props); const visible = visibleText(tree);
  assert.match(visible, /Main 충돌 해결 · 1개 파일/); assert.match(visible, /해결안 확인 후 적용/);
  assert.doesNotMatch(visible, /example.txt|WORK-CODE|MAIN-CODE|CANDIDATE-CODE|work-commit|main-commit|gpt-6.1-sol/);
  const full = renderToStaticMarkup(tree);
  for (const text of ['example.txt', 'WORK-CODE', 'MAIN-CODE', 'CANDIDATE-CODE', 'work-commit', 'gpt-6.1-sol']) assert.ok(full.includes(text));
  assert.ok(elements(tree, (item) => item.type === 'details' && item.props.className === 'conflict-resolution__details')
    .every((item) => !item.props.open));
  assert.ok(full.indexOf('해결안 적용 후 재검증') < full.indexOf('파일별 코드 비교'));
  assert.equal(actions(tree)[1].props.disabled, false);
  assert.ok(h.calls.every((call) => !call.approved && ['providers.execution', 'runs.integrationConflict'].includes(call.method)));
});

test('applied but failed verification remains visible and the complete failed command and log remain available', async () => {
  const { detail, props } = fixture({ resolution_status: 'applied', error: 'RAW-VERIFY-ERROR: dotnet build Example.sln' });
  detail.can_apply = false;
  detail.attempts = [{ request_id: 'failed-attempt', action: 'conflict_resolution_apply', status: 'failed', phase: 'verification_failed',
    error: 'RAW-VERIFY-ERROR', log: 'FULL-PROVIDER-LOG' }];
  const tree = await harness(detail).settle(props); const visible = visibleText(tree);
  assert.match(visible, /해결안 적용됨 · 검증 실패/); assert.match(visible, /다시 검증/);
  assert.doesNotMatch(visible, /RAW-VERIFY|dotnet build|FULL-PROVIDER-LOG|충돌 해결·검증 완료/);
  const full = renderToStaticMarkup(tree); assert.match(full, /RAW-VERIFY-ERROR/); assert.match(full, /FULL-PROVIDER-LOG/);
  assert.equal(actions(tree)[1].props.disabled, true);
});

test('existing guards still block requests during work, stale detail, history and lookup failure', async () => {
  for (const status of ['generating', 'applying']) {
    const { detail, props } = fixture({ resolution_status: status });
    const tree = await harness(detail).settle(props);
    assert.ok(actions(tree).filter((button) => visibleText(button) !== '상태 다시 확인').every((button) => button.props.disabled));
  }
  const { detail, props } = fixture(); const h = harness(detail); await h.settle(props);
  assert.ok(actions(h.render({ ...props, run: { ...props.run, updated_at: 'v2' } })).every((button) => button.props.disabled));
  h.failLookup(); const failed = await h.settle({ ...props, run: { ...props.run, updated_at: 'v2' } });
  assert.match(visibleText(failed), /최신 상태를 확인하지 못했습니다/);
  assert.ok(actions(failed).filter((button) => button.props.children !== '상태 다시 확인').every((button) => button.props.disabled));
  assert.doesNotMatch(visibleText(failed), /RAW-LOOKUP-ERROR/); assert.match(renderToStaticMarkup(failed), /RAW-LOOKUP-ERROR/);
  const historicalProps = { ...props, recoveryTaskId: 'old-task', run: { ...props.run,
    recovery_tasks: [{ id: 'old-task', conflict: detail.conflict, superseded_by: 'new-task' }] } };
  const historical = await harness(detail).settle(historicalProps);
  assert.match(visibleText(historical), /이전 해결 기록/); assert.ok(actions(historical).every((button) => button.props.disabled));
});

test('summary actions preserve explicit generation requests and approval before apply without auto-running either', async () => {
  for (const kind of ['prepare', 'apply']) {
    const { detail, props } = fixture(); let refreshed = 0; props.onUpdated = () => refreshed++;
    const h = harness(detail); const tree = await h.settle(props);
    actions(tree)[kind === 'prepare' ? 0 : 1].props.onClick();
    await h.settle(props);
    const mutation = h.calls.find((call) => call.method === (kind === 'prepare' ? 'runs.prepareConflictResolution' : 'runs.applyConflictResolution'));
    assert.ok(mutation); assert.equal(mutation.approved, kind === 'apply');
    assert.equal(mutation.params.projectName, 'mock-project'); assert.equal(mutation.params.runId, 'run-test');
    assert.equal(mutation.params.conflictId, 'conflict-test'); assert.equal(mutation.params.fingerprint, 'test-fingerprint');
    assert.equal(mutation.params.requestId, 'test-operation-id');
    if (kind === 'apply') { assert.equal(mutation.params.candidateId, 'candidate-test'); assert.equal(mutation.params.candidateRevision, 2); }
    else assert.equal(mutation.params.model, 'gpt-6.1-sol');
    assert.equal(refreshed, 1);
  }
});

test('an hours-old running record is unconfirmed without a live lock and refresh never requests AI', async () => {
  const { detail, props } = fixture({ resolution_status: 'applied' }); detail.can_apply = false;
  detail.attempts = [{ request_id: 'old-request', action: 'conflict_resolution_apply', status: 'running', phase: 'verifying',
    created_at: new Date(Date.now() - 264 * 60000).toISOString() }];
  props.operationsSnapshot = operations(props); let refreshed = 0; props.onUpdated = () => refreshed++;
  const h = harness(detail); let tree = await h.settle(props);
  assert.match(visibleText(tree), /현재 실행 여부 확인 필요/);
  assert.match(visibleText(tree), /마지막 기록: 전체 검증 중/);
  assert.doesNotMatch(visibleText(tree), /264분|경과|60초 동안/);
  assert.equal(elements(tree, item => item.props?.className === 'spin').length, 0);
  assert.equal(h.timers(), 0, 'stored running metadata cannot keep timers or polling alive');
  actions(tree).find(button => visibleText(button) === '상태 다시 확인').props.onClick();
  tree = await h.settle(props); assert.equal(refreshed, 1);
  h.advance(60000); h.poll(); await h.settle(props);
  assert.ok(h.calls.every(call => ['providers.execution', 'runs.integrationConflict'].includes(call.method)));
  assert.equal(h.timers(), 0);
});

test('fresh unlocked applied resolution offers only the existing verify callback with no reapply or Main action', async () => {
  const { detail, props } = fixture({ resolution_status: 'applied' }); detail.can_apply = false;
  detail.attempts = [{ request_id: 'old', action: 'conflict_resolution_apply', status: 'running', phase: 'verifying' }];
  let verified = 0; props.onVerify = () => verified++;
  props.run.integration_control = { can_verify: true }; props.operationsSnapshot = operations(props);
  const h = harness(detail), tree = await h.settle(props);
  const retry = actions(tree).find(button => visibleText(button) === '결과 다시 검사');
  assert.ok(retry); assert.equal(retry.props.disabled, false); assert.equal(verified, 0);
  assert.doesNotMatch(visibleText(tree), /해결안 적용 후 재검증/);
  retry.props.onClick(); assert.equal(verified, 1);
  assert.ok(h.calls.every(call => !call.approved && ['providers.execution', 'runs.integrationConflict'].includes(call.method)));
});

test('verify-only action preserves stale, foreign, active, historical, dirty, permission and lookup guards', async () => {
  const setup = () => { const value = fixture({ resolution_status: 'applied' });
    value.props.run.integration_control = { can_verify: true }; value.props.onVerify = () => assert.fail('no automatic verification');
    value.props.operationsSnapshot = operations(value.props); return value; };
  for (const change of [p => { p.operationsSnapshot.runUpdatedAt = 'old'; }, p => { p.operationsSnapshot.status = 'loading'; },
    p => { p.operationsSnapshot.projectName = 'foreign'; }, p => { p.operationsSnapshot.runId = 'foreign'; },
    p => { p.operationsSnapshot.lock.run_id = 'foreign'; }, p => { p.operationsSnapshot.lock.state = 'unknown'; },
    p => { p.operationsSnapshot.lock = { run_id: p.run.id, state: 'active', operation: 'execute' }; },
    p => { p.run.integration_control.can_verify = false; }, p => { p.verifyDisabled = true; },
    p => { p.recoveryTaskId = 'old'; p.run.recovery_tasks = [{ id: 'old', conflict: p.run.integration_conflict, superseded_by: 'new' }]; }]) {
    const { detail, props } = setup(); change(props); const h = harness(detail);
    assert.ok(actions(h.render(props)).find(button => visibleText(button) === '결과 다시 검사').props.disabled);
    const tree = await h.settle(props);
    assert.ok(actions(tree).find(button => visibleText(button) === '결과 다시 검사').props.disabled);
  }
  const { detail, props } = setup(); const h = harness(detail); h.failLookup();
  assert.ok(actions(await h.settle(props)).find(button => visibleText(button) === '결과 다시 검사').props.disabled);
});

test('live verification uses the parent progress card while conflict preparation polling remains read-only', async () => {
  for (const phase of ['verify', 'conflict-resolution-prepare', 'conflict-resolution-apply']) {
    const { detail, props } = fixture({ resolution_status: phase === 'verify' ? 'applied' : 'generating', error: 'OLD-FAILURE' });
    detail.attempts = [{ request_id: 'old', action: 'conflict_resolution_apply', status: 'running', phase: 'verifying' }];
    props.run.active_step = 'verify';
    props.operationsSnapshot = operations(props, { lock: { run_id: props.run.id, state: 'active', operation: phase } });
    const h = harness(detail); let tree = await h.settle(props);
    assert.doesNotMatch(visibleText(tree), /검증 확인 필요|현재 실행 여부 확인 필요|처리 중 오류가 발생/);
    assert.equal(elements(tree, item => item.props?.className === 'conflict-operation-progress').length, phase === 'verify' ? 0 : 1);
    assert.equal(elements(tree, item => item.props?.className === 'conflict-resolution__summary').length, phase === 'verify' ? 1 : 0,
      'the same live phase is not repeated in a separate summary');
    for (let i = 0; i < 3; i++) { h.advance(120000); h.poll(); tree = await h.settle(props); }
    assert.ok(h.calls.filter(call => call.method === 'runs.integrationConflict').length >= 4);
    assert.ok(h.calls.every(call => ['providers.execution', 'runs.integrationConflict'].includes(call.method)));
    assert.doesNotMatch(visibleText(tree), /60초 동안|현재 실행 여부 확인 필요/);
    assert.ok(actions(tree).every(button => button.props.disabled));
  }
});

test('a local request with no live execution proof stops waiting timers after sixty seconds without retrying AI', async () => {
  const { detail, props } = fixture(); props.operationsSnapshot = operations(props);
  const h = harness(detail, { pendingMutation: true }); let tree = await h.settle(props);
  actions(tree)[0].props.onClick(); tree = await h.settle(props);
  assert.match(visibleText(tree), /요청 시작 확인 중/); assert.ok(h.timers() > 0);
  h.advance(60000); tree = await h.settle(props);
  assert.match(visibleText(tree), /현재 실행 여부 확인 필요/);
  assert.equal(h.timers(), 0); assert.doesNotMatch(visibleText(tree), /60초 경과/);
  assert.equal(elements(tree, item => item.props?.className === 'spin').length, 0);
  for (let i = 0; i < 3; i++) { h.advance(60000); h.poll(); await h.settle(props); }
  assert.equal(h.calls.filter(call => call.method === 'runs.prepareConflictResolution').length, 1);
  assert.equal(h.calls.filter(call => call.approved).length, 0);
});

test('a successful fresh verification supersedes a stale conflict operation without rewriting its history', async () => {
  const { detail, props } = fixture({ resolution_status: 'applied', error: 'OLD-FAILURE' });
  detail.attempts = [{ request_id: 'old', action: 'conflict_resolution_apply', status: 'running', phase: 'verifying' }];
  props.onVerify = () => assert.fail('rendering the completed resolution cannot start another verification');
  props.run.integration_control = { status: 'verified', can_verify: true, verified_main_head: 'main', current_main_head: 'main',
    verified_integration_head: 'candidate', current_integration_head: 'candidate' };
  props.operationsSnapshot = operations(props);
  const h = harness(detail); const tree = await h.settle(props);
  assert.match(visibleText(tree), /충돌 해결·검증 완료/);
  assert.match(visibleText(tree), /위쪽.*반영/);
  assert.equal(actions(tree).length, 0, 'completed conflict does not keep regeneration or redundant verification controls');
  assert.doesNotMatch(visibleText(tree), /현재 실행 여부 확인 필요|처리 중 오류가 발생/);
  assert.equal(h.timers(), 0); assert.equal(detail.attempts[0].status, 'running');
  const changed = { ...props, run: { ...props.run, integration_control: { ...props.run.integration_control, current_integration_head: 'changed' } } };
  const stale = await harness(detail).settle(changed);
  assert.match(visibleText(stale), /현재 실행 여부 확인 필요/);
  assert.equal(actions(stale).find(button => visibleText(button) === '결과 다시 검사').props.disabled, false);
});

test('an active verification cannot claim an unresolved candidate was applied', async () => {
  const { detail, props } = fixture({ resolution_status: 'unresolved' });
  props.run.active_step = 'verify';
  props.operationsSnapshot = operations(props, { lock: { run_id: props.run.id, state: 'active', operation: 'verify' } });
  const tree = await harness(detail).settle(props);
  assert.match(visibleText(tree), /결과 검사 중/); assert.doesNotMatch(visibleText(tree), /해결안 적용됨/);
});
