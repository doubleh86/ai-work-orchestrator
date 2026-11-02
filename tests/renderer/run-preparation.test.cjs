const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');
const root = resolve(__dirname, '../..');
const tempRoot = join(root, '.tmp');
mkdirSync(tempRoot, { recursive: true });
const output = mkdtempSync(join(tempRoot, 'run-preparation-'));
process.on('exit', () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); });
const ts = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(ts), require(ts).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
  'desktop/renderer/src/RunPreparation.tsx'], { cwd: root, stdio: 'inherit' });
const file = join(output, 'RunPreparation.js');
const localRequire = createRequire(file);
function nodes(tree) {
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return tree && typeof tree === 'object' ? [tree, ...nodes(tree.props?.children)] : [];
}
function text(tree) {
  if (typeof tree === 'string' || typeof tree === 'number') return String(tree);
  return Array.isArray(tree) ? tree.map(text).join('') : tree ? text(tree.props?.children) : '';
}
function harness(changes = {}) {
  const values = [], effects = [], calls = [], exports = {};
  let cursor = 0, pending = [], changed = false;
  const react = { ...localRequire('react'),
    useState(initial) { const index = cursor++; if (!(index in values)) values[index] = initial; return [values[index], value => { values[index] = typeof value === 'function' ? value(values[index]) : value; changed = true; }]; },
    useRef(current) { const index = cursor++; return values[index] ||= { current }; },
    useId() { return 'preparation-editor'; },
    useEffect(callback, deps) { const index = cursor++; if (!effects[index] || deps.some((value, i) => value !== effects[index][i])) pending.push(callback); effects[index] = deps; },
  };
  runInNewContext(readFileSync(file, 'utf8'), { exports, require: name => name === 'react' ? react : localRequire(name), window: { requestAnimationFrame: callback => callback() } });
  const tasks = Array.from({ length: 6 }, (_, i) => ({ id: `task-${i}`, title: `작업 ${i + 1}`, status: 'pending' }));
  const props = { run: { id: 'group', summary: '실행 전 계획', stage: 'planned', tasks },
    action: { kind: 'execute', status: '작업 그룹 실행 가능', label: '작업 시작', description: '실행합니다', disabled: false },
    busy: false, blocked: false, planDirty: false, draftConflict: false, draftErrorCount: 0, invalidTaskIds: [],
    profileSummary: task => task.id + ' model', profileEditor: task => react.createElement('select', { 'data-task': task.id }),
    onAction: action => calls.push(action.kind), onReset: () => calls.push('reset'), onReviewErrors: () => calls.push('errors'),
    onOpenTask: id => calls.push(id), onDiscuss: () => calls.push('chat'), ...changes };
  let tree;
  const render = () => {
    do { changed = false; cursor = 0; pending = []; tree = exports.RunPreparation(props); pending.forEach(effect => effect()); } while (changed);
    return tree;
  };
  const button = label => nodes(tree).find(node => node.type === 'button' && text(node) === label);
  render();
  return { props, calls, render, button, get tree() { return tree; } };
}

test('unavailable models replace start and open only the affected tasks without invoking execution', () => {
  const h = harness({ invalidTaskIds: ['task-0', 'task-4'] });
  assert.deepEqual(h.calls, []); assert.equal(h.button('작업 시작'), undefined);
  h.button('실행 AI 확인').props.onClick(); h.render();
  assert.deepEqual(nodes(h.tree).filter(node => node.type === 'select').map(node => node.props['data-task']), ['task-0', 'task-4']);
  assert.deepEqual(h.calls, []);
  const rows = nodes(h.tree).filter(node => node.props.className === 'run-preparation__task');
  assert.ok(rows.some(node => text(node).includes('작업 5')));
  const folded = nodes(h.tree).find(node => node.props.className === 'run-preparation__remaining');
  assert.equal(folded.props.open, undefined);
  assert.doesNotMatch(text(folded), /작업 5/);
});

