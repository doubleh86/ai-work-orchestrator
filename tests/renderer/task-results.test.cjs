const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');
const { renderToStaticMarkup } = require('react-dom/server');
const root = resolve(__dirname, '../..'), temp = join(root, '.tmp');
mkdirSync(temp, { recursive: true });
const output = mkdtempSync(join(temp, 'task-results-'));
process.on('exit', () => { assert.equal(dirname(output), temp); rmSync(output, { recursive: true, force: true }); });
const pkg = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(pkg), require(pkg).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--rootDir', 'desktop', '--outDir', output,
  'desktop/renderer/src/taskResults.ts', 'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });

const { currentTaskResult } = require(join(output, 'renderer/src/taskResults.js'));

test('task details require the latest result to match a completed commit', () => {
  const result = { result_commit: 'final', files: [{ path: 'saved.txt', change: 'A' }], manual_verification_note: '실제 기기 확인' };
  const task = { status: 'completed', completed_commit: 'final', result_history: [result] };
  assert.equal(currentTaskResult(task), result);
  assert.equal(currentTaskResult({ ...task, status: 'merged' }), result);
  for (const status of ['pending', 'running', 'failed', 'waiting', 'deferred']) assert.equal(currentTaskResult({ ...task, status }), undefined);
  assert.equal(currentTaskResult({ ...task, completed_commit: '' }), undefined);
  assert.equal(currentTaskResult({ ...task, completed_commit: 'newer' }), undefined);
  assert.equal(currentTaskResult({ ...task, result_history: [result, { result_commit: 'stale' }] }), undefined);
  assert.equal(currentTaskResult({ ...task, result_history: [] }), undefined);
  assert.equal(currentTaskResult({ status: 'completed', completed_commit: 'final' }), undefined);
  assert.deepEqual(currentTaskResult(task).files, [{ path: 'saved.txt', change: 'A' }]);
  assert.equal(currentTaskResult(task).manual_verification_note, '실제 기기 확인');
});
