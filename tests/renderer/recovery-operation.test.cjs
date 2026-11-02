const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'recovery-operation-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot, 'Test output must stay inside the temporary directory');
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/recoveryOperation.ts'],
  { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const recovery = require(join(output, 'recoveryOperation.js'));
const operation = (overrides = {}) => ({
  request_id: 'request', run_id: 'run', action: 'recovery_preview', digest: 'digest',
  phase: 'checking_failure', status: 'running', error: '', error_code: '', finished_at: '',
  result_revision: 0, result_commit: '', result_ref: '', resume_request_id: '',
  lock_state: 'unlocked',
  created_at: '2026-09-10T00:00:00Z', updated_at: '2026-09-10T00:00:05Z', result: null,
  ...overrides,
});

test('recovery phases distinguish failure inspection, source collection, and replanning', () => {
  assert.equal(recovery.recoveryPhaseLabel(operation()), '실패 원인 확인 중');
  assert.equal(recovery.recoveryPhaseLabel(operation({ phase: 'collecting_sources' })), '가져올 결과 확인 중');
  assert.equal(recovery.recoveryPhaseLabel(operation({ action: 'recovery_apply', phase: 'replanning' })), '남은 작업 재계획 중');
});

test('elapsed state marks 15 second delay and 60 second unconfirmed result', () => {
  assert.equal(recovery.recoveryDelayState(operation(), Date.parse('2026-09-10T00:00:14Z')), 'normal');
  assert.equal(recovery.recoveryDelayState(operation(), Date.parse('2026-09-10T00:00:15Z')), 'delayed');
  assert.equal(recovery.recoveryDelayState(operation(), Date.parse('2026-09-10T00:01:00Z')), 'unconfirmed');
  assert.equal(recovery.recoveryElapsedSeconds('2026-09-10T00:01:00Z', Date.parse('2026-09-10T00:00:00Z')), 0);
});

test('successful preview restores reviewed plan including an empty candidate result', () => {
  const plan = { run_id: 'run', fingerprint: 'fingerprint', sources: [], failed_tasks: [] };
  assert.deepEqual(recovery.recoveryPlanFromOperation(operation({ status: 'succeeded', phase: 'preview_ready', result: plan })), plan);
});

test('partial apply exposes only the saved replanning resume input', () => {
  const partial = operation({ action: 'recovery_apply', status: 'partial', phase: 'replanning',
    result: { fingerprint: 'fingerprint', source_ids: ['source'], result_commit: 'abc' } });
  assert.deepEqual(recovery.recoveryResumeInput(partial), { fingerprint: 'fingerprint', sourceIds: ['source'] });
  assert.equal(recovery.recoveryResumeInput(operation({ action: 'recovery_apply', status: 'failed' })), undefined);
});
