const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');
const { renderToStaticMarkup } = require('react-dom/server');
const root = resolve(__dirname, '../..'), temp = join(root, '.tmp');
mkdirSync(temp, { recursive: true });
const output = mkdtempSync(join(temp, 'provider-capacity-feedback-'));
process.on('exit', () => { assert.equal(dirname(output), temp); rmSync(output, { recursive: true, force: true }); });
const pkg = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(pkg), require(pkg).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
  'desktop/renderer/src/RecoveryDialog.tsx',
  'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });
const modulePath = name => join(output, 'renderer/src', name);
const failure = require(modulePath('providerFailure.js'));
const recovery = require(modulePath('recoveryOperation.js'));
const capacity = 'agent codex-general Codex SDK failed: Selected model is at capacity. Please try a different model.; see mock.log';
const rateLimit = 'exceeded retry limit, last status: 429 Too Many Requests';
const usageLimit = `${rateLimit}; {"error":{"code":"insufficient_quota"}}`;
const now = Date.parse('2026-10-13T08:00:00Z');
const operation = overrides => ({ request_id: 'saved-request', run_id: 'run', action: 'recovery_apply', digest: '',
  phase: 'replanning', status: 'running', error: '', error_code: '', result_commit: '', result_ref: '', result_revision: 0,
  resume_request_id: '', lock_state: 'active', created_at: '2026-10-13T07:57:00Z', updated_at: '2026-10-13T07:59:00Z',
  finished_at: '', result: null, ...overrides });
const partial = () => operation({ status: 'partial', error: capacity, error_code: 'replanning_failed', lock_state: 'unlocked',
  result_commit: 'kept-commit', result: { fingerprint: 'same-fingerprint', source_ids: ['source'], result_commit: 'kept-commit' } });
const task = () => ({ id: 'task', title: '실패 작업', status: 'failed', error: capacity });
const run = tasks => ({ id: 'run', stage: 'failed', failed_step: 'agent_execution', tasks });
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  return Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)];
}
function text(tree) {
  if (typeof tree === 'string' || typeof tree === 'number') return String(tree);
  return Array.isArray(tree) ? tree.map(text).join('') : text(tree?.props?.children || '');
}
function mount(api) {
  const file = modulePath('RecoveryDialog.js'), local = createRequire(file), result = {};
  const states = [], refs = [], deps = [], cleanups = [], effects = [];
  let index = 0, refIndex = 0, effectIndex = 0, request = 0, applied = 0, closed = 0, writes = 0;
  const props = { projectName: 'mock', runId: 'run', runTitle: '모의 그룹', onApplied() { applied++; }, onClose() { closed++; } };
  runInNewContext(readFileSync(file, 'utf8'), {
    exports: result, Date: class extends Date { constructor(...args) { super(...(args.length ? args : [now])); } static now() { return now; } },
    crypto: { randomUUID: () => `new-${++request}` },
    window: { orchestrator: api, setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {} },
    require(name) {
      if (name !== 'react') return local(name);
      return {
        useState(initial) {
          const i = index++;
          if (!(i in states)) states[i] = typeof initial === 'function' ? initial() : initial;
          return [states[i], value => { writes++; states[i] = typeof value === 'function' ? value(states[i]) : value; }];
        },
        useRef(initial) { const i = refIndex++; return refs[i] ||= { current: initial }; },
        useMemo(callback) { return callback(); },
        useEffect(callback, values) {
          const i = effectIndex++, previous = deps[i];
          if (!previous || values.some((value, n) => !Object.is(value, previous[n]))) {
            deps[i] = values; effects.push(() => { cleanups[i]?.(); cleanups[i] = callback(); });
          }
        },
      };
    },
  });
  let tree;
  const render = () => { index = refIndex = effectIndex = 0; tree = result.RecoveryDialog(props); return tree; };
  const settle = async () => { for (let i = 0; i < 16; i++) { render(); effects.splice(0).forEach(fn => fn()); await Promise.resolve(); } return tree; };
  return { settle, render, html: () => renderToStaticMarkup(tree), states,
    button: label => nodes(tree).find(node => node.type === 'button' && text(node) === label),
    unmount: () => cleanups.forEach(fn => fn?.()), writes: () => writes, applied: () => applied, closed: () => closed };
}