test('model edits survive save failure; explicit confirmation and execution remain separate actions', () => {
  const h = harness({ invalidTaskIds: ['task-0'] });
  h.button('실행 AI 확인').props.onClick(); h.render();
  Object.assign(h.props, { invalidTaskIds: [], planDirty: true, action: { ...h.props.action, kind: 'confirm_plan', label: '변경 저장하고 계획 확정' } }); h.render();
  h.button('변경 저장하고 계획 확정').props.onClick();
  assert.deepEqual(h.calls, ['confirm_plan']);
  h.props.busy = true; h.render(); assert.equal(h.button('처리 중').props.disabled, true);
  h.props.busy = false; h.render();
  assert.equal(nodes(h.tree).filter(node => node.type === 'select').length, 1, 'a failed save must keep the editor and draft');
  Object.assign(h.props, { planDirty: false, action: { ...h.props.action, kind: 'execute', label: '작업 시작' } }); h.render();
  assert.equal(nodes(h.tree).filter(node => node.type === 'select').length, 0);
  assert.deepEqual(h.calls, ['confirm_plan'], 'saving never starts work automatically');
  h.button('작업 시작').props.onClick(); assert.deepEqual(h.calls, ['confirm_plan', 'execute']);
});

test('busy, conflicting, locked, disabled and empty plans cannot start through the primary action', () => {
  for (const change of [{ busy: true }, { draftConflict: true, planDirty: true }, { blocked: true },
    { planDirty: true }, { action: { kind: 'execute', label: '작업 시작', disabled: true } }, { run: { summary: '빈 계획', tasks: [] } }]) {
    const h = harness(change);
    const button = nodes(h.tree).find(node => node.type === 'button' && node.props.className === 'button button--primary');
    if (button) { assert.equal(button.props.disabled, true); button.props.onClick(); }
    assert.deepEqual(h.calls, [], JSON.stringify(change));
  }
});

test('a stale execute action cannot bypass plan revision or effort review requirements', () => {
  for (const changes of [{ plan_revision: 3, plan_approved_revision: 2 }, { effort_control: { requires_plan_review: true } }]) {
    const h = harness(); Object.assign(h.props.run, changes); h.render();
    assert.equal(h.button('작업 시작').props.disabled, true); h.button('작업 시작').props.onClick();
    assert.deepEqual(h.calls, []);
  }
});

test('validation failures reveal the existing task editor rather than confirming or starting', () => {
  const h = harness({ draftErrorCount: 2, planDirty: true });
  h.button('입력 오류 확인').props.onClick(); assert.deepEqual(h.calls, ['errors']);
  h.button('변경 취소').props.onClick(); assert.deepEqual(h.calls, ['errors', 'reset']);
});

test('effort review opens execution settings before invoking the existing comparison flow', () => {
  const h = harness({ action: { kind: 'effort', status: '작업 강도 확인', label: '변경 비교', description: '', disabled: false } });
  const settings = nodes(h.tree).find(node => node.props.className === 'run-preparation__settings');
  const element = { open: false }; settings.props.ref.current = element;
  h.props.onAction = action => { assert.equal(element.open, true); h.calls.push(action.kind); };
  h.render(); h.button('변경 비교').props.onClick(); assert.deepEqual(h.calls, ['effort']);
});

test('task details and chat return use their own callbacks without submitting work', () => {
  const h = harness();
  nodes(h.tree).find(node => node.props.className === 'run-preparation__task-copy').props.onClick();
  h.button('채팅에서 이야기하기').props.onClick(); assert.deepEqual(h.calls, ['task-0', 'chat']);
});

test('bulk editing includes pending tasks only and remains a deliberate settings action', () => {
  const h = harness(); h.props.run.tasks[1].status = 'completed'; h.render();
  assert.equal(nodes(h.tree).filter(node => node.type === 'select').length, 0);
  h.button('작업별 실행 AI 편집').props.onClick(); h.render();
  const ids = nodes(h.tree).filter(node => node.type === 'select').map(node => node.props['data-task']);
  assert.equal(ids.length, 5); assert.ok(!ids.includes('task-1')); assert.deepEqual(h.calls, []);
});
