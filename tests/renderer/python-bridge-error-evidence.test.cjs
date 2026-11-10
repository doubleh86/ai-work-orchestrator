const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { EventEmitter } = require('node:events');
const { PassThrough } = require('node:stream');
const { runInNewContext } = require('node:vm');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(root, '.tmp');
mkdirSync(tempRoot, { recursive: true });
const output = resolve(mkdtempSync(join(tempRoot, 'bridge-evidence-')));
const cleanup = () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); };
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  execFileSync(process.execPath, [resolve(dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig',
    '--strict', '--target', 'ES2022', '--module', 'commonjs', '--skipLibCheck', '--types', 'node', '--outDir', output,
    'desktop/main/pythonBridge.ts'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);
const modulePath = join(output, 'main/pythonBridge.js');

// All process and timeout behavior is simulated; no backend or desktop app is launched.
function harness() {
  const children = [];
  const timers = new Map();
  let timerId = 0;
  const exports = {};
  const localRequire = createRequire(modulePath);
  const spawn = () => {
    const child = new EventEmitter();
    child.stdout = new PassThrough(); child.stderr = new PassThrough(); child.stdin = new EventEmitter();
    child.requests = [];
    child.stdin.write = (payload, encoding, callback) => {
      child.requests.push(JSON.parse(payload));
      callback?.(child.writeError || null);
      return true;
    };
    child.respond = (frame) => child.stdout.write(`${JSON.stringify(frame)}\n`);
    child.exitCode = null; child.signalCode = null;
    children.push(child);
    return child;
  };
  runInNewContext(readFileSync(modulePath, 'utf8'), { exports, __dirname: dirname(modulePath),
    require: (name) => name === 'node:child_process' ? { spawn } : localRequire(name),
    process: { platform: 'win32', env: {}, stderr: { write() {} } },
    setTimeout: (callback) => { const id = { id: ++timerId, unref() { return this; } }; timers.set(id, callback); return id; },
    clearTimeout: (id) => timers.delete(id),
  });
  const bridge = new exports.PythonBridge('mock-backend');
  return { bridge, children, errorClass: exports.PythonBridgeRequestError,
    timeout: () => { const batch = [...timers.values()]; timers.clear(); for (const callback of batch) callback(); } };
}

test('application errors retain method and role without becoming transport errors', async () => {
  const h = harness(); h.bridge.start();
  const request = h.bridge.request('notifications.list', { projectName: 'A' });
  const sent = h.children[0].requests[0];
  h.children[0].respond({ id: sent.id, error: { code: 'application_error', message: 'backend file denied' } });
  await assert.rejects(request, (error) => {
    assert.ok(error instanceof h.errorClass);
    assert.equal(error.kind, 'application');
    assert.equal(error.method, 'notifications.list');
    assert.equal(error.backend, 'control');
    assert.equal(error.rpcCode, 'application_error');
    assert.equal(error.requestId, sent.id);
    assert.ok(error.instanceId);
    return true;
  });
});

test('conversation Planning backends isolate same-project requests and target only the interrupted conversation', async () => {
  const h=harness();h.bridge.start();
  const first=h.bridge.requestPlanning('runs.sendPlanningMessage',{projectName:'A',runId:'one',message:'first'});
  const second=h.bridge.requestPlanning('runs.sendPlanningMessage',{projectName:'A',runId:'two',message:'second'});
  assert.equal(h.children.length,5);
  const a=h.children[3],b=h.children[4];
  assert.equal(a.requests[0].params.runId,'one');assert.equal(b.requests[0].params.runId,'two');
  const stopped=assert.rejects(first,error=>error.kind==='stopped'&&error.backend==='planning');
  await h.bridge.restartPlanning('A','one');await stopped;
  b.respond({id:b.requests[0].id,result:{id:'two'}});
  assert.equal((await second).id,'two');
  const next=h.bridge.requestPlanning('runs.sendPlanningMessage',{projectName:'A',runId:'two',message:'continue'});
  assert.equal(h.children.length,5,'the uninterrupted conversation reuses its SDK process');
  b.respond({id:b.requests[1].id,result:{id:'two'}});await next;
  await h.bridge.stop();assert.equal(h.bridge.planningSessions.size,0);
});

test('idle Planning sessions are released and app shutdown rejects its owned remaining requests', async () => {
  const h=harness();h.bridge.start();
  const first=h.bridge.requestPlanning('runs.sendPlanningMessage',{projectName:'A',runId:'one'});
  const child=h.children[3];child.respond({id:child.requests[0].id,result:'done'});await first;
  h.timeout();await new Promise(setImmediate);
  assert.equal(h.bridge.planningSessions.size,0);
  const next=h.bridge.requestPlanning('runs.sendPlanningMessage',{projectName:'A',runId:'one'});
  assert.equal(h.children.length,5);
  const stopped=assert.rejects(next,error=>error.kind==='stopped');
  await h.bridge.stop();await stopped;
  assert.equal(h.bridge.planningSessions.size,0);
});

test('timeout evidence is distinct and a late response cannot complete the expired request', async () => {
  const h = harness(); h.bridge.start();
  const request = h.bridge.request('projects.list');
  h.timeout();
  await assert.rejects(request, (error) => error.kind === 'timeout' && error.backend === 'control' && error.method === 'projects.list');
  h.children[0].respond({ id: h.children[0].requests[0].id, result: ['late'] });
  const next = h.bridge.request('projects.list');
  const sent = h.children[0].requests.at(-1);
  h.children[0].respond({ id: sent.id, result: ['current'] });
  assert.equal((await next)[0], 'current');
});

test('confirmed exit, closed output and write errors include the affected instance only', async () => {
  for (const mode of ['exit', 'output', 'write']) {
    const h = harness(); h.bridge.start();
    const child = h.children[0];
    if (mode === 'write') child.writeError = new Error('write EPIPE');
    const control = h.bridge.request('notifications.list');
    const planning = h.bridge.request('runs.sendPlanningMessage');
    const rejected = assert.rejects(control, (error) => {
      assert.equal(error.kind, mode === 'exit' ? 'process_exit' : 'transport');
      assert.equal(error.backend, 'control');
      assert.ok(error.instanceId);
      return true;
    });
    if (mode === 'exit') child.emit('exit', 1, null);
    if (mode === 'output') { child.stdout.end(); await new Promise((resolve) => setImmediate(resolve)); }
    await rejected;
    const sent = h.children[1].requests[0];
    h.children[1].respond({ id: sent.id, result: 'planning-alive' });
    assert.equal(await planning, 'planning-alive');
  }
});

test('restarting uses a new instance and ignores frames from the previous process', async () => {
  const h = harness(); h.bridge.start();
  const oldChild = h.children[0];
  const oldRequest = h.bridge.request('projects.list');
  const rejected = assert.rejects(oldRequest, (error) => error.kind === 'stopped' && Boolean(error.instanceId));
  await h.bridge.restart();
  await rejected;
  const fresh = h.bridge.request('projects.list');
  const current = h.children[3];
  const sent = current.requests[0];
  oldChild.respond({ id: sent.id, result: 'wrong-instance' });
  current.respond({ id: sent.id, result: 'fresh-instance' });
  assert.equal(await fresh, 'fresh-instance');
});

test('credential changes affect subsequent requests across all roles and survive backend restart', async () => {
  const h = harness(); h.bridge.start(); h.bridge.setNvidiaApiKey('first-fixture');
  const active = h.bridge.request('tasks.execute', { projectName: 'A' });
  const work = h.children[2], old = work.requests[0];
  h.bridge.setNvidiaApiKey('second-fixture');
  for (const [method, role] of [['providers.status', 0], ['runs.sendPlanningMessage', 1], ['tasks.retry', 2]]) {
    const request = h.bridge.request(method, { projectName: 'A', nvidia_api_key: 'cannot-override-frame' });
    const child = h.children[role], sent = child.requests.at(-1);
    assert.equal(sent.nvidia_api_key, 'second-fixture');
    assert.equal(Object.hasOwn(sent.params, 'key'), false);
    child.respond({ id: sent.id, result: 'ok' }); await request;
  }
  assert.equal(old.nvidia_api_key, 'first-fixture');
  work.respond({ id: old.id, result: 'finished-with-first' }); assert.equal(await active, 'finished-with-first');
  await h.bridge.restart();
  const fresh = h.bridge.request('projects.list');
  const child = h.children[3], sent = child.requests[0];
  assert.equal(sent.nvidia_api_key, 'second-fixture'); child.respond({ id: sent.id, result: [] }); await fresh;
  h.bridge.setNvidiaApiKey(undefined);
  const fallback = h.bridge.request('projects.list'), frame = child.requests.at(-1);
  assert.equal(Object.hasOwn(frame, 'nvidia_api_key'), false); child.respond({ id: frame.id, result: [] }); await fallback;
});

test('Claude app credentials stay out of params and follow updates in existing and new Planning sessions', async () => {
  const h = harness(); h.bridge.start(); h.bridge.setClaudeApiKey('first-claude-fixture');
  const active = h.bridge.request('tasks.execute', { projectName: 'A' });
  const old = h.children[2].requests[0];
  const first = h.bridge.requestPlanning('runs.sendPlanningMessage', { projectName: 'A', runId: 'one' });
  const session = h.children[3], firstFrame = session.requests[0];
  assert.equal(firstFrame.claude_api_key, 'first-claude-fixture');
  session.respond({ id: firstFrame.id, result: 'ready' }); await first;
  h.bridge.setClaudeApiKey('next-claude-fixture');
  const next = h.bridge.requestPlanning('runs.sendPlanningMessage', { projectName: 'A', runId: 'one' });
  const nextFrame = session.requests[1];
  assert.equal(nextFrame.claude_api_key, 'next-claude-fixture');
  assert.equal(Object.hasOwn(nextFrame.params, 'claude_api_key'), false);
  assert.equal(old.claude_api_key, 'first-claude-fixture');
  session.respond({ id: nextFrame.id, result: 'updated' }); await next;
  h.children[2].respond({ id: old.id, result: 'finished' }); await active;
  h.bridge.setClaudeApiKey(undefined);
  const fallback = h.bridge.request('auth.claude.status', {}), child = h.children[0], frame = child.requests.at(-1);
  assert.equal(Object.hasOwn(frame, 'claude_api_key'), false);
  child.respond({ id: frame.id, result: {} }); await fallback;
  await h.bridge.stop();
});

test('model credential mappings are private snapshots and cannot be changed by renderer RPC params', async () => {
  const h = harness(); h.bridge.start();
  const bindings = { 'vendor/review': 'review-fixture' };
  h.bridge.setNvidiaApiKey('default-fixture', bindings); bindings['vendor/review'] = 'caller-mutation';
  const active = h.bridge.request('tasks.execute', { nvidia_model_api_keys: { 'vendor/review': 'renderer-mutation' } });
  const child = h.children[2], first = child.requests[0];
  assert.equal(first.nvidia_model_api_keys['vendor/review'], 'review-fixture');
  h.bridge.setNvidiaApiKey('next-default', { 'vendor/review': 'next-review' });
  const next = h.bridge.request('tasks.retry'), second = child.requests[1];
  assert.equal(second.nvidia_model_api_keys['vendor/review'], 'next-review');
  assert.equal(first.nvidia_model_api_keys['vendor/review'], 'review-fixture');
  child.respond({ id: first.id, result: 'ok' }); child.respond({ id: second.id, result: 'ok' });
  await active; await next;
});