test('confirmed SDK service failure has its own short final guidance', () => {
  assert.equal(failure.providerFailurePresentation('AI 서버가 일시적으로 응답하지 않습니다. upstream').kind,'unavailable');
  assert.equal(failure.providerFailurePresentation('HTTP 503'),undefined);
});

test('capacity requires confirmed specific evidence, preserving HTTP/quota/auth/schema/local allocation failures', () => {
  assert.equal(failure.isModelCapacityFailure(capacity), true);
  assert.equal(failure.isModelCapacityFailure('선택한 AI 모델이 혼잡합니다. upstream detail'), true);
  for (const error of ['HTTP 503', 'agent capacity exhausted', 'not enough codex agent capacity', 'usageLimitExceeded', 'unauthorized', 'invalid schema']) {
    assert.equal(failure.isModelCapacityFailure(error), false, error);
  }
  for (const status of ['running', 'interrupted', 'succeeded']) {
    assert.ok(!recovery.recoveryPhaseLabel(operation({ status, error: capacity })).includes('혼잡'));
  }
  assert.equal(recovery.recoveryPhaseLabel(partial()), '통합 결과 보존 · AI 모델 혼잡으로 재계획 실패');
});



test('request limit presentation distinguishes confirmed usage limits and avoids unrelated HTTP failures', () => {
  for (const error of [rateLimit, `agent codex-general Codex SDK failed: HTTP 429; see mock.log`,
    'AI 요청이 제한되었습니다. upstream detail', 'rateLimitExceeded', '{"error":{"code":"slow_down"}}']) {
    assert.equal(failure.providerFailurePresentation(error).kind, 'rate');
  }
  for (const error of [usageLimit, 'usageLimitExceeded', "You've hit your usage limit", 'You exceeded your current quota',
    'AI 사용 한도에 도달했습니다. upstream detail', 'credit_balance_exhausted', 'project_spend_limit_exceeded',
    'organization_usage_limit_exceeded', 'organization_spend_limit_exceeded']) {
    const presentation = failure.providerFailurePresentation(error);
    assert.equal(presentation.kind, 'usage');
    assert.doesNotMatch(presentation.description, /잠시 후/);
  }
  for (const error of ['HTTP 503', 'HTTP 429', 'test failed: expected HTTP 429', 'schema invalid at line 429',
    'exceeded retry limit, last status: 500', 'exceeded retry limit, last status: 4290', 'unauthorized',
    'sessionBudgetExceeded', 'not enough codex agent capacity']) {
    assert.equal(failure.providerFailurePresentation(error), undefined, error);
  }
});

for (const [error, label, title] of [[rateLimit, 'AI 요청 제한', 'AI 요청이 제한되었습니다'],
  [usageLimit, 'AI 사용 한도', 'AI 사용 한도에 도달했습니다']]) {


  test(`${label}: confirmed partial preserves integration and only explicit approved replan can retry`, async () => {
    const calls = [], current = { ...partial(), error };
    const h = mount({ async request(method) { calls.push(method); return current; },
      async approve(method, params) { calls.push({ method, params }); return undefined; } });
    await h.settle();
    assert.match(h.html(), new RegExp(`통합 결과 보존 · ${label}로 재계획 실패`));
    assert.match(h.html(), /kept-commit/);
    assert.ok(h.html().includes('오류 상세'));
    assert.ok(calls.every(call => call === 'operations.latest'));
    h.button('작업 재계획 다시 시도').props.onClick(); await h.settle();
    const approval = calls.find(call => call.method === 'runs.applyRecovery');
    assert.equal(approval.params.resumeRequestId, 'saved-request');
    assert.equal(approval.params.fingerprint, 'same-fingerprint');
    assert.equal(h.applied(), 0);
  });

  test(`${label}: running, interrupted and succeeded operations do not diagnose stale errors`, async () => {
    for (const status of ['running', 'interrupted', 'succeeded']) {
      assert.ok(!recovery.recoveryPhaseLabel(operation({ status, error })).includes(label));
    }
    const calls = [];
    const h = mount({ async request(method) { calls.push(method); return operation({ error }); } });
    await h.settle();
    assert.match(h.html(), /남은 작업 재계획 중/);
    assert.ok(!h.html().includes(title));
    assert.equal(h.button('복구안 다시 조회').props.disabled, true);
    assert.ok(calls.every(call => call === 'operations.latest'));
  });

  test(`${label}: confirmed failure shows guidance and keeps the raw error under details`, async () => {
    const h = mount({ async request() { return operation({ status: 'failed', lock_state: 'unlocked', error }); } });
    const tree = await h.settle();
    assert.match(h.html(), new RegExp(title));
    assert.ok(nodes(tree).some(node => node.type === 'details' && text(node).includes(error)));
    assert.equal(h.button('복구안 다시 조회').props.disabled, false);
    assert.equal(h.applied(), 0);
  });
}

