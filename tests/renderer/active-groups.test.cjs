const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'active-groups-')));
process.on('exit', () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
});
const packagePath = require.resolve('typescript/package.json', { paths: [root] });
const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022', '--module', 'commonjs',
  '--skipLibCheck', '--outDir', output, 'desktop/renderer/src/activeGroups.ts', 'desktop/renderer/src/types.ts'],
{ cwd: root, stdio: 'inherit' });
const { reconcileActiveGroups, visibleActiveGroups, confirmedActiveGroupCount, activeGroupActivityLabel } =
  require(join(output, 'activeGroups.js'));

function group(project_name, run_id, overrides = {}) {
  return {
    project_name, run_id, title: `${project_name} work`, stage: 'executing', status: 'active',
    completed_task_count: 1, task_count: 2, activity_kinds: ['task'],
    last_activity_at: '2026-09-29T00:00:00+00:00', checked_at: '2026-09-29T00:00:00+00:00', ...overrides,
  };
}

test('same run ID in two projects stays distinct and search includes project name', () => {
  const snapshot = { items: [group('Sample Project A', 'shared'), group('Sample Project B', 'shared')], errors: [], checked_at: '' };
  assert.equal(confirmedActiveGroupCount(snapshot), 2);
  assert.deepEqual(visibleActiveGroups(snapshot, 'project b').map((item) => [item.project_name, item.run_id]),
    [['Sample Project B', 'shared']]);
  assert.equal(activeGroupActivityLabel(snapshot.items[0]), 'Task 실행 중');
});

test('failed project preserves its last card as uncertain without counting it active', () => {
  const previous = { items: [group('Sample Project A', 'one'), group('Sample Project B', 'two')], errors: [], checked_at: 'earlier' };
  const incoming = { items: [group('Sample Project B', 'two', { activity_kinds: ['planning'] })],
    errors: [{ project_name: 'Sample Project A', error: 'read failed', checked_at: 'now' }], checked_at: 'now' };
  const result = reconcileActiveGroups(previous, incoming);

  assert.equal(confirmedActiveGroupCount(result), 1);
  const failed = result.items.find((item) => item.project_name === 'Sample Project A');
  assert.equal(failed.status, 'check_required');
  assert.equal(failed.stale, true);
  assert.equal(activeGroupActivityLabel(failed), '상태 확인 필요');
  assert.equal(activeGroupActivityLabel(result.items.find((item) => item.project_name === 'Sample Project B')), '기획 작업 중');
});
