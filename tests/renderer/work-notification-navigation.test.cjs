const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'work-notification-navigation-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/workNotificationNavigation.ts', 'desktop/shared/workNotifications.ts'],
  { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const { notificationNavigation } = require(join(output, 'renderer/src/workNotificationNavigation.js'));

test('notification targets open their read-only workbench context', () => {
  assert.deepEqual(notificationNavigation({ target_kind: 'planning', target_id: 'run', summary_code: 'plan_confirmation_required' }),
    { view: 'planning', taskId: '', inspector: 'detail' });
  assert.deepEqual(notificationNavigation({ target_kind: 'conflict', target_id: 'conflict', summary_code: 'integration_conflict' }),
    { view: 'operations', taskId: '', inspector: 'detail' });
  assert.deepEqual(notificationNavigation({ target_kind: 'task', target_id: 'task-1', summary_code: 'task_failed' }),
    { view: 'tasks', taskId: 'task-1', inspector: 'log' });
  assert.deepEqual(notificationNavigation({ target_kind: 'task', target_id: 'task-1', summary_code: 'task_completed' }),
    { view: 'results', taskId: 'task-1', inspector: 'detail' });
  assert.deepEqual(notificationNavigation({ target_kind: 'operations', target_id: 'run', summary_code: 'group_completed' }),
    { view: 'results', taskId: '', inspector: 'detail' });
});
