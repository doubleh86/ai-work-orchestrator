const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'workspace-location-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/workspaceLocation.ts', 'desktop/renderer/src/types.ts'],
    { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const { runWorkspacePresentation } = require(join(output, 'workspaceLocation.js'));
const run = (overrides = {}) => ({
  id: 'group-1', repo_path: 'C:\\Project', workspace_mode: 'shared',
  execution_worktree: '', tasks: [], ...overrides,
});

test('new group displays its fixed workspace as planned before creation', () => {
  assert.deepEqual(runWorkspacePresentation(run({
    workspace_location: { root: 'C:\\Project\\.ai_auto_work\\worktree', source: 'project_default', layout_version: 2 },
  })), { path: 'C:\\Project\\.ai_auto_work\\worktree\\group-1', status: '생성 예정' });
});

test('prepared group displays the actual shared workspace', () => {
  assert.deepEqual(runWorkspacePresentation(run({
    execution_worktree: 'D:\\custom\\group-1\\work',
  })), { path: 'D:\\custom\\group-1\\work', status: '기록된 경로' });
});

test('legacy isolated group derives the group directory from a recorded task', () => {
  assert.deepEqual(runWorkspacePresentation(run({
    workspace_mode: 'isolated',
    tasks: [{ worktree: 'D:\\legacy\\group-1\\task-1' }],
  })), { path: 'D:\\legacy\\group-1', status: '기록된 경로' });
});

test('group without any location record is explicit', () => {
  assert.deepEqual(runWorkspacePresentation(run()), { path: '', status: '기록 없음' });
});

const shared = () => run({ execution_worktree: 'D:\\custom\\group-1\\work', updated_at: 'now', stage: 'merged' });
const snapshot = (group, workspaces, overrides = {}) => ({
  projectName: 'Fixture', runId: group.id, runUpdatedAt: group.updated_at,
  mainOperationsSignature: JSON.stringify(group.main_operations), status: 'ready', workspaces, ...overrides,
});
const workspace = (state, overrides = {}) => ({
  run_id: 'group-1', task_id: 'task-1', worktree: 'D:\\custom\\group-1\\work', state, ...overrides,
});

test('cleaned shared workspace keeps the recorded path and shows confirmed cleanup', () => {
  const group = shared();
  assert.deepEqual(runWorkspacePresentation(group, snapshot(group, [workspace('cleaned')]), 'Fixture'), {
    path: group.execution_worktree, status: '정리 완료',
  });
  for (const [state, label] of [['active', '정리 대기'], ['stale', '정리 가능'], ['unsafe', '정리 보류'], ['not_prepared', '미준비']]) {
    assert.equal(runWorkspacePresentation(group, snapshot(group, [workspace(state)]), 'Fixture').status, label);
  }
});

test('merged stage alone and stale, foreign or failed observations never prove cleanup', () => {
  const group = shared();
  assert.equal(runWorkspacePresentation(group).status, '기록된 경로');
  for (const overrides of [
    { projectName: 'Other' }, { runId: 'other' }, { runUpdatedAt: 'old' },
    { mainOperationsSignature: 'changed' }, { status: 'loading' }, { status: 'error' },
  ]) {
    assert.equal(runWorkspacePresentation(group, snapshot(group, [workspace('cleaned')], overrides), 'Fixture').status, '기록된 경로');
  }
});

test('missing, wrong-path, foreign and unknown workspace records remain explicit', () => {
  const group = shared();
  for (const workspaces of [[], [workspace('cleaned', { worktree: group.execution_worktree + '-other' })],
    [workspace('cleaned', { run_id: 'other' })], [workspace('future-state')]]) {
    assert.equal(runWorkspacePresentation(group, snapshot(group, workspaces), 'Fixture').status, '상태 확인 필요');
  }
  assert.equal(runWorkspacePresentation(group, snapshot(group, [workspace('cleaned', {
    worktree: 'd:/CUSTOM/group-1/work/',
  })]), 'Fixture').status, '정리 완료');
});

test('legacy isolated group is cleaned only when all recorded task workspaces are confirmed', () => {
  const group = run({ workspace_mode: 'isolated', updated_at: 'now', tasks: [
    { worktree: 'D:\\legacy\\group-1\\task-1' }, { worktree: 'D:\\legacy\\group-1\\task-2' },
  ] });
  const first = workspace('cleaned', { worktree: group.tasks[0].worktree });
  const second = workspace('cleaned', { worktree: group.tasks[1].worktree, task_id: 'task-2' });
  assert.equal(runWorkspacePresentation(group, snapshot(group, [first, second]), 'Fixture').status, '정리 완료');
  assert.equal(runWorkspacePresentation(group, snapshot(group, [first]), 'Fixture').status, '상태 확인 필요');
  assert.equal(runWorkspacePresentation(group, snapshot(group, [first, { ...second, state: 'active' }]), 'Fixture').status, '일부 정리');
  assert.equal(runWorkspacePresentation(group, snapshot(group, [first, { ...second, state: 'unsafe' }]), 'Fixture').status, '정리 보류');
});
