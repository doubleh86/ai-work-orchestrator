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
const output = mkdtempSync(join(temp, 'log-polling-'));
process.on('exit', () => { assert.equal(dirname(output), temp); rmSync(output, { recursive: true, force: true }); });
const pkg = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(pkg), require(pkg).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--rootDir', 'desktop', '--outDir', output,
  'desktop/renderer/src/logPolling.ts', 'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });

const logs = require(join(output, 'renderer/src/logPolling.js'));

test('switching project with identical run and task ids masks the old log synchronously', () => {
  const state = { key: JSON.stringify(['a', 'run', 'task']), snapshot: { ...logs.emptyTaskLog, value: 'private old output' } };
  assert.equal(logs.selectTaskLogSnapshot(JSON.stringify(['b', 'run', 'task']), true, state).value, '');
  assert.equal(logs.selectTaskLogSnapshot(state.key, false, state).value, '');
});
test('poller never overlaps requests', async () => {
  let complete; let calls = 0;
  const poller = logs.createTaskLogPoller(() => { calls++; return new Promise((r) => { complete = r; }); }, () => {});
  const first = poller.refresh();
  await poller.refresh();
  assert.equal(calls, 1);
  complete('done'); await first; poller.stop();
});
test('late response after disposal cannot publish to another task', async () => {
  let complete; const updates = [];
  const poller = logs.createTaskLogPoller(() => new Promise((r) => { complete = r; }), (value) => updates.push(value));
  const first = poller.refresh(); poller.stop(); complete('old task'); await first;
  assert.equal(updates.length, 1);
  assert.equal(updates[0].value, '');
});
test('read failure preserves last content and last successful check; retry recovers', async () => {
  let fail = false; let tick = 10; const updates = [];
  const poller = logs.createTaskLogPoller(async () => { if (fail) throw new Error('offline'); return 'saved'; }, (value) => updates.push(value), () => tick);
  await poller.refresh(); fail = true; tick = 20; await poller.refresh();
  assert.equal(updates.at(-1).value, 'saved');
  assert.equal(updates.at(-1).checkedAt, 10);
  assert.match(updates.at(-1).error, /offline/);
  fail = false; tick = 30; await poller.refresh();
  assert.equal(updates.at(-1).error, '');
  assert.equal(updates.at(-1).checkedAt, 30);
  assert.equal(updates.at(-1).changedAt, 10);
  poller.stop();
});
test('successful polling is not mistaken for new agent output', async () => {
  let tick = 1; let content = ''; const updates = [];
  const poller = logs.createTaskLogPoller(async () => content, (value) => updates.push(value), () => tick);
  await poller.refresh(); assert.equal(updates.at(-1).changedAt, undefined);
  content = 'new'; tick = 2; await poller.refresh();
  tick = 3; await poller.refresh();
  assert.equal(updates.at(-1).checkedAt, 3);
  assert.equal(updates.at(-1).changedAt, 2);
  poller.stop();
});