test('confirmed partial recovery keeps commit and retries only by the same resumeRequestId with explicit approval', async () => {
  const calls = [];
  const h = mount({ async request(method) { calls.push(method); return partial(); },
    async approve(method, params) { calls.push({ method, params }); return undefined; } });
  await h.settle();
  assert.match(h.html(), /통합 결과 보존 · AI 모델 혼잡으로 재계획 실패/);
  assert.match(h.html(), /kept-commit/); assert.match(h.html(), /오류 상세/);
  assert.ok(calls.every(call => call === 'operations.latest'));
  assert.equal(h.button('작업 재계획 다시 시도').props.disabled, false);
  h.button('작업 재계획 다시 시도').props.onClick(); await h.settle();
  const approved = calls.find(call => call.method === 'runs.applyRecovery');
  assert.equal(approved.params.resumeRequestId, 'saved-request');
  assert.equal(approved.params.fingerprint, 'same-fingerprint');
  assert.deepEqual(Array.from(approved.params.sourceIds), ['source']);
  assert.equal(calls.filter(call => call.method).length, 1);
  assert.equal(h.applied(), 0);
});

test('running recovery retains actual phase and lock, then read-only refresh accepts confirmed partial result', async () => {
  const calls = [];
  const h = mount({ async request(method) { calls.push(method); return method === 'operations.get' ? partial() : operation({ error: capacity }); } });
  await h.settle();
  assert.match(h.html(), /남은 작업 재계획 중/);
  assert.match(h.html(), /최근 단계 갱신 60초 전/);
  assert.doesNotMatch(h.html(), /AI 모델 혼잡|Selected model|마지막 상태 보고/);
  assert.equal(h.button('복구안 다시 조회').props.disabled, true);
  h.button('복구 상태 다시 확인').props.onClick(); await h.settle();
  assert.match(h.html(), /통합 결과 보존 · AI 모델 혼잡으로 재계획 실패/);
  assert.ok(calls.every(call => ['operations.latest', 'operations.get'].includes(call)));
});

test('initial in-flight history lookup prevents duplicate requests before any response', async () => {
  const releases = [], calls = [];
  const h = mount({ request(method) { calls.push(method); return new Promise(resolve => releases.push(resolve)); } });
  await h.settle();
  assert.match(h.html(), /이전 복구 상태 확인 중/);
  assert.equal(h.button('복구안 다시 조회').props.disabled, true);
  assert.equal(h.button('복구안 확인 필요').props.disabled, true);
  assert.deepEqual(calls, ['operations.latest', 'operations.latest']);
  releases.forEach(resolve => resolve(partial())); await h.settle();
  assert.equal(h.button('작업 재계획 다시 시도').props.disabled, false);
});

test('initial history lookup failure prevents duplicate requests and offers read-only reconciliation', async () => {
  let failed = true; const calls = [];
  const h = mount({ async request(method) { calls.push(method); if (failed) throw new Error('lookup unavailable'); return partial(); } });
  await h.settle();
  assert.match(h.html(), /이전 복구 결과 확인 필요/);
  assert.doesNotMatch(h.html(), /복구 요청을 완료하지 못했습니다/);
  assert.equal(h.button('복구안 다시 조회').props.disabled, true);
  assert.equal(h.button('복구안 확인 필요').props.disabled, true);
  assert.deepEqual(calls, ['operations.latest', 'operations.latest']);
  failed = false; h.button('이전 복구 상태 다시 확인').props.onClick(); await h.settle();
  assert.equal(h.button('작업 재계획 다시 시도').props.disabled, false);
  assert.ok(calls.every(method => method === 'operations.latest'));
});

