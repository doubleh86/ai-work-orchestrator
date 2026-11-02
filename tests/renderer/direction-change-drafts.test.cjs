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
const output = resolve(mkdtempSync(join(tempRoot, 'direction-drafts-')));
const cleanup = () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); };
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  execFileSync(process.execPath, [resolve(dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig',
    '--strict', '--target', 'ES2022', '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck',
    '--rootDir', 'desktop', '--outDir', output, 'desktop/renderer/src/DirectionChangePanel.tsx',
    'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);
const modulePath = join(output, 'renderer/src/DirectionChangePanel.js');
const { DirectionChangeDrafts } = require(join(output, 'renderer/src/directionChangeDrafts.js'));

function store() {
  let sequence = 0;
  return new DirectionChangeDrafts(() => `direction-${++sequence}`);
}
function run(extra = {}) {
  return { id: 'group', summary: '실행 그룹', stage: 'executing', tasks: [], direction_change_requests: [], ...extra };
}
function accepted(params, extra = {}) {
  return run({ id: params.runId, direction_change_requests: [{
    request_id: params.requestId, text: params.text, status: 'received', task_id: '', task_title: '',
    created_at: '2026-10-01T01:00:00Z', updated_at: '2026-10-01T01:00:00Z', next_step: '미리보기 확인', error: '',
  }], ...extra });
}
function api() {
  const calls = [];
  return { calls, request(method, params) {
    return new Promise((resolve, reject) => calls.push({ method, params, resolve, reject }));
  } };
}
function find(tree, predicate) {
  if (!tree || typeof tree !== 'object') return undefined;
  if (Array.isArray(tree)) {
    for (const child of tree) { const result = find(child, predicate); if (result) return result; }
    return undefined;
  }
  return predicate(tree) ? tree : find(tree.props?.children, predicate);
}
const input = (tree) => find(tree, (item) => item.type === 'textarea');
const send = (tree) => find(tree, (item) => item.type === 'button' && ['다음 작업에 반영 요청', '접수 중…'].includes(item.props.children));
const tick = async () => { await Promise.resolve(); await Promise.resolve(); };

test('shared composer owns preview while independent direction views keep their existing entry and history', () => {
  const rpc = api(), drafts = store();
  const current = run({ direction_change_requests: [{ request_id: 'request', status: 'awaiting_confirmation', text: '다음 작업 변경',
    created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z', next_step: '변경안 확인' }] });
  let previews = 0;
  const view = harness(rpc, drafts, { run: current, onOpenPreview: () => previews++ });
  const standalone = view.render();
  const preview = find(standalone, item => item.type === 'button' && item.props.children === '변경 미리보기');
  assert.ok(preview); preview.props.onClick(); assert.equal(previews, 1);
  const shared = view.render({ previewElsewhere: true });
  assert.equal(find(shared, item => item.type === 'button' && item.props.children === '변경 미리보기'), undefined);
  assert.match(renderToStaticMarkup(shared), /변경 요청 기록/);
  assert.ok(send(shared)); assert.deepEqual(rpc.calls, []);
  view.unmount();
});

// Hook lifecycle checks exercise request/draft behavior without starting Electron.
function harness(rpc, drafts, extra = {}) {
  const slots = [];
  const effects = [];
  const scheduled = [];
  const acceptedCalls = [];
  let cursor = 0;
  let notifications = 0;
  let props = { projectName: 'project', run: run(), drafts, onAccepted: () => acceptedCalls.push('accepted'),
    onOpenPreview() {}, onStop() {}, ...extra };
  function effect(callback, deps) {
    const index = cursor++;
    const previous = effects[index];
    if (!previous || deps.some((value, i) => !Object.is(value, previous.deps[i]))) {
      effects[index] = { deps, cleanup: previous?.cleanup };
      scheduled.push(() => { effects[index].cleanup?.(); effects[index].cleanup = callback(); });
    }
  }
  const hooks = {
    useRef(initial) { const index = cursor++; return slots[index] ||= { current: initial }; },
    useEffect: effect,
    useSyncExternalStore(subscribe, snapshot) {
      effect(() => subscribe(() => notifications++), [subscribe]);
      return snapshot();
    },
  };
  const exports = {};
  const localRequire = createRequire(modulePath);
  runInNewContext(readFileSync(modulePath, 'utf8'), {
    exports, window: { orchestrator: rpc },
    require: (name) => name === 'react' ? hooks : localRequire(name),
  });
  return {
    acceptedCalls,
    edit(value) { drafts.edit(props.projectName, props.run.id, value); },
    message() { this.render(); return drafts.read(props.projectName, props.run.id).text; },
    render(patch = {}) {
      props = { ...props, ...patch };
      cursor = 0;
      const tree = exports.DirectionChangePanel(props);
      for (const callback of scheduled.splice(0)) callback();
      return tree;
    },
    unmount() { for (const item of effects) item?.cleanup?.(); },
    notificationCount: () => notifications,
  };
}

test('session drafts survive screen and project switches without automatically sending', () => {
  const drafts = store();
  const rpc = api();
  const first = harness(rpc, drafts);
  first.edit('  다음 작업부터 순서를 바꿔줘\n원문 유지  ');
  first.unmount();
  const other = harness(rpc, drafts, { projectName: 'other' });
  assert.equal(other.message(), '');
  other.edit('다른 프로젝트 요청');
  const anotherGroup = harness(rpc, drafts, { run: run({ id: 'other-group' }) });
  assert.equal(anotherGroup.message(), '');
  const returned = harness(rpc, drafts);
  assert.equal(returned.message(), '  다음 작업부터 순서를 바꿔줘\n원문 유지  ');
  assert.equal(other.message(), '다른 프로젝트 요청');
  assert.match(renderToStaticMarkup(returned.render()), /미전송 초안/);
  assert.equal(rpc.calls.length, 0);
  other.unmount(); anotherGroup.unmount(); returned.unmount();
});

test('rapid clicks and remount while pending share one request and settle the original draft', async () => {
  const drafts = store();
  const rpc = api();
  const first = harness(rpc, drafts);
  first.edit('접수할 요청');
  const button = send(first.render());
  button.props.onClick(); button.props.onClick();
  assert.equal(rpc.calls.length, 1);
  assert.equal(rpc.calls[0].method, 'runs.requestDirectionChange');
  first.unmount();
  const detachedNotifications = first.notificationCount();
  const returned = harness(rpc, drafts);
  const tree = returned.render();
  assert.equal(send(tree).props.disabled, true);
  assert.match(renderToStaticMarkup(tree), /전송 결과 확인 중/);
  send(tree).props.onClick();
  assert.equal(rpc.calls.length, 1);
  rpc.calls[0].resolve(accepted(rpc.calls[0].params));
  await tick();
  assert.equal(returned.message(), '');
  assert.match(renderToStaticMarkup(returned.render()), /요청 접수 확인 · 접수할 요청/);
  assert.equal(drafts.read('project', 'group').busy, false);
  assert.equal(first.notificationCount(), detachedNotifications);
  assert.equal(first.acceptedCalls.length, 0, 'an unmounted panel cannot refresh the visible run');
  returned.unmount();
});

test('confirmed receipt is distinct from application and fresh server history supplies the actual status', async () => {
  const drafts = store();
  const rpc = api();
  const fixture = harness(rpc, drafts);
  fixture.edit('반영할 요청');
  send(fixture.render()).props.onClick();
  const result = accepted(rpc.calls[0].params);
  rpc.calls[0].resolve(result);
  await tick();
  const receiptMarkup = renderToStaticMarkup(fixture.render());
  assert.match(receiptMarkup, /요청 접수 확인 · 반영할 요청/);
  assert.doesNotMatch(receiptMarkup, /반영 완료/);
  const refreshed = { ...result, direction_change_requests: [{ ...result.direction_change_requests[0], status: 'applied' }] };
  const freshMarkup = renderToStaticMarkup(fixture.render({ run: refreshed }));
  assert.match(freshMarkup, /반영 완료/);
  assert.doesNotMatch(freshMarkup, /요청 접수 확인 ·/);
  fixture.unmount();
});

test('successful acceptance keeps new text written while the original request was pending', async () => {
  const drafts = store();
  const rpc = api();
  const fixture = harness(rpc, drafts);
  fixture.edit('원래 요청');
  send(fixture.render()).props.onClick();
  fixture.edit('접수 중 추가한 새 초안');
  assert.match(renderToStaticMarkup(fixture.render()), /전송한 요청 · 원래 요청/);
  rpc.calls[0].resolve(accepted(rpc.calls[0].params));
  await tick();
  assert.equal(fixture.message(), '접수 중 추가한 새 초안');
  assert.equal(fixture.acceptedCalls.length, 1);
  assert.equal(send(fixture.render()).props.disabled, false);
  fixture.unmount();
});

test('editing and then restoring identical text during submission does not erase a new draft', () => {
  const drafts = store();
  drafts.edit('project', 'group', '내용');
  const pending = drafts.begin('project', 'group');
  drafts.edit('project', 'group', '내용 수정');
  drafts.edit('project', 'group', '내용');
  assert.equal(drafts.confirm('project', 'group', pending.requestId,
    accepted({ runId: 'group', requestId: pending.requestId, text: pending.text })), true);
  assert.equal(drafts.read('project', 'group').text, '내용');
});

test('uncertain receipt and same-content retry survive navigation and use the same request ID', async () => {
  const drafts = store();
  const rpc = api();
  const first = harness(rpc, drafts);
  first.edit('  원래 요청  ');
  send(first.render()).props.onClick();
  first.unmount();
  rpc.calls[0].reject(new Error('RPC 결과 수신 실패'));
  await tick();
  const returned = harness(rpc, drafts);
  assert.equal(returned.message(), '  원래 요청  ');
  assert.match(renderToStaticMarkup(returned.render()), /접수 확인 필요/);
  assert.match(renderToStaticMarkup(returned.render()), /RPC 결과 수신 실패/);
  returned.edit('원래 요청\n');
  send(returned.render()).props.onClick();
  assert.equal(rpc.calls.length, 2);
  assert.equal(rpc.calls[1].params.requestId, rpc.calls[0].params.requestId);
  assert.equal(rpc.calls[1].params.text, '원래 요청');
  rpc.calls[1].resolve(accepted(rpc.calls[1].params));
  await tick();
  assert.equal(returned.message(), '');
  assert.doesNotMatch(renderToStaticMarkup(returned.render()), /role="alert"/);
  returned.unmount();
});

test('changed content gets a new ID and older receipts and errors cannot clear the newer request', () => {
  const drafts = store();
  drafts.edit('project', 'group', '원래 요청');
  const first = drafts.begin('project', 'group');
  drafts.fail('project', 'group', first.requestId, '수신 실패');
  drafts.edit('project', 'group', '다른 요청');
  const second = drafts.begin('project', 'group');
  assert.notEqual(second.requestId, first.requestId);
  assert.equal(drafts.confirm('project', 'group', first.requestId,
    accepted({ runId: 'group', requestId: first.requestId, text: first.text })), false);
  drafts.fail('project', 'group', first.requestId, '늦은 실패');
  assert.equal(drafts.read('project', 'group').text, '다른 요청');
  assert.equal(drafts.read('project', 'group').busy, true);
  assert.equal(drafts.read('project', 'group').error, '');
});

test('polling a matching receipt confirms acceptance without letting a late RPC error undo it', async () => {
  const drafts = store();
  const rpc = api();
  const fixture = harness(rpc, drafts);
  fixture.edit('요청');
  send(fixture.render()).props.onClick();
  fixture.render({ run: accepted(rpc.calls[0].params) });
  assert.equal(fixture.message(), '');
  assert.equal(drafts.read('project', 'group').busy, false);
  rpc.calls[0].reject(new Error('늦은 수신 실패'));
  await tick();
  assert.equal(drafts.read('project', 'group').error, '');
  assert.equal(fixture.acceptedCalls.length, 0);
  fixture.unmount();
});

test('polling without a receipt preserves pending state and failures instead of inventing success', () => {
  const drafts = store();
  drafts.edit('project', 'group', '요청');
  const pending = drafts.begin('project', 'group');
  drafts.reconcile('project', run());
  assert.equal(drafts.read('project', 'group').busy, true);
  drafts.fail('project', 'group', pending.requestId, '조회 불명');
  drafts.reconcile('project', run({ stage: 'failed' }));
  assert.equal(drafts.read('project', 'group').text, '요청');
  assert.equal(drafts.read('project', 'group').error, '조회 불명');
  assert.equal(drafts.read('project', 'group').pending.requestId, pending.requestId);
});

test('wrong run, missing receipt, wrong ID, and changed receipt text remain visible failures', async () => {
  for (const change of [
    (result) => ({ ...result, id: 'other' }),
    (result) => ({ ...result, direction_change_requests: [] }),
    (result) => ({ ...result, direction_change_requests: [{ ...result.direction_change_requests[0], request_id: 'other-id' }] }),
    (result) => ({ ...result, direction_change_requests: [{ ...result.direction_change_requests[0], text: '변조된 내용' }] }),
  ]) {
    const drafts = store();
    const rpc = api();
    const fixture = harness(rpc, drafts);
    fixture.edit('요청');
    send(fixture.render()).props.onClick();
    rpc.calls[0].resolve(change(accepted(rpc.calls[0].params)));
    await tick();
    assert.equal(fixture.message(), '요청');
    assert.equal(drafts.read('project', 'group').busy, false);
    assert.match(renderToStaticMarkup(fixture.render()), /접수 기록이 요청과 일치하지 않습니다/);
    assert.equal(fixture.acceptedCalls.length, 0);
    fixture.unmount();
  }
});

test('a malformed polling receipt keeps the original request and explains the mismatch', () => {
  const drafts = store();
  drafts.edit('project', 'group', '원문');
  const pending = drafts.begin('project', 'group');
  drafts.reconcile('project', accepted({ runId: 'group', requestId: pending.requestId, text: '다른 원문' }));
  assert.equal(drafts.read('project', 'group').text, '원문');
  assert.equal(drafts.read('project', 'group').pending.requestId, pending.requestId);
  assert.match(drafts.read('project', 'group').error, /일치하지 않습니다/);
});

test('late success after scope change settles only its own project and cannot refresh another run', async () => {
  const drafts = store();
  const rpc = api();
  const fixture = harness(rpc, drafts);
  fixture.edit('프로젝트 A');
  send(fixture.render()).props.onClick();
  fixture.render({ projectName: 'other' }); fixture.edit('프로젝트 B');
  rpc.calls[0].resolve(accepted(rpc.calls[0].params));
  await tick();
  assert.equal(fixture.message(), '프로젝트 B');
  assert.equal(drafts.read('project', 'group').text, '');
  assert.equal(fixture.acceptedCalls.length, 0);
  fixture.unmount();
});

test('leaving execution keeps drafts readable and stale send handlers cannot submit', () => {
  const drafts = store();
  const rpc = api();
  const fixture = harness(rpc, drafts);
  fixture.edit('남은 초안');
  const staleButton = send(fixture.render());
  const tree = fixture.render({ run: run({ stage: 'verified' }) });
  assert.equal(fixture.message(), '남은 초안');
  assert.equal(input(tree), undefined, 'the shared Planning AI composer owns the input');
  assert.equal(send(tree), undefined);
  staleButton.props.onClick();
  assert.equal(rpc.calls.length, 0);
  assert.match(renderToStaticMarkup(tree), /현재 단계에서는 새 요청을 접수할 수 없습니다/);
  fixture.unmount();
  staleButton.props.onClick();
  assert.equal(rpc.calls.length, 0);
});


test('saved discussion is submitted only by explicit request with no separate direction input', async () => {
  const drafts = store(); const rpc = api();
  let discussed = 0;
  const fixture = harness(rpc, drafts, { run: run({ planning_messages: [
    {role: 'user', text: '실패한 테스트만 수정해줘'}, {role: 'assistant', text: '검증 순서도 유지하겠습니다'}
  ] }), onDiscuss: () => discussed++ });
  const tree = fixture.render();
  assert.equal(input(tree), undefined);
  assert.equal(rpc.calls.length, 0);
  find(tree, item => item.type === 'button' && item.props.children === '대화로 변경 논의').props.onClick();
  assert.equal(discussed, 1); assert.equal(rpc.calls.length, 0);
  send(tree).props.onClick();
  assert.equal(rpc.calls[0].method, 'runs.requestDirectionChange');
  assert.equal(rpc.calls[0].params.text, '실패한 테스트만 수정해줘');
  rpc.calls[0].resolve(accepted(rpc.calls[0].params)); await tick();
  assert.equal(fixture.message(), ''); fixture.unmount();
});

test('a backend length rejection preserves the common composer text without truncating or applying', async () => {
  const drafts = store(); const rpc = api(); const fixture = harness(rpc, drafts);
  const text = '원'.repeat(4001); fixture.render(); fixture.edit(text);
  send(fixture.render()).props.onClick();
  assert.equal(rpc.calls[0].params.text, text);
  rpc.calls[0].reject(new Error('4000자 제한')); await tick();
  assert.equal(fixture.message(), text);
  assert.match(renderToStaticMarkup(fixture.render()), /4000자 제한/);
  assert.equal(fixture.acceptedCalls.length, 0); fixture.unmount();
});
