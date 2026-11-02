const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, mkdirSync, rmSync, writeFileSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'python-bridge-timeout-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--types', 'node', '--outDir', output,
    'desktop/main/pythonBridge.ts', 'desktop/shared/rpc.ts'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const { backendCommand, bundledBackendExecutable, requestTimeoutMilliseconds } = require(join(output, 'main/pythonBridge.js'));

test('bundled backend is selected by its fixed resource path even when Electron reports development mode', () => {
  const backend = join(output, 'backend', 'ai-orchestrator-backend');
  mkdirSync(dirname(backend), { recursive: true });
  writeFileSync(backend, '');
  assert.equal(bundledBackendExecutable(output, 'darwin'), backend);
  assert.equal(bundledBackendExecutable(output, 'win32'), undefined);
  assert.equal(bundledBackendExecutable(join(output, 'missing'), 'darwin'), undefined);
});

test('Windows portable selects its exe without requiring Python or a checkout', () => {
  const backend = join(output, 'backend', 'ai-orchestrator-backend.exe');
  writeFileSync(backend, '');
  assert.equal(bundledBackendExecutable(output, 'win32'), backend);
  assert.deepEqual(backendCommand(join(output, 'app'), backend), [backend, []]);
  assert.equal(bundledBackendExecutable(join(output, 'missing'), 'win32'), undefined);
  assert.equal(bundledBackendExecutable(output, 'linux'), undefined);
});

test('packaged macOS backend runs directly without Python module arguments', () => {
  assert.deepEqual(backendCommand('/app/resources/app', '/app/resources/backend/ai-orchestrator-backend'),
    ['/app/resources/backend/ai-orchestrator-backend', []]);
});

test('checkout backend continues using its selected Python interpreter', () => {
  assert.deepEqual(backendCommand('/checkout'), ['python', ['-m', 'ai_orchestrator.desktop_rpc']]);
});

test('agent-backed work requests rely on backend activity and command timeouts', () => {
  for (const method of ['runs.execute', 'runs.resume', 'tasks.execute', 'tasks.retry', 'tasks.repairFromChat',
    'tasks.complete', 'runs.verify', 'runs.verifyAndRepair', 'runs.prepareConflictResolution',
    'runs.applyPlanningConversation', 'planning.generateFeaturePlan']) {
    assert.equal(requestTimeoutMilliseconds(method), undefined, method);
  }
});

test('quick and explicitly bounded requests keep their response deadlines', () => {
  assert.equal(requestTimeoutMilliseconds('runs.get'), 15_000);
  assert.equal(requestTimeoutMilliseconds('runs.planningPreviewStatus'), 15_000);
  assert.equal(requestTimeoutMilliseconds('tasks.retryContext'), 15_000);
  assert.equal(requestTimeoutMilliseconds('tasks.saveRetryInstruction'), 15_000);
  assert.equal(requestTimeoutMilliseconds('runs.previewEffortMode'), 15_000);
  assert.equal(requestTimeoutMilliseconds('runs.setEffortMode'), 15_000);
  assert.equal(requestTimeoutMilliseconds('runs.cancelEffortReservation'), 15_000);
  assert.equal(requestTimeoutMilliseconds('planning.previewBootstrap'), 15_000);
  assert.equal(requestTimeoutMilliseconds('notifications.list'), 15_000);
  assert.equal(requestTimeoutMilliseconds('runs.requestStop'), 15_000);
  assert.equal(requestTimeoutMilliseconds('operations.get'), 15_000);
  assert.equal(requestTimeoutMilliseconds('operations.latest'), 15_000);
  assert.equal(requestTimeoutMilliseconds('runs.recoveryPlan'), 60_000);
  assert.equal(requestTimeoutMilliseconds('projects.updateMain'), 90_000);
});
