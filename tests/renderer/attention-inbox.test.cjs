const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(root, '.tmp');
mkdirSync(tempRoot, { recursive: true });
const output = resolve(mkdtempSync(join(tempRoot, 'attention-inbox-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/AttentionInbox.tsx'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);
const { attentionItemKey, reconcileAttentionItems, confirmedAttentionCount, uncertainAttentionSnapshot, attentionNavigation } =
  require(join(output, 'attentionInboxPresentation.js'));
const { AttentionInbox, AttentionInboxTrigger } = require(join(output, 'AttentionInbox.js'));
const { createElement } = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

function item(project_name, overrides = {}) {
  return { project_name, run_id: 'same', run_title: '작업', stage: 'needs_clarification', kind: 'planning_questions',
    title: '기획 질문에 답변', reason: '질문에 답변해야 합니다.', view: 'planning', task_id: '',
    status: 'actionable', updated_at: '2026-09-30T00:00:00Z', checked_at: '2026-09-30T00:00:00Z', ...overrides };
}
function snapshot(items = [], errors = []) { return { items, errors, checked_at: '2026-09-30T00:00:00Z' }; }
function run(overrides = {}) {
  return { id: 'same', stage: 'planned', plan_revision: 1, plan_approved_revision: 1, tasks: [],
    execution_control: { situation: 'ready', action: 'execute', reason: '준비', lock_state: 'unlocked' }, ...overrides };
}

test('same run IDs in different projects are distinct and duplicate decisions count once', () => {
  const incoming = snapshot([item('first'), item('second'), item('first')]);
  const result = reconcileAttentionItems(snapshot(), incoming);
  assert.equal(confirmedAttentionCount(result), 2);
  assert.notEqual(attentionItemKey(item('first')), attentionItemKey(item('second')));
});

test('resolved groups disappear while failed projects retain uncertain prior items', () => {
  const previous = snapshot([item('resolved'), item('broken'), item('current')]);
  const result = reconcileAttentionItems(previous, snapshot([item('current')], [
    { project_name: 'broken', error: 'read denied', checked_at: 'now' },
  ]));
  assert.equal(confirmedAttentionCount(result), 1);
  assert.equal(result.items.some((entry) => entry.project_name === 'resolved'), false);
  assert.equal(result.items.find((entry) => entry.project_name === 'broken').stale, true);
  assert.equal(confirmedAttentionCount(uncertainAttentionSnapshot(result)), 0);
});

test('navigation uses fresh stage and does not select a removed task', () => {
  const stale = item('first');
  assert.deepEqual(attentionNavigation(stale, run()), { view: 'tasks', taskId: '', changed: true });
  assert.deepEqual(attentionNavigation(item('first', { stage: 'planned', task_id: 'deleted', view: 'tasks' }), run()),
    { view: 'tasks', taskId: '', changed: false });
  const latest = run({ stage: 'needs_clarification' });
  assert.deepEqual(attentionNavigation(stale, latest), { view: 'planning', taskId: '', changed: false });
  assert.equal(attentionNavigation(item('first', { stale: true }), latest).changed, true);
  assert.deepEqual(attentionNavigation(item('first', { kind: 'status_check', status: 'check_required', view: 'operations' }), latest),
    { view: 'operations', taskId: '', changed: true });
});

test('inbox renders lookup errors and uncertain items without claiming an empty success', () => {
  const html = renderToStaticMarkup(createElement(AttentionInbox, {
    snapshot: snapshot([item('broken', { status: 'check_required', stale: true })], [
      { project_name: 'broken', error: 'read denied', checked_at: 'now' },
    ]), loading: false, error: '', onClose() {}, onRefresh() {}, onOpen() {},
  }));
  assert.match(html, /처리할 일/);
  assert.doesNotMatch(html, /처리할 일 0개/);
  assert.match(html, /상태 확인 필요 1개/);
  assert.match(html, /read denied/);
  assert.match(html, /이전 조회 결과/);
  assert.doesNotMatch(html, /미해결 항목이 없습니다/);
  assert.equal((html.match(/>닫기</g) || []).length, 1);
});

test('initial load failure remains distinct from a confirmed empty inbox', () => {
  const render = (error, checked_at) => renderToStaticMarkup(createElement(AttentionInbox, {
    snapshot: { items: [], errors: [], checked_at }, loading: false, error, onClose() {}, onRefresh() {}, onOpen() {},
  }));
  assert.match(render('', '2026-09-30T00:00:00Z'), /미해결 항목이 없습니다/);
  assert.doesNotMatch(render('backend unavailable', ''), /미해결 항목이 없습니다/);
  assert.match(render('backend unavailable', ''), /조회하지 못했습니다/);
});

test('sidebar counts are definite only for a fully confirmed inbox and never pair zero with an uncertainty warning', () => {
  const render = (state, error = '') => renderToStaticMarkup(createElement(AttentionInboxTrigger, {
    snapshot: state, error, open: false, buttonRef: { current: null }, onClick() {},
  }));
  const empty = render(snapshot());
  assert.match(empty, /확인할 일 0개/);
  assert.doesNotMatch(empty, /attention-inbox__warning/);
  const current = render(snapshot([item('first'), item('second')]));
  assert.match(current, /확인할 일 2개/);
  assert.doesNotMatch(current, /attention-inbox__warning/);
  for (const [state, error, expected] of [
    [{ items: [], errors: [], checked_at: '' }, '', '미확인'],
    [snapshot([item('unknown', { status: 'check_required' })]), '', '상태 미확인'],
    [snapshot([item('old', { stale: true })]), '', '상태 미확인'],
    [snapshot(), 'backend unavailable', '조회 실패'],
    [snapshot([], [{ project_name: 'broken', error: 'read denied' }]), '', '일부 조회 실패'],
  ]) {
    const html = render(state, error);
    assert.match(html, new RegExp(expected));
    assert.doesNotMatch(html, /0개/);
    assert.match(html, /aria-haspopup="dialog"/);
  }
  const partial = render(snapshot([item('current'), item('old', { stale: true })]));
  assert.match(partial, /확인된 일 1개/);
  assert.match(partial, /상태 미확인/);
  const failedProject = render(snapshot([item('current')], [{ project_name: 'broken', error: 'read denied' }]));
  assert.match(failedProject, /확인된 일 1개/);
  assert.match(failedProject, /일부 조회 실패/);
});

test('sidebar trigger preserves its opener reference and dialog interaction without initiating requests on render', () => {
  const buttonRef = { current: null };
  let opened = 0;
  const tree = AttentionInboxTrigger({ snapshot: snapshot(), error: '', open: true, buttonRef, onClick: () => { opened += 1; } });
  assert.equal(tree.props.ref, buttonRef);
  assert.equal(tree.props['aria-expanded'], true);
  assert.equal(tree.props['aria-haspopup'], 'dialog');
  assert.equal(opened, 0);
  tree.props.onClick();
  assert.equal(opened, 1);
});
