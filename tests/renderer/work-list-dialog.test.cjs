const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');
const root = resolve(__dirname, '../..'), temp = join(root, '.tmp');
mkdirSync(temp, { recursive: true });
const output = mkdtempSync(join(temp, 'work-list-dialog-'));
process.on('exit', () => { assert.equal(dirname(output), temp); rmSync(output, { recursive: true, force: true }); });
const pkg = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(pkg), require(pkg).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
  'desktop/renderer/src/App.tsx', 'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });
const path = join(output, 'renderer/src/App.js'), local = createRequire(path);
function fixture() {
  const refs = [], result = {}, effects = [], frames = new Map();
  let index = 0, frameId = 0;
  runInNewContext(readFileSync(path, 'utf8') + '\nexports.WorkGroupPane=WorkGroupPane;', {
    exports: result, require: name => name === 'react' ? { ...local(name),
      useRef(value) { const i = index++; return refs[i] ||= { current: value }; },
      useLayoutEffect(callback) { effects.push(callback); },
    } : local(name), window: {
      requestAnimationFrame(callback) { frames.set(++frameId, callback); return frameId; },
      cancelAnimationFrame(id) { frames.delete(id); },
    },
  });
  return { refs, render(extra = {}) { index = 0; effects.length = 0; return result.WorkGroupPane(props(extra)); },
    show() { effects.forEach(callback => callback()); [...frames.values()].forEach(callback => callback()); frames.clear(); } };
}
function props(extra = {}) {
  return { visible: true, runs: [], mode: 'project', globalGroups: [], globalCount: 0, globalErrorCount: 0,
    globalErrors: [], globalError: '', globalLoading: false, globalSearch: '', selectedProjectName: '프로젝트 A',
    scope: 'active', selectedRunId: '', search: '', statusFilter: 'all', statusCounts: {}, totalRunCount: 0,
    loading: false, deletingRunId: '', archivingRunId: '', ...extra };
}
const run = (id, stage = 'planned') => ({ id, summary: `작업 ${id}`, stage, task_count: 2, completed_task_count: 0,
  updated_at: '2026-10-10T00:00:00Z' });
function nodes(tree) { if (!tree || typeof tree !== 'object') return []; return Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)]; }
function text(tree) { if (typeof tree === 'string' || typeof tree === 'number') return String(tree); return Array.isArray(tree) ? tree.map(text).join('') : text(tree?.props?.children || ''); }
const button = (tree, label) => nodes(tree).find(node => node.type === 'button' && text(node) === label);

test('list owns one new-plan action and preserves its project target and both query scopes', () => {
  const calls = [], tree = fixture().render({ onNewPlanning: () => calls.push('new'), onModeChange: mode => calls.push(mode) });
  assert.equal(nodes(tree).filter(node => node.type === 'h2').length, 0);
  assert.equal(nodes(tree).filter(node => node.type === 'button' && text(node) === '새 계획').length, 1);
  assert.match(text(tree), /새 계획 대상 · 프로젝트 A/);
  button(tree, '새 계획').props.onClick();
  nodes(tree).find(node => node.props.role === 'tab' && text(node).startsWith('모든 프로젝트')).props.onClick();
  button(tree, '프로젝트별').props.onClick();
  assert.deepEqual(calls, ['new', 'global', 'project']);
  assert.equal(button(fixture().render({ selectedProjectName: '' }), '새 계획').props.disabled, true);
});

test('project and global refresh keep separate callbacks and loading state', () => {
  let project = 0, global = 0;
  const callbacks = { onRefreshProject() { project++; }, onRefreshGlobal() { global++; } };
  button(fixture().render(callbacks), '새로고침').props.onClick();
  button(fixture().render({ ...callbacks, mode: 'global' }), '새로고침').props.onClick();
  assert.equal(project, 1); assert.equal(global, 1);
  assert.equal(button(fixture().render({ loading: true }), '확인 중…').props.disabled, true);
  assert.equal(button(fixture().render({ mode: 'global', globalLoading: true }), '확인 중…').props.disabled, true);
});