test('RPC failure plus unknown final state is kept unconfirmed without model diagnosis or duplicate retry', async () => {
  const calls = [];
  const h = mount({ async request(method) {
    calls.push(method); if (method === 'operations.latest') return null;
    throw new Error(method === 'runs.recoveryPlan' ? capacity : 'read failed');
  } });
  await h.settle();
  assert.match(h.html(), /복구 결과 확인 중입니다/); assert.match(h.html(), /최종 상태를 확인하지 못했습니다/);
  assert.doesNotMatch(h.html(), /복구 요청을 완료하지 못했습니다/);
  assert.equal(h.button('복구안 다시 조회').props.disabled, true);
  assert.equal(calls.filter(method => method === 'runs.recoveryPlan').length, 1);
  const alerts = nodes(h.render()).filter(node => node.props?.role === 'alert').map(text).join('');
  assert.ok(!alerts.includes(failure.modelCapacityMessage));
  assert.equal(h.button('잠금 해제 후 다시 조회'), undefined);
});

test('late failed operation lookup after dialog closes cannot update state or request approval', async () => {
  let release; const calls = [];
  const h = mount({ async request(method) {
    calls.push(method); if (method === 'operations.latest') return null;
    if (method === 'runs.recoveryPlan') throw new Error(capacity);
    return new Promise(resolve => { release = resolve; });
  } });
  await h.settle(); assert.equal(typeof release, 'function');
  h.unmount(); const writes = h.writes(); release(partial());
  for (let i = 0; i < 5; i++) await Promise.resolve();
  assert.equal(h.writes(), writes); assert.equal(h.applied(), 0); assert.equal(h.closed(), 0);
  assert.ok(calls.every(method => ['operations.latest', 'operations.get', 'runs.recoveryPlan'].includes(method)));
});

test('late apply completion after close cannot update the group or close another dialog', async () => {
  let release;
  const h = mount({ async request() { return partial(); },
    approve() { return new Promise(resolve => { release = resolve; }); } });
  await h.settle(); h.button('작업 재계획 다시 시도').props.onClick(); await h.settle();
  h.unmount(); const writes = h.writes(); release(run([task({})]));
  for (let i = 0; i < 5; i++) await Promise.resolve();
  assert.equal(h.writes(), writes); assert.equal(h.applied(), 0); assert.equal(h.closed(), 0);
});

test('confirmed final success refreshes the group once with no additional apply request', async () => {
  const calls = [];
  const h = mount({ async request(method) {
    calls.push(method); return method === 'runs.get' ? run([task({ status: 'completed' })])
      : operation({ status: 'succeeded', phase: 'completed', error: '' });
  } });
  await h.settle(); await h.settle();
  assert.equal(h.applied(), 1); assert.equal(h.closed(), 1);
  assert.equal(calls.filter(method => method === 'runs.get').length, 1);
  assert.ok(calls.every(method => ['operations.latest', 'runs.get'].includes(method)));
});

test('successful reconciliation clears the old unknown-result warning while group state is still loading', async () => {
  let succeeded = false, releaseGroup;
  const h = mount({ async request(method, params) {
    if (method === 'operations.latest') return partial();
    if (method === 'operations.get') {
      if (!succeeded) throw new Error('query unavailable');
      return operation({ request_id: params.requestId, status: 'succeeded', phase: 'completed', error: '' });
    }
    return new Promise(resolve => { releaseGroup = resolve; });
  }, async approve() { throw new Error(capacity); } });
  await h.settle(); h.button('작업 재계획 다시 시도').props.onClick(); await h.settle();
  assert.match(h.html(), /복구 결과 확인 중입니다/);
  h.states[8] = now + 65000; h.render(); succeeded = true;
  h.button('복구 상태 다시 확인').props.onClick(); await h.settle();
  assert.match(h.html(), /복구 적용 완료 · 그룹 상태 확인 중/);
  assert.doesNotMatch(h.html(), /복구 결과 확인 중입니다|복구 요청을 완료하지 못했습니다/);
  assert.equal(h.applied(), 0); releaseGroup(run([task({ status: 'completed' })]));
  await h.settle(); assert.equal(h.applied(), 1); assert.equal(h.closed(), 1);
});
