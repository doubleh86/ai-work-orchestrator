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
const output = resolve(mkdtempSync(join(tempRoot, 'preview-dialog-')));
const cleanup = () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); };
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  execFileSync(process.execPath, [resolve(dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig',
    '--strict', '--target', 'ES2022', '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck',
    '--rootDir', 'desktop', '--outDir', output, 'desktop/renderer/src/PlanningApplyDialog.tsx',
    'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);
const modulePath = join(output, 'renderer/src/PlanningApplyDialog.js');

const candidate = (extra = {}) => ({ preview_id: 'candidate', request_id: 'generation', run_id: 'group',
  run_title: '계획', created_at: '2026-10-01T00:00:00Z', plan_revision: 1, conversation_revision: 2,
  fingerprint: 'confirmed-context', candidate_digest: 'confirmed-content', changes: [], can_apply: true,
  apply_after: '지금', dependency_impact: false, verification_impact: false, completed_task_review: false,
  completed_task_rerun: false, status: 'preview', stale: false, ...extra });
const receipt = (extra = {}) => candidate({ status: 'applied', stale: true,
  actual: { added: 0, modified: 0, excluded: 0, unchanged: 0 }, ...extra });
const status = (phase, extra = {}) => ({ phase, preview: null, request_id: '', error: '',
  can_generate: ['idle', 'failed', 'interrupted'].includes(phase), lock_state: 'unlocked',
  work_state: 'idle', active_operations: [], can_apply: phase === 'ready',
  last_activity_at: '2026-10-01T00:00:00Z', checked_at: '2026-10-01T00:00:00Z', ...extra });
const run = (extra = {}) => ({ id: 'group', stage: 'failed', failed_step: 'agent_execution', tasks: [], ...extra });
function api() {
  const calls = [];
  return { calls, request(method, params) {
    return new Promise((resolve, reject) => calls.push({ method, params, resolve, reject }));
  } };
}
const operations = (rpc, method) => rpc.calls.filter((item) => item.method === method);
const tick = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
function text(tree) {
  if (typeof tree === 'string') return tree;
  if (typeof tree === 'number') return String(tree);
  if (Array.isArray(tree)) return tree.map(text).join('');
  return text(tree?.props?.children || '');
}
function find(tree, predicate) {
  if (!tree || typeof tree !== 'object') return undefined;
  if (Array.isArray(tree)) {
    for (const child of tree) { const found = find(child, predicate); if (found) return found; }
    return undefined;
  }
  return predicate(tree) ? tree : find(tree.props?.children, predicate);
}
const button = (tree, label) => find(tree, (item) => item.type === 'button' && text(item) === label);

// Exercise component lifecycle and deferred RPC without launching Electron or an AI.
function harness(rpc, extra = {}) {
  const slots = [];
  const effects = [];
  const scheduled = [];
  const timers = new Map();
  const applied = [];
  const retries = [];
  let closed = 0;
  let writes = 0;
  let cursor = 0;
  let requestIndex = 0;
  let timerIndex = 0;
  let now = Date.parse('2026-10-02T00:10:00Z');
  let activeElement;
  class Element { isConnected = true; focus() { activeElement = this; } }
  const origin = new Element(); origin.focus();
  const sidebar = { open: true, modal: Boolean(extra.compact), attributes: new Set(),
    matches() { return this.open && this.modal; },
    setAttribute(name) { this.attributes.add(name); }, removeAttribute(name) { this.attributes.delete(name); },
    close() { this.open = false; this.modal = false; },
    show() { this.open = true; this.modal = false; }, showModal() { this.open = true; this.modal = true; }, isConnected: true };
  const dialog = { open: false, showModal() { this.open = true; }, close() { this.open = false; } };
  let props = { projectName: 'project', runId: 'group', planDirty: false,
    onApplied: (...args) => applied.push(args), onRetry: (id) => retries.push(id), onClose: () => { closed++; }, ...extra };
  const hooks = {
    useRef(initial) { const index = cursor++; return slots[index] ||= { current: initial }; },
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = initial;
      return [slots[index], (value) => { writes++; slots[index] = typeof value === 'function' ? value(slots[index]) : value; }];
    },
    useEffect(callback, deps) {
      const index = cursor++;
      const previous = effects[index];
      if (!previous || deps.some((value, i) => !Object.is(value, previous.deps[i]))) {
        effects[index] = { deps, cleanup: previous?.cleanup };
        scheduled.push(() => { effects[index].cleanup?.(); effects[index].cleanup = callback(); });
      }
    },
  };
  const exports = {};
  const localRequire = createRequire(modulePath);
  runInNewContext(readFileSync(modulePath, 'utf8'), { exports,
    HTMLElement: Element, document: { get activeElement() { return activeElement; }, getElementById: () => sidebar },
    Date: class extends Date { static now() { return now; } },
    crypto: { randomUUID: () => `generation-${++requestIndex}` }, window: { orchestrator: rpc, matchMedia: () => ({ matches: Boolean(extra.compact) }),
      setInterval(callback, delay) { const id = ++timerIndex; timers.set(id, { callback, delay }); return id; },
      clearInterval(id) { timers.delete(id); } },
    require: (name) => name === 'react' ? hooks : localRequire(name) });
  return {
    applied, retries, sidebar, dialog, origin, active: () => activeElement,
    render(patch = {}) {
      props = { ...props, ...patch };
      cursor = 0;
      const tree = exports.PlanningApplyDialog(props);
      if (tree.type === 'dialog') tree.props.ref.current = dialog;
      for (const callback of scheduled.splice(0)) callback();
      return tree;
    },
    poll() { for (const timer of timers.values()) if (timer.delay === 2000) timer.callback(); },
    clock(value) { now = value; for (const timer of timers.values()) if (timer.delay === 1000) timer.callback(); },
    unmount() { for (const effect of effects) effect?.cleanup?.(); },
    writeCount: () => writes, closed: () => closed,
  };
}
test('standalone preview swaps compact chat for one modal and restores focus without changing the plan', async () => {
  const rpc = api();
  const view = harness(rpc, { compact: true });
  await load(rpc, view, status('idle', { can_generate: false }));
  assert.equal(view.dialog.open, true);
  assert.equal(view.sidebar.open, false);
  assert.ok(view.sidebar.attributes.has('data-planning-preview-open'));
  assert.equal(view.active(), view.origin);
  view.unmount();
  assert.equal(view.dialog.open, false);
  assert.equal(view.sidebar.modal, true);
  assert.equal(view.sidebar.attributes.size, 0);
  assert.equal(view.active(), view.origin);
  assert.deepEqual(rpc.calls.map((call) => call.method), ['runs.planningPreviewStatus']);
});
async function load(rpc, view, snapshot = status('ready', { preview: candidate() })) {
  view.render();
  operations(rpc, 'runs.planningPreviewStatus').at(-1).resolve(snapshot);
  await tick();
  return view.render();
}
async function confirmApply(rpc, snapshot = status('ready', { preview: candidate() })) {
  operations(rpc, 'runs.planningPreviewStatus').at(-1).resolve(snapshot);
  await tick();
}

test('request and usage limit previews disclose raw errors without regenerating until explicitly requested', async () => {
  for (const [error, title] of [
    ['exceeded retry limit, last status: 429 Too Many Requests', 'AI 요청이 제한되었습니다'],
    ['HTTP 429: insufficient_quota', 'AI 사용 한도에 도달했습니다'],
  ]) {
    const rpc = api(), view = harness(rpc);
    const tree = await load(rpc, view, status('failed', { error }));
    const alert = find(tree, node => node.props?.role === 'alert' && text(node).includes(title));
    assert.ok(alert);
    const details = find(alert, node => node.type === 'details');
    assert.ok(details); assert.ok(!details.props.open); assert.ok(text(details).includes(error));
    assert.equal(operations(rpc, 'runs.previewPlanningApply').length, 0);
    assert.equal(button(tree, '변경안 다시 작성').props.disabled, false);
    assert.equal(operations(rpc, 'runs.applyPlanningPreview').length, 0);
    view.unmount();
  }
});
const operation = (extra = {}) => ({ kind: 'task_execute', operation: 'execute', task_id: 'task', task_title: '설정 통합',
  started_at: '2026-10-02T00:00:00Z', stage_changed_at: '2026-10-02T00:03:00Z', last_activity_at: '', ...extra });
const activeStatus = (extra = {}) => status('check_required', { preview: candidate(), work_state: 'active', can_apply: false,
  active_operations: [operation()], ...extra });

test('saved ready preview is secondary to actual work; ending work updates timing and action together', async () => {
  const rpc = api();
  const view = harness(rpc);
  let tree = await load(rpc, view, activeStatus());
  let markup = renderToStaticMarkup(tree);
  assert.match(markup, /Task 실행 중 · 설정 통합/);
  assert.match(markup, /현재 작업 종료 후 확인/);
  assert.match(markup, /최근 활동 정보 없음/);
  assert.match(markup, /작업 단계 변경/);
  assert.match(markup, /상태 조회/);
  assert.doesNotMatch(markup, /적용 가능 시점: 지금|반영 전 확인/);
  assert.equal(button(tree, '이 변경 반영'), undefined);
  view.poll();
  operations(rpc, 'runs.planningPreviewStatus').at(-1).resolve(status('ready', { preview: candidate() }));
  await tick();
  tree = view.render();
  markup = renderToStaticMarkup(tree);
  assert.match(markup, /적용 가능 시점: 지금/);
  assert.ok(button(tree, '이 변경 반영'));
  assert.equal(operations(rpc, 'runs.applyPlanningPreview').length, 0);
  view.poll();
  operations(rpc, 'runs.planningPreviewStatus').at(-1).resolve(status('idle'));
  await tick();
  assert.equal(button(view.render(), '이 변경 반영'), undefined);
  assert.equal(operations(rpc, 'runs.previewPlanningApply').length, 0, 'status refresh must not regenerate a stale candidate');
  view.unmount();
});

test('elapsed time survives reopening and stage changes; clock ticks do not report AI activity or query', async () => {
  const rpc = api();
  const first = harness(rpc);
  await load(rpc, first, activeStatus());
  assert.match(renderToStaticMarkup(first.render()), /600초 경과/);
  first.unmount();
  const reopened = harness(rpc);
  await load(rpc, reopened, activeStatus());
  assert.match(renderToStaticMarkup(reopened.render()), /600초 경과/);
  const before = rpc.calls.length;
  reopened.clock(Date.parse('2026-10-02T00:10:10Z'));
  assert.match(renderToStaticMarkup(reopened.render()), /610초 경과/);
  assert.match(renderToStaticMarkup(reopened.render()), /최근 활동 정보 없음/);
  assert.equal(rpc.calls.length, before);
  reopened.poll();
  operations(rpc, 'runs.planningPreviewStatus').at(-1).resolve(activeStatus({ active_operations: [operation({ kind: 'task_review' })] }));
  await tick();
  const markup = renderToStaticMarkup(reopened.render());
  assert.match(markup, /Task 리뷰 중 · 설정 통합/);
  assert.match(markup, /610초 경과/);
  reopened.unmount();
});

test('failed current-work query hides apply and cannot reuse saved immediate timing', async () => {
  const rpc = api();
  const view = harness(rpc);
  await load(rpc, view);
  view.poll();
  operations(rpc, 'runs.planningPreviewStatus').at(-1).reject(new Error('work query failed'));
  await tick();
  const tree = view.render();
  assert.equal(button(tree, '이 변경 반영'), undefined);
  assert.doesNotMatch(renderToStaticMarkup(tree), /적용 가능 시점: 지금/);
  assert.match(renderToStaticMarkup(tree), /work query failed/);
  view.unmount();
});

test('simultaneous planning and Task work each show their own kind, start and activity evidence', async () => {
  const rpc = api();
  const view = harness(rpc);
  await load(rpc, view, activeStatus({ active_operations: [operation({ kind: 'preview_generation', operation: 'planning-preview',
    task_id: '', task_title: '', started_at: '2026-10-02T00:05:00Z', last_activity_at: '2026-10-02T00:09:00Z' }),
  operation({ kind: 'task_verify' })] }));
  const markup = renderToStaticMarkup(view.render());
  assert.match(markup, /AI 작업 진행 중 · 변경안 작성 중/);
  assert.match(markup, /Task 검증 중 · 설정 통합/);
  assert.match(markup, /300초 경과/);
  assert.match(markup, /600초 경과/);
  assert.match(markup, /최근 AI 활동/);
  assert.match(markup, /최근 활동 정보 없음/);
  assert.equal(operations(rpc, 'runs.previewPlanningApply').length, 0);
  view.unmount();
});

test('old ready response and queued polling cannot apply after actual work starts', async () => {
  const rpc = api();
  const view = harness(rpc);
  const tree = await load(rpc, view);
  view.poll();
  const oldPoll = operations(rpc, 'runs.planningPreviewStatus').at(-1);
  button(tree, '이 변경 반영').props.onClick();
  await confirmApply(rpc, activeStatus());
  oldPoll.resolve(status('ready', { preview: candidate() }));
  await tick();
  assert.match(renderToStaticMarkup(view.render()), /Task 실행 중/);
  assert.equal(button(view.render(), '이 변경 반영'), undefined);
  assert.equal(operations(rpc, 'runs.applyPlanningPreview').length, 0);
  view.unmount();
});

test('pre-apply revalidation rejects uncertain ownership, changed candidate, stale input, and query failure', async () => {
  for (const next of [status('check_required', { work_state: 'unknown' }),
    status('ready', { preview: candidate({ preview_id: 'newer' }) }),
    status('ready', { preview: candidate({ stale: true }) }),
    status('ready', { preview: candidate(), work_state: undefined }),
    status('ready', { preview: candidate(), can_apply: false }), new Error('read failed')]) {
    const rpc = api();
    const view = harness(rpc);
    button(await load(rpc, view), '이 변경 반영').props.onClick();
    const check = operations(rpc, 'runs.planningPreviewStatus').at(-1);
    if (next instanceof Error) check.reject(next); else check.resolve(next);
    await tick();
    const tree = view.render();
    assert.equal(operations(rpc, 'runs.applyPlanningPreview').length, 0);
    assert.equal(operations(rpc, 'runs.previewPlanningApply').length, 0);
    assert.match(renderToStaticMarkup(tree), next instanceof Error ? /반영 전 작업 상태를 확인하지 못했습니다/ : /최신 상태를 확인/);
    view.unmount();
  }
});

test('switching groups during pre-apply check cannot send the old mutation or publish old work', async () => {
  const rpc = api();
  const view = harness(rpc);
  button(await load(rpc, view), '이 변경 반영').props.onClick();
  const old = operations(rpc, 'runs.planningPreviewStatus').at(-1);
  view.render({ projectName: 'other', runId: 'other' });
  operations(rpc, 'runs.planningPreviewStatus').at(-1).resolve(activeStatus({ active_operations: [operation({ task_title: '다른 그룹' })] }));
  await tick();
  const tree = view.render();
  const writes = view.writeCount();
  old.resolve(status('ready', { preview: candidate() }));
  await tick();
  assert.equal(view.writeCount(), writes);
  assert.equal(operations(rpc, 'runs.applyPlanningPreview').length, 0);
  assert.match(renderToStaticMarkup(tree), /다른 그룹/);
  view.unmount();
});

test('rapid regeneration creates one request and an older polling failure cannot erase its candidate', async () => {
  const rpc = api();
  const view = harness(rpc);
  let tree = await load(rpc, view, status('failed'));
  view.poll();
  const older = operations(rpc, 'runs.planningPreviewStatus').at(-1);
  const regenerate = button(tree, '변경안 다시 작성');
  regenerate.props.onClick(); regenerate.props.onClick();
  assert.equal(operations(rpc, 'runs.planningPreviewStatus').length, 3);
  operations(rpc, 'runs.planningPreviewStatus').at(-1).resolve(status('failed'));
  await tick();
  assert.equal(operations(rpc, 'runs.previewPlanningApply').length, 1);
  tree = view.render();
  assert.match(renderToStaticMarkup(tree), /변경안 작성 중/);
  older.reject(new Error('old session failed'));
  await tick();
  assert.doesNotMatch(renderToStaticMarkup(view.render()), /old session failed/);
  operations(rpc, 'runs.previewPlanningApply')[0].resolve(candidate());
  await tick();
  operations(rpc, 'runs.planningPreviewStatus').at(-1).resolve(status('ready', { preview: candidate() }));
  await tick();
  assert.ok(button(view.render(), '이 변경 반영'));
  assert.equal(operations(rpc, 'runs.applyPlanningPreview').length, 0);
  view.unmount();
});

test('confirmed apply uses the matching response once without a second group read or duplicate mutation', async () => {
  const rpc = api();
  const view = harness(rpc);
  const tree = await load(rpc, view);
  const apply = button(tree, '이 변경 반영');
  apply.props.onClick(); apply.props.onClick();
  assert.equal(operations(rpc, 'runs.applyPlanningPreview').length, 0);
  assert.equal(operations(rpc, 'runs.planningPreviewStatus').length, 2);
  button(tree, '닫기').props.onClick();
  assert.equal(view.closed(), 0, 'a stale close handler must respect the synchronous apply latch');
  await confirmApply(rpc);
  assert.equal(operations(rpc, 'runs.applyPlanningPreview').length, 1);
  const pending = operations(rpc, 'runs.applyPlanningPreview')[0];
  assert.equal(pending.params.previewId, 'candidate');
  assert.equal(pending.params.fingerprint, 'confirmed-context');
  assert.equal(pending.params.candidateDigest, 'confirmed-content');
  pending.resolve({ run: run(), preview: receipt() });
  await tick();
  assert.match(renderToStaticMarkup(view.render()), /실제 반영/);
  assert.equal(view.applied.length, 1);
  assert.equal(operations(rpc, 'runs.get').length, 0);
  view.poll();
  operations(rpc, 'runs.planningPreviewStatus').at(-1).resolve(status('applied', { preview: receipt() }));
  await tick();
  button(view.render(), '작업 그룹으로').props.onClick();
  assert.equal(view.closed(), 1);
  assert.equal(view.applied.length, 1);
  assert.equal(operations(rpc, 'runs.get').length, 0);
  view.unmount();
});

test('plan application blocks Task actions during confirmation and releases on success or failure', async () => {
  for (const fail of [false, true]) {
    const rpc = api(); let starts = 0, finishes = 0;
    const view = harness(rpc, { onTaskEditStart: () => { starts++; return () => finishes++; } });
    const tree = await load(rpc, view);
    assert.equal(starts, 0, 'reading a stored proposal is not a Task edit');
    button(tree, '이 변경 반영').props.onClick();
    assert.equal(starts, 1); assert.equal(finishes, 0);
    await confirmApply(rpc);
    const pending = operations(rpc, 'runs.applyPlanningPreview')[0];
    if (fail) {
      pending.reject(new Error('apply failed')); await tick();
      operations(rpc, 'runs.planningPreviewStatus').at(-1).resolve(status('failed')); await tick();
    } else { pending.resolve({ run: run(), preview: receipt() }); await tick(); }
    assert.equal(finishes, 1); view.unmount(); assert.equal(finishes, 1);
  }
});

test('response loss checks the saved apply receipt and never sends another mutation', async () => {
  const rpc = api();
  const view = harness(rpc);
  button(await load(rpc, view), '이 변경 반영').props.onClick();
  await confirmApply(rpc);
  operations(rpc, 'runs.applyPlanningPreview')[0].reject(new Error('connection lost'));
  await tick();
  operations(rpc, 'runs.planningPreviewStatus').at(-1).resolve(status('applied', { preview: receipt() }));
  await tick();
  view.render();
  assert.equal(operations(rpc, 'runs.get').length, 1);
  const lookup = operations(rpc, 'runs.get')[0];
  for (let index = 0; index < 3; index++) {
    view.poll();
    operations(rpc, 'runs.planningPreviewStatus').at(-1).resolve(status('applied', { preview: receipt() }));
    await tick();
    view.render();
  }
  assert.equal(operations(rpc, 'runs.get').length, 1, 'polling the same receipt must not cancel a slow group lookup');
  lookup.resolve(run());
  await tick();
  assert.match(renderToStaticMarkup(view.render()), /계획 반영 완료/);
  assert.equal(view.applied.length, 1);
  assert.equal(operations(rpc, 'runs.applyPlanningPreview').length, 1);
  assert.equal(operations(rpc, 'runs.previewPlanningApply').length, 0);
  view.unmount();
});

test('an uncertain apply with no stored receipt waits for explicit regeneration', async () => {
  const rpc = api();
  const view = harness(rpc);
  button(await load(rpc, view), '이 변경 반영').props.onClick();
  await confirmApply(rpc);
  operations(rpc, 'runs.applyPlanningPreview')[0].reject(new Error('reply lost'));
  await tick();
  operations(rpc, 'runs.planningPreviewStatus').at(-1).resolve(status('idle'));
  await tick();
  let tree = view.render();
  assert.ok(button(tree, '변경안 다시 작성'));
  for (let index = 0; index < 3; index++) {
    view.poll();
    operations(rpc, 'runs.planningPreviewStatus').at(-1).resolve(status('idle'));
    await tick();
    tree = view.render();
  }
  assert.equal(operations(rpc, 'runs.previewPlanningApply').length, 0);
  assert.equal(operations(rpc, 'runs.applyPlanningPreview').length, 1);
  assert.match(renderToStaticMarkup(tree), /reply lost/);
  view.unmount();
});

test('wrong group, candidate, context, digest, status, or missing actual counts are not apply success', async () => {
  const invalid = [
    { run: run({ id: 'other' }), preview: receipt() },
    { run: run(), preview: receipt({ run_id: 'other' }) },
    { run: run(), preview: receipt({ preview_id: 'other' }) },
    { run: run(), preview: receipt({ request_id: 'other' }) },
    { run: run(), preview: receipt({ fingerprint: 'other' }) },
    { run: run(), preview: receipt({ candidate_digest: 'other' }) },
    { run: run(), preview: candidate() },
    { run: run(), preview: receipt({ actual: undefined }) },
    { run: run(), preview: receipt({ actual: { added: -1, modified: 0, excluded: 0, unchanged: 0 } }) },
  ];
  for (const result of invalid) {
    const rpc = api();
    const view = harness(rpc);
    button(await load(rpc, view), '이 변경 반영').props.onClick();
    await confirmApply(rpc);
    operations(rpc, 'runs.applyPlanningPreview')[0].resolve(result);
    await tick();
    assert.equal(view.applied.length, 0);
    operations(rpc, 'runs.planningPreviewStatus').at(-1).reject(new Error('status unavailable'));
    await tick();
    const tree = view.render();
    assert.match(renderToStaticMarkup(tree), /status unavailable/);
    assert.equal(button(tree, '이 변경 반영'), undefined);
    assert.equal(operations(rpc, 'runs.applyPlanningPreview').length, 1);
    assert.equal(operations(rpc, 'runs.previewPlanningApply').length, 0);
    view.unmount();
  }
});

test('latest draft edits, candidate changes, and unmount make old apply handlers inert', async () => {
  const rpc = api();
  const view = harness(rpc);
  const original = await load(rpc, view);
  const oldApply = button(original, '이 변경 반영');
  view.render({ planDirty: true });
  oldApply.props.onClick();
  assert.equal(operations(rpc, 'runs.applyPlanningPreview').length, 0);
  view.render({ planDirty: false });
  view.poll();
  operations(rpc, 'runs.planningPreviewStatus').at(-1).resolve(status('ready', { preview: candidate({ preview_id: 'new' }) }));
  await tick();
  oldApply.props.onClick();
  assert.equal(operations(rpc, 'runs.applyPlanningPreview').length, 0);
  const current = button(view.render(), '이 변경 반영');
  view.unmount();
  current.props.onClick();
  assert.equal(operations(rpc, 'runs.applyPlanningPreview').length, 0);
});

test('switching project cannot publish a late apply response or begin a mutation from old handlers', async () => {
  const rpc = api();
  const view = harness(rpc);
  const original = await load(rpc, view);
  button(original, '이 변경 반영').props.onClick();
  await confirmApply(rpc);
  const pending = operations(rpc, 'runs.applyPlanningPreview')[0];
  view.render({ projectName: 'other', runId: 'another' });
  const other = candidate({ run_id: 'another', preview_id: 'another-candidate' });
  operations(rpc, 'runs.planningPreviewStatus').at(-1).resolve(status('ready', { preview: other }));
  await tick();
  const tree = view.render();
  const writes = view.writeCount();
  pending.resolve({ run: run(), preview: receipt() });
  await tick();
  assert.equal(view.writeCount(), writes);
  assert.equal(view.applied.length, 0);
  button(original, '이 변경 반영').props.onClick();
  assert.equal(operations(rpc, 'runs.applyPlanningPreview').length, 1);
  assert.match(renderToStaticMarkup(tree), /another-candidate|another/);
  view.unmount();
});

test('closing during an apply response cannot notify or write into the closed view', async () => {
  const rpc = api();
  const view = harness(rpc);
  button(await load(rpc, view), '이 변경 반영').props.onClick();
  await confirmApply(rpc);
  view.unmount();
  const writes = view.writeCount();
  operations(rpc, 'runs.applyPlanningPreview')[0].resolve({ run: run(), preview: receipt() });
  await tick();
  assert.equal(view.writeCount(), writes);
  assert.equal(view.applied.length, 0);
  assert.equal(operations(rpc, 'runs.get').length, 0);
});

test('preview owns its target once outside the closed candidate record and preserves approval effects and metadata', async () => {
  const rpc = api();
  const contextRun = run({ summary: '선택한 그룹 목표', planning_conversation_revision: 2, planning_messages: [] });
  const view = harness(rpc, { context: { projectName: 'mock', run: contextRun } });
  const tree = await load(rpc, view, status('ready', { preview: candidate({ run_title: contextRun.summary }) }));
  const markup = renderToStaticMarkup(tree);
  const context = find(tree, item => item.props.className === 'planning-preview-dialog__context');
  const record = find(context, item => item.type === 'details');
  assert.equal(record.props.open, undefined);
  assert.match(text(record), /선택한 그룹 목표.*계획 revision 1.*대화 revision 2/);
  assert.equal((text(context).match(/선택한 그룹 목표/g) || []).length, 1);
  assert.match(markup, /계획만 변경 · Task 실행과 Main 반영은 별도/); assert.match(markup, /선행 Task 영향/);
  assert.ok(button(tree, '이 변경 반영'));
  view.unmount();
});

test('compact preview keeps changed counts and true impacts visible with full comparison in closed records', async () => {
  const rpc = api(), view = harness(rpc);
  const changes = [{ task_id: 'changed', title: '변경 작업', kind: 'modified', fields: ['description'] },
    { task_id: 'kept', title: '보존 작업', kind: 'unchanged', fields: [] }];
  const tree = await load(rpc, view, status('ready', { preview: candidate({ changes, verification_impact: true, completed_task_review: true }) }));
  const record = find(tree, node => node.type === 'details' && text(node).startsWith('변경안 기록'));
  assert.equal(record.props.open, undefined); assert.match(text(record), /유지 1/);
  const basic = (function visible(node) {
    if (typeof node === 'string' || typeof node === 'number') return String(node);
    if (Array.isArray(node)) return node.map(visible).join(' ');
    return !node || node.type === 'details' ? '' : visible(node.props?.children);
  })(tree);
  assert.match(basic, /수정 1/); assert.match(basic, /검증 명령 변경 있음/); assert.match(basic, /완료 Task 재검토 필요/);
  assert.doesNotMatch(basic, /추가 0|제외 0|유지 1/);
  assert.ok(button(tree, '이 변경 반영'));
  assert.equal(operations(rpc, 'runs.applyPlanningPreview').length, 0);
  view.unmount();
});

test('identical preview errors have one alert and distinct query causes keep one refresh action', async () => {
  const rpc = api(), view = harness(rpc);
  const lookupError = '계획 반영 기록은 확인했지만 그룹 상태를 조회하지 못했습니다. Error: repeated failure';
  await load(rpc, view, status('applied', { preview: receipt(), error: lookupError }));
  operations(rpc, 'runs.get').at(-1).reject(new Error('repeated failure'));
  await tick();
  let markup = renderToStaticMarkup(view.render());
  assert.equal((markup.match(/repeated failure/g) || []).length, 1);
  assert.equal((markup.match(/>상태 다시 확인</g) || []).length, 1);
  view.poll();
  operations(rpc, 'runs.planningPreviewStatus').at(-1).resolve(status('applied', { preview: receipt(), error: 'separate query failure' }));
  await tick();
  markup = renderToStaticMarkup(view.render());
  assert.match(markup, /repeated failure/); assert.match(markup, /separate query failure/);
  assert.equal((markup.match(/>상태 다시 확인</g) || []).length, 1);
  view.unmount();
});

test('applied group lookup errors survive polling and can be retried with read-only actions', async () => {
  const rpc = api();
  const view = harness(rpc);
  await load(rpc, view, status('applied', { preview: receipt() }));
  operations(rpc, 'runs.get')[0].reject(new Error('group read failed'));
  await tick();
  let tree = view.render();
  assert.match(renderToStaticMarkup(tree), /group read failed/);
  view.poll();
  operations(rpc, 'runs.planningPreviewStatus').at(-1).resolve(status('applied', { preview: receipt() }));
  await tick();
  tree = view.render();
  assert.match(renderToStaticMarkup(tree), /group read failed/);
  assert.equal(operations(rpc, 'runs.get').length, 1);
  button(tree, '상태 다시 확인').props.onClick();
  view.render();
  operations(rpc, 'runs.planningPreviewStatus').at(-1).resolve(status('applied', { preview: receipt() }));
  await tick();
  view.render();
  assert.equal(operations(rpc, 'runs.get').length, 2);
  operations(rpc, 'runs.get')[1].resolve(run());
  await tick();
  assert.doesNotMatch(renderToStaticMarkup(view.render()), /group read failed/);
  assert.equal(view.applied.length, 1);
  assert.equal(operations(rpc, 'runs.previewPlanningApply').length, 0);
  assert.equal(operations(rpc, 'runs.applyPlanningPreview').length, 0);
  view.unmount();
});

test('a read failure queued before a newer manual check cannot show an old error or hide the new candidate', async () => {
  const rpc = api();
  const view = harness(rpc);
  view.render();
  operations(rpc, 'runs.planningPreviewStatus')[0].reject(new Error('initial failed'));
  await tick();
  const retry = button(view.render(), '상태 다시 확인');
  retry.props.onClick();
  operations(rpc, 'runs.planningPreviewStatus')[1].reject(new Error('superseded queued failure'));
  await Promise.resolve();
  retry.props.onClick();
  operations(rpc, 'runs.planningPreviewStatus')[2].resolve(status('ready', { preview: candidate() }));
  await tick();
  const tree = view.render();
  assert.ok(button(tree, '이 변경 반영'));
  assert.doesNotMatch(renderToStaticMarkup(tree), /superseded queued failure/);
  view.unmount();
});

test('a failed Task retry is offered only after the applied group is confirmed and old retry handlers stop after change', async () => {
  const rpc = api();
  const view = harness(rpc);
  const applied = receipt({ actual: { added: 0, modified: 1, excluded: 0, unchanged: 0 },
    changes: [{ task_id: 'task', title: 'Task', kind: 'modified', fields: ['expected_paths'] }] });
  let tree = await load(rpc, view, status('applied', { preview: applied }));
  assert.equal(button(tree, '적용한 복구안으로 재실행'), undefined);
  assert.doesNotMatch(text(tree), /복구안 적용 완료/);
  operations(rpc, 'runs.get')[0].resolve(run({ tasks: [{ id: 'task', status: 'failed' }],
    execution_control: { action: 'resume', situation: 'resumable' } }));
  await tick();
  tree = view.render();
  const retry = button(tree, '적용한 복구안으로 재실행');
  assert.ok(retry);
  assert.match(text(tree), /복구안 적용 완료/);
  retry.props.onClick();
  assert.deepEqual(view.retries, ['task']);
  view.poll();
  operations(rpc, 'runs.planningPreviewStatus').at(-1).resolve(status('chat'));
  await tick();
  retry.props.onClick();
  assert.deepEqual(view.retries, ['task']);
  assert.equal(operations(rpc, 'tasks.retry').length, 0, 'the dialog delegates the explicit action without starting execution itself');
  view.unmount();
});

test('an older applied group lookup cannot replace a newer candidate or show its lookup failure', async () => {
  for (const fail of [false, true]) {
    const rpc = api();
    const view = harness(rpc);
    await load(rpc, view, status('applied', { preview: receipt() }));
    const old = operations(rpc, 'runs.get')[0];
    view.poll();
    operations(rpc, 'runs.planningPreviewStatus').at(-1).resolve(status('ready', { preview: candidate({ preview_id: 'new' }) }));
    await tick();
    view.render();
    const writes = view.writeCount();
    if (fail) old.reject(new Error('old group read failed'));
    else old.resolve(run());
    await tick();
    assert.equal(view.writeCount(), writes);
    assert.equal(view.applied.length, 0);
    const tree = view.render();
    assert.ok(button(tree, '이 변경 반영'));
    assert.doesNotMatch(renderToStaticMarkup(tree), /old group read failed/);
    view.unmount();
  }
});

test('wrong group lookup stays unconfirmed and does not expose a Task retry', async () => {
  const rpc = api();
  const view = harness(rpc);
  await load(rpc, view, status('applied', { preview: receipt() }));
  operations(rpc, 'runs.get')[0].resolve(run({ id: 'other' }));
  await tick();
  const tree = view.render();
  assert.equal(view.applied.length, 0);
  assert.equal(button(tree, '적용한 복구안으로 재실행'), undefined);
  assert.match(renderToStaticMarkup(tree), /일치하지 않습니다/);
  view.unmount();
});

test('Task proposal saves only unless its exact failed Task continuation is explicitly chosen in either surface', async () => {
  for (const embedded of [false, true]) for (const continueAfter of [false, true]) {
    const rpc = api(); const continued = [];
    const contextRun = run({ tasks: [{ id: 'kept', status: 'completed' }, { id: 'fix', status: 'failed' }],
      execution_control: { action: 'resume', situation: 'resumable' } });
    const preview = candidate({ changes: [{ task_id: 'fix', title: '실패 작업', kind: 'modified', fields: ['description'] }] });
    const saved = receipt({ changes: preview.changes, actual: { added: 0, modified: 1, excluded: 0, unchanged: 0 } });
    const view = harness(rpc, { embedded, continueTaskId: 'fix', context: { projectName: 'project', run: contextRun },
      onContinue: (...args) => continued.push(args) });
    let tree = await load(rpc, view, status('ready', { preview }));
    assert.equal(tree.type, embedded ? 'section' : 'dialog');
    if (embedded) assert.match(text(tree), /완료 작업 1개는 보존/);
    else assert.match(text(tree), /완료 Task: 자동 재실행 없음/);
    assert.match(text(tree), /복구안 확인/);
    assert.match(text(tree), /계획에만 저장 · 작업 재실행은 별도/);
    assert.match(text(tree), /재실행 성공 후 남은 작업도 이어갑니다/);
    assert.doesNotMatch(text(tree), /복구안 적용 완료/);
    assert.ok(button(tree, '복구안 적용 후 2번부터 계속'));
    assert.ok(button(tree, '복구안 적용'));
    button(tree, continueAfter ? '복구안 적용 후 2번부터 계속' : '복구안 적용').props.onClick();
    assert.equal(continued.length, 0);
    await confirmApply(rpc, status('ready', { preview }));
    operations(rpc, 'runs.applyPlanningPreview')[0].resolve({ run: contextRun, preview: saved });
    await tick(); tree = view.render();
    assert.equal(view.applied.length, 1);
    assert.match(text(tree), /복구안 적용 완료/);
    assert.ok(button(tree, '적용한 복구안으로 재실행'));
    assert.equal(button(tree, '복구안 적용'), undefined);
    assert.equal(view.retries.length, 0, 'applying a plan is distinct from requesting its retry');
    assert.equal(continued.length, continueAfter ? 1 : 0);
    if (continueAfter) { assert.equal(continued[0][0], 'fix'); assert.equal(continued[0][1], contextRun); }
    assert.equal(operations(rpc, 'tasks.retry').length, 0);
    view.unmount();
  }
});

test('compound continuation excludes missing Task, wrong context and changes to other Tasks in either surface', async () => {
  for (const embedded of [false, true]) for (const scope of ['missing', 'project', 'stage', 'other-change']) {
    const rpc = api();
    const contextRun = run({ tasks: [{ id: 'fix', status: 'failed' }], ...(scope === 'stage' ? { stage: 'planned' } : {}) });
    const preview = candidate({ changes: [{ task_id: 'fix', title: 'Task', kind: 'modified', fields: [] },
      ...(scope === 'other-change' ? [{ task_id: 'other', title: '다른 Task', kind: 'modified', fields: [] }] : [])] });
    const view = harness(rpc, { embedded, continueTaskId: scope === 'missing' ? 'missing' : 'fix',
      context: { projectName: scope === 'project' ? 'another' : 'project', run: contextRun }, onContinue: () => assert.fail('not approved') });
    const tree = await load(rpc, view, status('ready', { preview }));
    assert.equal(find(tree, (item) => item.type === 'button' && text(item).startsWith('복구안 적용 후')), undefined);
    assert.doesNotMatch(text(tree), /NaN/);
    assert.equal(operations(rpc, 'runs.applyPlanningPreview').length, 0);
    view.unmount();
  }
});

test('chat answer repair entry distinguishes saving a fix from running it without a continuation target', async () => {
  const rpc = api();
  const currentRun = run({tasks: [{id: 'fix', status: 'failed'}], execution_control: {action: 'resume', situation: 'resumable'}});
  const proposed = candidate({changes: [{task_id: 'fix', title: '실패 작업', kind: 'modified', fields: ['description']}]});
  const saved = receipt({changes: proposed.changes, actual: {added: 0, modified: 1, excluded: 0, unchanged: 0}});
  const view = harness(rpc, {context: {projectName: 'project', run: currentRun}});
  let tree = await load(rpc, view, status('ready', {preview: proposed}));
  assert.ok(button(tree, '복구안 적용'));
  assert.equal(button(tree, '적용한 복구안으로 재실행'), undefined);
  assert.equal(find(tree, item => item.type === 'button' && text(item).includes('번부터 계속')), undefined);
  assert.equal(operations(rpc, 'runs.applyPlanningPreview').length, 0);
  button(tree, '복구안 적용').props.onClick();
  await confirmApply(rpc, status('ready', {preview: proposed}));
  assert.deepEqual(view.retries, []);
  operations(rpc, 'runs.applyPlanningPreview')[0].resolve({run: currentRun, preview: saved});
  await tick(); tree = view.render();
  assert.match(text(tree), /복구안 적용 완료/);
  assert.equal(operations(rpc, 'runs.applyPlanningPreview').length, 1);
  assert.deepEqual(view.retries, []);
  button(tree, '적용한 복구안으로 재실행').props.onClick();
  assert.deepEqual(view.retries, ['fix']);
  assert.equal(operations(rpc, 'tasks.retry').length, 0);
  view.unmount();
});