test('selection passes the exact run or project-run pair without invoking list mutations', () => {
  const calls = [];
  const current = fixture().render({ runs: [run('same')], onSelectRun: id => calls.push(['run', id]),
    onDeleteRun() { throw new Error('automatic delete'); }, onArchiveRun() { throw new Error('automatic archive'); } });
  nodes(current).find(node => node.props.className === 'group-row__select').props.onClick();
  const global = fixture().render({ mode: 'global', globalGroups: [{ project_name: '프로젝트 B', run_id: 'same', title: '다른 프로젝트', status: 'active', activity_kinds: ['task'] }],
    onSelectGlobal: (project, id) => calls.push([project, id]) });
  nodes(global).find(node => node.props.className === 'group-row__select').props.onClick();
  assert.deepEqual(calls, [['run', 'same'], ['프로젝트 B', 'same']]);
});

test('current groups retain explicit archive/delete controls and archived groups offer neither', () => {
  const runs = [run('pending'), run('complete', 'pushed')], calls = [];
  const tree = fixture().render({ runs, onDeleteRun: id => calls.push(['delete', id]), onArchiveRun: id => calls.push(['archive', id]) });
  nodes(tree).find(node => node.props['aria-label'] === '작업 pending 작업 그룹 삭제').props.onClick();
  nodes(tree).find(node => node.props['aria-label'] === '작업 complete 작업 그룹 보관').props.onClick();
  assert.deepEqual(calls, [['delete', 'pending'], ['archive', 'complete']]);
  const pending = fixture().render({ runs, deletingRunId: 'pending', archivingRunId: 'complete' });
  assert.ok(nodes(pending).filter(node => /작업 그룹 (삭제|보관)$/.test(node.props['aria-label'] || '')).every(node => node.props.disabled));
  assert.equal(nodes(fixture().render({ runs, scope: 'archived' })).filter(node => /작업 그룹 (삭제|보관)$/.test(node.props['aria-label'] || '')).length, 0);
});

test('empty/filter states preserve selection and explicit resets instead of silently changing scope', () => {
  let resets = 0;
  const tree = fixture().render({ search: '없는 작업', totalRunCount: 12, selectedRunId: 'selected', onClearConditions() { resets++; } });
  assert.match(text(tree), /현재 그룹은 필터 밖/); assert.match(text(tree), /조건에 맞는 작업 그룹이 없습니다/);
  button(tree, '검색·필터 초기화').props.onClick(); assert.equal(resets, 1);
  assert.ok(nodes(fixture().render()).some(node => node.props.title === '아직 작업 그룹이 없습니다'));
  assert.ok(nodes(fixture().render({ scope: 'archived' })).some(node => node.props.title === '보관된 작업 그룹이 없습니다'));
  assert.equal(nodes(fixture().render({ loading: true })).find(node => node.props.className === 'group-list').props['aria-busy'], true);
});

test('global lookup errors retain previous groups and their original diagnostics', () => {
  const tree = fixture().render({ mode: 'global', globalError: '조회 실패 원문', globalErrorCount: 1,
    globalErrors: [{ project_name: '프로젝트 C', error: '상태 파일 오류' }],
    globalGroups: [{ project_name: '프로젝트 B', run_id: 'prior', title: '이전 작업', stale: true }] });
  assert.match(text(tree), /조회 실패 원문/); assert.match(text(tree), /상태 파일 오류/);
  assert.match(text(tree), /이전 작업/); assert.match(text(tree), /이전 확인/);
});

test('closing and reopening remembers scroll by mode/project/scope and ignores closed-list events', () => {
  const view = fixture(), scroller = { scrollTop: 0, closest: () => ({ open: true }) };
  let tree = view.render(); view.refs[0].current = scroller; view.show();
  const scroll = next => nodes(next).find(node => node.props.className === 'group-list').props.onScroll({ currentTarget: scroller });
  scroller.scrollTop = 140; scroll(tree);
  tree = view.render({ visible: false }); scroller.scrollTop = 0; scroll(tree); view.show();
  view.render(); view.show(); assert.equal(scroller.scrollTop, 140);
  tree = view.render({ scope: 'archived' }); view.show(); assert.equal(scroller.scrollTop, 0);
  scroller.scrollTop = 35; scroll(tree);
  view.render({ selectedProjectName: '프로젝트 B' }); view.show(); assert.equal(scroller.scrollTop, 0);
  view.render(); view.show(); assert.equal(scroller.scrollTop, 140);
  view.render({ scope: 'archived' }); view.show(); assert.equal(scroller.scrollTop, 35);
  tree = view.render(); view.show(); scroller.closest = () => ({ open: false }); scroller.scrollTop = 0; scroll(tree);
  view.render(); view.show(); assert.equal(scroller.scrollTop, 140);
});
