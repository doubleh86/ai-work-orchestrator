const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(root, '.tmp');
mkdirSync(tempRoot, { recursive: true });
const output = resolve(mkdtempSync(join(tempRoot, 'notification-refresh-')));
const cleanup = () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); };
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  execFileSync(process.execPath, [resolve(dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig',
    '--strict', '--target', 'ES2022', '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--types', 'node',
    '--outDir', output, 'desktop/main/workNotifications.ts'],
  { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);
const { WorkNotificationCenter } = require(join(output, 'main/workNotifications.js'));
const { PythonBridgeRequestError } = require(join(output, 'main/pythonBridge.js'));
const { notificationRefreshCopy, notificationErrorDetail, reconcileNotificationSnapshot, workNotificationCopy } = require(join(output, 'shared/workNotifications.js'));

function event(id) {
  return { event_id: id, source_key: `source:${id}`, project_key: 'B-repo', project_name: 'B', run_id: 'run', run_title: '작업',
    target_kind: 'run', target_id: 'run', request_id: '', verification_attempt_id: '', kind: 'completed',
    occurred_at: '2026-10-02T00:00:00Z', summary_code: 'group_completed', related_targets: [], os_eligible: true };
}
function fixture() {
  const store = join(output, `state-${Math.random().toString(36).slice(2)}.json`);
  const calls = [];
  const shown = [];
  const published = [];
  const errors = new Map();
  const pages = new Map();
  let projects = [{ name: 'A', repo: 'A-repo' }, { name: 'B', repo: 'B-repo' }];
  let projectError;
  let pending;
  let hostResult = true;
  let hostError;
  const bridge = { async request(method, params) {
    calls.push({ method, params });
    if (method === 'projects.list') { if (projectError) throw projectError; return projects; }
    assert.equal(method, 'notifications.list');
    if (pending?.name === params.projectName) await pending.promise;
    if (errors.has(params.projectName)) throw errors.get(params.projectName);
    const result = pages.get(params.projectName);
    if (typeof result === 'function') return result(params);
    return { items: result || [], next_cursor: `${params.projectName}-cursor`, has_more: false };
  } };
  const host = { isBackground: () => true, publish: (snapshot) => published.push(snapshot), log() {}, open() {},
    showOs: (...args) => { shown.push(args); if (hostError) throw hostError; return hostResult; } };
  const make = () => new WorkNotificationCenter(store, bridge, host, 0);
  return { store, calls, shown, published, errors, pages, center: make(), restart: make,
    setProjects: (value) => { projects = value; }, setProjectError: (value) => { projectError = value; },
    setPending: (value) => { pending = value; }, setHostResult: (value) => { hostResult = value; }, setHostError: (value) => { hostError = value; } };
}
const issue = (f, name = 'A') => f.center.snapshot().refresh_issues.filter((entry) => entry.project_name === name).at(-1);
const bridgeError = (kind, method = 'notifications.list', backend = 'control') =>
  new PythonBridgeRequestError(kind, backend, method, 17, 'instance-control-1', 'backend detail', kind === 'application' ? 'application_error' : '');

test('a single project query failure keeps other projects fresh and cannot claim engine loss', async () => {
  const f = fixture();
  await f.center.poll();
  f.errors.set('A', new Error('Python backend data read denied; token=private-value'));
  f.pages.set('B', [event('B-1')]);
  await f.center.poll();
  const snapshot = f.center.snapshot();
  assert.equal(issue(f).kind, 'query_failed');
  assert.equal(issue(f).failure_count, 1);
  assert.ok(issue(f).last_success_at);
  assert.doesNotMatch(issue(f).error_detail, /private-value/);
  assert.equal(snapshot.items.length, 1);
  assert.equal(snapshot.items[0].event_id, 'B-1');
  assert.equal(f.shown.length, 1);
  assert.equal(snapshot.delivery_error, '');
  assert.equal(JSON.parse(readFileSync(f.store, 'utf8')).projects.A.cursor, 'A-cursor');
});

test('initial repeated failures make one event; recovery does not read, dismiss, or notify again', async () => {
  const f = fixture();
  f.errors.set('A', new Error('lookup denied'));
  await f.center.poll();
  assert.equal(f.center.snapshot().unread_count, 0);
  assert.equal(JSON.parse(readFileSync(f.store, 'utf8')).projects.A, undefined);
  await f.center.poll();
  await f.center.poll();
  const failed = issue(f);
  assert.equal(failed.failure_count, 3);
  assert.equal(f.center.snapshot().items.length, 1);
  assert.equal(f.center.snapshot().unread_count, 1);
  assert.equal(f.shown.length, 1);
  f.errors.delete('A');
  await f.center.poll(failed.scope_key);
  const recovered = issue(f);
  assert.ok(recovered.recovered_at);
  assert.equal(recovered.first_failed_at, failed.first_failed_at);
  assert.equal(recovered.error_detail, 'lookup denied');
  assert.equal(f.center.snapshot().items[0].read_at, '');
  assert.equal(f.center.snapshot().items[0].summary_code, 'notification_query_failed');
  assert.equal(f.center.snapshot().unread_count, 1);
  assert.equal(f.shown.length, 1);
  assert.match(notificationRefreshCopy(recovered).title, /정상화/);
});

test('timeouts remain delayed and a confirmed connection loss is deduplicated across affected projects', async () => {
  const delayed = fixture();
  delayed.errors.set('A', bridgeError('timeout'));
  await delayed.center.poll();
  assert.equal(issue(delayed).kind, 'response_delayed');
  assert.equal(delayed.shown.length, 0);
  assert.doesNotMatch(notificationRefreshCopy(issue(delayed)).title, /끊겼/);
  const lost = fixture();
  lost.errors.set('A', bridgeError('process_exit'));
  lost.errors.set('B', bridgeError('not_running'));
  await lost.center.poll();
  assert.equal(issue(lost).kind, 'connection_lost');
  assert.equal(issue(lost).instance_id, 'instance-control-1');
  assert.equal(issue(lost).request_id, 17);
  assert.equal(lost.center.snapshot().items.length, 1);
  assert.equal(issue(lost).event_id, issue(lost, 'B').event_id);
  assert.equal(lost.shown.length, 1);
  lost.errors.delete('A');
  await lost.center.poll(issue(lost).scope_key);
  assert.ok(issue(lost).recovered_at);
  assert.equal(issue(lost, 'B').recovered_at, '');
  assert.equal(lost.center.snapshot().items.length, 1);
});

test('only the failed scope and backend role can establish recovery', async () => {
  const f = fixture();
  f.errors.set('A', bridgeError('application'));
  f.errors.set('B', bridgeError('timeout', 'notifications.list', 'planning'));
  await f.center.poll();
  const scopeA = issue(f).scope_key;
  const scopeB = issue(f, 'B').scope_key;
  f.errors.clear();
  f.calls.length = 0;
  await f.center.poll(scopeA);
  assert.deepEqual(f.calls.map((entry) => [entry.method, entry.params?.projectName]), [['projects.list', undefined], ['notifications.list', 'A']]);
  assert.ok(issue(f).recovered_at);
  assert.equal(issue(f, 'B').recovered_at, '');
  await f.center.poll(scopeB);
  assert.equal(issue(f, 'B').recovered_at, '');
});

test('read and dismissal receipts survive retry, restart and late successful poll commits', async () => {
  const f = fixture();
  f.errors.set('A', new Error('blocked'));
  await f.center.poll(); await f.center.poll();
  const eventId = issue(f).event_id;
  f.center.markRead(eventId);
  const restarted = f.restart();
  await restarted.poll();
  assert.equal(restarted.snapshot().items.length, 1);
  assert.equal(restarted.snapshot().unread_count, 0);
  restarted.dismissNotification(eventId);
  await restarted.poll();
  assert.equal(restarted.snapshot().items.length, 0);
  assert.equal(f.shown.length, 1);
  const next = f.restart();
  await next.poll();
  assert.equal(next.snapshot().items.length, 0);
  assert.equal(f.shown.length, 1);
});

test('manual retries join an in-flight poll and concurrent read/settings changes are preserved', async () => {
  const f = fixture();
  f.errors.set('A', new Error('blocked'));
  await f.center.poll(); await f.center.poll();
  let release;
  const promise = new Promise((resolve) => { release = resolve; });
  f.setPending({ name: 'A', promise });
  f.calls.length = 0;
  const poll = f.center.poll();
  const duplicate = f.center.poll(issue(f).scope_key);
  await Promise.resolve(); await Promise.resolve();
  f.center.markRead(issue(f).event_id);
  f.center.updateSettings({ enabled: false, completion: true, failure: true, attention_required: true });
  release();
  await Promise.all([poll, duplicate]);
  assert.equal(f.calls.filter((entry) => entry.method === 'projects.list').length, 1);
  assert.equal(f.center.snapshot().unread_count, 0);
  assert.equal(f.center.snapshot().settings.enabled, false);
});

test('a dismissed query problem cannot reappear when it escalates to one shared connection incident', async () => {
  const f = fixture();
  f.errors.set('A', new Error('denied'));
  await f.center.poll(); await f.center.poll();
  const eventId = issue(f).event_id;
  f.center.dismissNotification(eventId);
  f.errors.set('A', bridgeError('transport'));
  f.errors.set('B', bridgeError('transport'));
  await f.center.poll();
  assert.equal(f.center.snapshot().items.length, 0);
  assert.equal(issue(f).event_id, issue(f, 'B').event_id);
  assert.equal(f.shown.length, 1);
  const restarted = f.restart();
  await restarted.poll();
  assert.equal(restarted.snapshot().items.length, 0);
  assert.equal(f.shown.length, 1);
});

test('a dismissal during a pending poll and stopping before its response cannot restore old events', async () => {
  const f = fixture();
  f.errors.set('A', new Error('denied'));
  await f.center.poll(); await f.center.poll();
  let release;
  const promise = new Promise((resolve) => { release = resolve; });
  f.setPending({ name: 'A', promise });
  const pending = f.center.poll();
  await Promise.resolve(); await Promise.resolve();
  f.center.dismissNotification(issue(f).event_id);
  release(); await pending;
  assert.equal(f.center.snapshot().items.length, 0);
  assert.equal(f.shown.length, 1);
  const before = f.center.snapshot().revision;
  f.setPending({ name: 'A', promise: new Promise((resolve) => { release = resolve; }) });
  const stopped = f.center.poll();
  await Promise.resolve(); await Promise.resolve();
  f.center.stop();
  release(); await stopped;
  assert.equal(f.center.snapshot().revision, before);
});

test('failed pagination cannot advance a project cursor or ingest partial history', async () => {
  const f = fixture();
  f.pages.set('A', (params) => {
    if (params.afterCursor) throw new Error('page two failed');
    return { items: [{ ...event('partial'), project_key: 'A-repo' }], next_cursor: 'partial-cursor', has_more: true };
  });
  await f.center.poll();
  const saved = JSON.parse(readFileSync(f.store, 'utf8'));
  assert.equal(saved.projects.A, undefined);
  assert.equal(saved.items.length, 0);
  assert.equal(issue(f).kind, 'query_failed');
  assert.ok(saved.projects.B);
});

test('project removal and registry failures stay explicit without querying an unregistered directory', async () => {
  const f = fixture();
  f.errors.set('A', new Error('blocked'));
  await f.center.poll();
  const scope = issue(f).scope_key;
  f.setProjects([{ name: 'B', repo: 'B-repo' }]);
  f.calls.length = 0;
  await f.center.poll(scope);
  assert.deepEqual(f.calls.map((entry) => entry.method), ['projects.list']);
  assert.match(issue(f).error_detail, /등록 목록/);
  assert.equal(issue(f).recovered_at, '');
  f.setProjectError(bridgeError('timeout', 'projects.list'));
  await f.center.poll();
  assert.equal(issue(f, '').kind, 'response_delayed');
  assert.equal(issue(f).recovered_at, '');
});

test('malformed responses stay lookup failures rather than successful empty snapshots', async () => {
  const f = fixture();
  f.setProjects(null);
  await f.center.poll();
  assert.match(issue(f, '').error_detail, /응답/);
  f.setProjects([{ name: 'A', repo: 'A-repo' }]);
  f.pages.set('A', () => ({ items: [], next_cursor: null, has_more: false }));
  await f.center.poll();
  assert.equal(issue(f).kind, 'query_failed');
  assert.equal(JSON.parse(readFileSync(f.store, 'utf8')).projects.A, undefined);
});

test('v3 records upgrade safely and corrupted diagnostic metadata uses the existing backup', async () => {
  const f = fixture();
  await f.center.poll();
  const old = JSON.parse(readFileSync(f.store, 'utf8'));
  old.schema_version = 3;
  delete old.refresh_issues; delete old.refresh_successes;
  writeFileSync(f.store, JSON.stringify(old));
  const upgraded = f.restart();
  await upgraded.poll();
  assert.equal(JSON.parse(readFileSync(f.store, 'utf8')).schema_version, 4);
  upgraded.updateSettings({ enabled: false, completion: true, failure: true, attention_required: true });
  const broken = JSON.parse(readFileSync(f.store, 'utf8'));
  broken.refresh_issues = { invalid: true };
  writeFileSync(f.store, JSON.stringify(broken));
  assert.equal(f.restart().snapshot().read_state_notice, 'read_state_recovered_from_backup');
  delete broken.refresh_issues;
  writeFileSync(f.store, JSON.stringify(broken));
  assert.equal(f.restart().snapshot().read_state_notice, 'read_state_recovered_from_backup');
});

test('OS delivery failures remain notification diagnostics and never create an engine-loss episode', async () => {
  for (const throws of [false, true]) {
    const f = fixture();
    await f.center.poll();
    if (throws) f.setHostError(new Error('OS denied')); else f.setHostResult(false);
    f.pages.set('B', [event('delivery-1')]);
    await f.center.poll();
    assert.match(f.center.snapshot().delivery_error, /알림/);
    assert.equal(f.center.snapshot().refresh_issues.length, 0);
    assert.equal(f.center.snapshot().items[0].event_id, 'delivery-1');
  }
});



test('late snapshots cannot replace newer read, dismissal or recovery results in the same store', () => {
  const current = { storage_identity: 'same-store', revision: 8, refresh_issues: [{ recovered_at: 'now' }], items: [], unread_count: 0 };
  const stale = { ...current, revision: 7, items: [event('old')], unread_count: 1 };
  assert.equal(reconcileNotificationSnapshot(current, stale), current);
  const other = { ...stale, storage_identity: 'other-store' };
  assert.equal(reconcileNotificationSnapshot(current, other), other);
});

test('historical connection-unknown records and legacy error details do not assert a current outage or expose credentials', async () => {
  const f = fixture();
  await f.center.poll();
  const old = JSON.parse(readFileSync(f.store, 'utf8'));
  old.delivery_error = 'token=legacy-secret';
  writeFileSync(f.store, JSON.stringify(old));
  assert.doesNotMatch(f.restart().snapshot().delivery_error, /legacy-secret/);
  const copy = workNotificationCopy({ summary_code: 'connection_unknown', run_title: 'Python backend' });
  assert.match(copy.title, /이전/);
  assert.doesNotMatch(copy.body, /Python backend|끊겼/);
});

test('notification diagnostics redact sensitive error details', () => {
  const detail = notificationErrorDetail(new Error('token=private-value Authorization: Bearer another-secret'));
  assert.doesNotMatch(detail, /private-value|another-secret/);
  assert.match(notificationErrorDetail(new Error('"password":"value" Basic xyz')), /\[가림\]/);
});
