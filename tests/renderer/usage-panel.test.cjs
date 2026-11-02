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
const output = resolve(mkdtempSync(join(tempRoot, 'usage-panel-')));
const cleanup = () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); };
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  execFileSync(process.execPath, [resolve(dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig',
    '--strict', '--target', 'ES2022', '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/UsagePanel.tsx', 'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const tick = () => new Promise((done) => setImmediate(done));
function find(element, predicate) {
  if (!element || typeof element !== 'object') return undefined;
  if (predicate(element)) return element;
  const children = element.props?.children;
  for (const child of Array.isArray(children) ? children.flat() : [children]) {
    const found = find(child, predicate); if (found) return found;
  }
}
const button = (tree, text) => find(tree, (node) => node.type === 'button' && node.props.children === text);
function summary(total = null, extra = {}) {
  return { input_tokens: total, output_tokens: total === null ? null : 0, total_tokens: total,
    cached_input_tokens: null, cache_write_input_tokens: null, reasoning_output_tokens: null,
    call_count: 1, reported_call_count: total === null ? 0 : 1, complete_call_count: total === null ? 0 : 1,
    running_call_count: 0, coverage: total === null ? 'unavailable' : 'complete', latest_observed_at: '', ...extra };
}
function snapshot(total = null, extra = {}) {
  return { history_scope: 'recorded_calls', recording_started_at: '2026-10-01T00:00:00+00:00',
    summary: summary(total), execution_summary: summary(), execution_is_active: false, by_mode: [], by_purpose: [], execution_request_id: '',
    execution_requests: [], records: [], next_cursor: '', ...extra };
}
function row(id) {
  return { invocation_id: id, purpose: 'execute', task_id: 'task', outcome: 'failed', total_tokens: 12,
    input_tokens: 10, output_tokens: 2, cached_input_tokens: null, cache_write_input_tokens: null, reasoning_output_tokens: null,
    coverage: 'partial', provider: 'codex', model_requested: 'gpt-6.1-sol', model_effective: 'gpt-effective', mode: 'economy',
    missing_reason: '', created_at: '2026-10-01T00:00:00+00:00' };
}

function harness(request, initial = {}) {
  const path = join(output, 'renderer/src/UsagePanel.js');
  const localRequire = createRequire(path);
  const slots = []; const cleanups = new Map(); const timers = new Map();
  let cursor = 0; let effects = []; let nextTimer = 0;
  const hooks = {
    useId: () => 'usage-detail',
    useEffect(action, deps) {
      const index = cursor++;
      if (!slots[index] || deps.some((value, position) => value !== slots[index][position])) {
        effects.push(() => { cleanups.get(index)?.(); cleanups.set(index, action()); }); slots[index] = deps;
      }
    },
    useRef(initial) { const index = cursor++; return slots[index] ||= { current: initial }; },
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial;
      return [slots[index], (value) => { slots[index] = typeof value === 'function' ? value(slots[index]) : value; }];
    },
  };
  const exports = {};
  runInNewContext(readFileSync(path, 'utf8'), { exports, window: { orchestrator: { request },
    setInterval: (fn) => { timers.set(++nextTimer, fn); return nextTimer; }, clearInterval: (id) => timers.delete(id) },
    require: (dependency) => dependency === 'react' ? hooks : localRequire(dependency) });
  const props = { projectName: 'project', runId: 'group', running: false, refreshKey: 'reviewed', ...initial };
  return { props, timers, amount: exports.usageAmount,
    render() { cursor = 0; effects = []; return exports.UsagePanel(props); },
    commit() { effects.forEach((action) => action()); effects = []; },
    unmount() { cleanups.forEach((cleanup) => cleanup?.()); },
  };
}

test('unavailable, zero, partial and no-call amounts are distinct', () => {
  const fixture = harness(async () => snapshot());
  assert.equal(fixture.amount(summary()), '사용량 미제공');
  assert.equal(fixture.amount(summary(0)), '0토큰 · 집계 완료');
  assert.match(fixture.amount(summary(120, { coverage: 'partial' })), /현재 보고량 120토큰 · 일부 미집계/);
  assert.equal(fixture.amount(summary(null, { call_count: 0 })), '기록된 AI 호출이 없습니다');
});

test('summary and failed-call detail use only the read-only endpoint', async () => {
  const calls = [];
  const fixture = harness(async (method, params) => { calls.push([method, params]); return snapshot(12, { records: [row('one')] }); });
  fixture.render(); fixture.commit(); await tick();
  let tree = fixture.render();
  button(tree, '사용량 상세').props.onClick();
  tree = fixture.render(); fixture.commit(); await tick();
  const markup = renderToStaticMarkup(fixture.render());
  assert.match(markup, /그룹 전체 기록/); assert.match(markup, /실패.*12토큰/);
  assert.match(markup, /실제 gpt-effective/); assert.match(markup, /모드|절약/);
  assert.match(markup, /이후 기록된 호출만 집계/); assert.match(markup, /캐시·추론 토큰/);
  assert.equal(calls.length, 1); assert.equal(calls[0][0], 'runs.usage');
  assert.equal(find(tree, (node) => node.props?.id === 'usage-detail-details').props.hidden, false);
});

test('paging preserves aggregate totals and execution filter clears old rows', async () => {
  const calls = [];
  const fixture = harness(async (method, params) => {
    calls.push(params);
    return snapshot(100, { execution_requests: ['execution'], records: [row(params.executionRequestId ? 'filtered' : params.cursor ? 'two' : 'one')],
      next_cursor: params.cursor || params.executionRequestId ? '' : 'cursor' });
  });
  fixture.render(); fixture.commit(); await tick();
  button(fixture.render(), '사용량 상세').props.onClick(); fixture.render(); fixture.commit();
  button(fixture.render(), '이전 호출 더 보기').props.onClick(); await tick();
  let markup = renderToStaticMarkup(fixture.render());
  assert.match(markup, /호출 one/); assert.match(markup, /호출 two/); assert.match(markup, /100토큰/);
  find(fixture.render(), (node) => node.type === 'select').props.onChange({ target: { value: 'execution' } });
  fixture.render(); fixture.commit(); await tick();
  markup = renderToStaticMarkup(fixture.render());
  assert.match(markup, /호출 filtered/); assert.doesNotMatch(markup, /호출 one|호출 two/);
  assert.equal(calls.at(-1).executionRequestId, 'execution'); assert.equal(calls[1].cursor, 'cursor');
});

test('late responses and late failures from another scope are discarded', async () => {
  const pending = [], shared = [], sharedErrors = [];
  const fixture = harness(() => new Promise((resolve, reject) => pending.push({ resolve, reject })), {
    onSnapshot: (value) => shared.push(value.summary.total_tokens), onError: (error) => sharedErrors.push(error),
  });
  fixture.render(); fixture.commit();
  fixture.props.runId = 'second'; fixture.render(); fixture.commit();
  pending[1].resolve(snapshot(200)); await tick();
  pending[0].resolve(snapshot(100)); await tick();
  let markup = renderToStaticMarkup(fixture.render());
  assert.match(markup, /200토큰/); assert.doesNotMatch(markup, /100토큰/);
  button(fixture.render(), '사용량 새로 확인').props.onClick();
  fixture.props.projectName = 'other'; fixture.render(); fixture.commit();
  pending[3].resolve(snapshot(300)); await tick(); pending[2].reject(new Error('old scope failed')); await tick();
  markup = renderToStaticMarkup(fixture.render());
  assert.match(markup, /300토큰/); assert.doesNotMatch(markup, /old scope failed/);
  assert.deepEqual(shared, [200, 300], 'cards receive only validated snapshots from the current scope');
  assert.deepEqual(sharedErrors, [], 'old query failures must not mark the current cards as stale');
  fixture.unmount();
});

test('query errors remain visible and can be retried without executing tasks', async () => {
  let fail = true; const methods = [], shared = [], sharedErrors = [];
  const fixture = harness(async (method) => { methods.push(method); if (fail) throw new Error('usage corrupted'); return snapshot(0); }, {
    onSnapshot: (value) => shared.push(value.summary.total_tokens), onError: (error) => sharedErrors.push(error),
  });
  fixture.render(); fixture.commit(); await tick();
  assert.match(renderToStaticMarkup(fixture.render()), /사용량을 확인하지 못했습니다.*usage corrupted/);
  fail = false; button(fixture.render(), '사용량 새로 확인').props.onClick(); await tick();
  assert.match(renderToStaticMarkup(fixture.render()), /0토큰/);
  assert.deepEqual(methods, ['runs.usage', 'runs.usage']);
  fail = true; button(fixture.render(), '사용량 새로 확인').props.onClick(); await tick();
  assert.match(renderToStaticMarkup(fixture.render()), /0토큰/);
  assert.deepEqual(shared, [0], 'query failure preserves the last shared snapshot');
  assert.equal(sharedErrors.length, 2); assert.match(sharedErrors[1], /usage corrupted/);
});

test('current execution is separate from group history and polling preserves expanded pages', async () => {
  const calls = [];
  const fixture = harness(async (method, params) => {
    calls.push(params);
    return snapshot(calls.length * 100, { execution_request_id: 'active', execution_is_active: true,
      execution_summary: summary(null, { call_count: 0 }), execution_requests: ['active'],
      records: [row(params.cursor ? 'two' : 'one')], next_cursor: params.cursor ? '' : 'cursor' });
  }, { running: true });
  fixture.render(); fixture.commit(); await tick();
  button(fixture.render(), '사용량 상세').props.onClick(); fixture.render(); fixture.commit();
  button(fixture.render(), '이전 호출 더 보기').props.onClick(); await tick();
  assert.equal(fixture.timers.size, 1);
  [...fixture.timers.values()][0](); await tick();
  let markup = renderToStaticMarkup(fixture.render());
  assert.match(markup, /이번 실행 기록/); assert.match(markup, /기록된 AI 호출이 없습니다/);
  assert.match(markup, /300토큰/); assert.match(markup, /호출 one/); assert.match(markup, /호출 two/);
  assert.equal(button(fixture.render(), '이전 호출 더 보기'), undefined);
  fixture.props.running = false; fixture.props.refreshKey = 'done'; fixture.render(); fixture.commit(); await tick();
  assert.equal(fixture.timers.size, 0);
  markup = renderToStaticMarkup(fixture.render());
  assert.match(markup, /400토큰/); assert.match(markup, /호출 two/);
  fixture.unmount();
});
