const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'task-queue-presentation-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/taskQueuePresentation.ts', 'desktop/renderer/src/types.ts'],
  { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const { blockedTaskFailureAction, pendingTaskActionIsAllowed, taskQueueHold, taskRetryIsAllowed } = require(join(output, 'taskQueuePresentation.js'));
const pending = (readiness = 'ready') => ({ status: 'pending', readiness });

test('confirmed plan does not become plan confirmation wait while another task runs', () => {
  assert.equal(taskQueueHold(pending(), true, false, 'running'), 'group_turn');
  assert.notEqual(taskQueueHold(pending(), true, false, 'running'), 'plan_confirmation');
});

test('only an unconfirmed plan is presented as plan confirmation wait', () => {
  assert.equal(taskQueueHold(pending(), false, false, 'ready'), 'plan_confirmation');
});

test('blocked task preserves its dependency readiness instead of group turn text', () => {
  assert.equal(taskQueueHold(pending('blocked'), true, false, 'running'), 'none');
});

test('interrupted group explains that pending task continues after resume', () => {
  assert.equal(taskQueueHold(pending(), true, false, 'resumable'), 'group_resume');
});

test('completed and running tasks never receive a pending hold label', () => {
  for (const status of ['running', 'completed', 'failed', 'waiting']) {
    assert.equal(taskQueueHold({ status, readiness: 'active' }, false, false, 'running'), 'none');
  }
});

test('individual retry is available only for agent execution failure', () => {
  assert.equal(taskRetryIsAllowed('runs.resume', 'agent_execution'), true);
  assert.equal(taskRetryIsAllowed('runs.resume', 'manual_completion'), false);
  assert.equal(taskRetryIsAllowed('runs.resume', 'verify'), false);
  assert.equal(taskRetryIsAllowed(undefined, 'agent_execution'), false);
});

test('failed group keeps pending task execution behind the group resume action', () => {
  assert.equal(pendingTaskActionIsAllowed('runs.execute', 'planned'), true);
  assert.equal(pendingTaskActionIsAllowed('runs.resume', 'executing'), true);
  assert.equal(pendingTaskActionIsAllowed('runs.resume', 'failed'), false);
});

test('unsupported failed task points to group recovery instead of execute or retry', () => {
  const action = blockedTaskFailureAction('failed', false);
  assert.equal(action.label, '그룹 복원 필요');
  assert.match(action.reason, /개별 작업 재시도를 지원하지 않습니다/);
  assert.equal(blockedTaskFailureAction('failed', true), undefined);
});
