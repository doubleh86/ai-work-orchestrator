const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'work-notifications-build-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--types', 'node', '--outDir', output,
    'desktop/main/workNotifications.ts', 'desktop/shared/workNotifications.ts', 'desktop/shared/rpc.ts'],
  { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const { WorkNotificationCenter } = require(join(output, 'main/workNotifications.js'));

function event(id, kind = 'completed', summary = 'group_completed') {
  return {
    event_id: id,
    source_key: `source:${id}`,
    project_key: 'repo',
    run_id: 'run-1',
    run_title: '알림 테스트',
    target_kind: 'run',
    target_id: 'run-1',
    request_id: '',
    verification_attempt_id: '',
    kind,
    occurred_at: `2026-09-11T00:00:0${id.slice(-1)}+00:00`,
    summary_code: summary,
    related_targets: [],
    os_eligible: true,
  };
}

function fixture(storePath, pages, groupingWindowMs = 0, readRun) {
  const shown = [];
  const published = [];
  const opened = [];
  let background = true;
  const bridge = {
    async request(method, params) {
      if (method === 'projects.list') return [{ name: 'project', repo: 'C:/repo' }];
      if (method === 'runs.get' && readRun) return readRun(params);
      assert.equal(method, 'notifications.list');
      const items = pages.filter((item) => !params.afterCursor || item.event_id > params.afterCursor);
      return { items, next_cursor: items.at(-1)?.event_id || params.afterCursor || '', has_more: false };
    },
  };
  const host = {
    isBackground: () => background,
    publish: (snapshot) => published.push(snapshot),
    showOs: (title, body, onClick) => { shown.push({ title, body, onClick }); return true; },
    open(item) { opened.push(item); },
    log() {},
  };
  return {
    center: new WorkNotificationCenter(storePath, bridge, host, groupingWindowMs),
    shown,
    published,
    opened,
    setBackground(value) { background = value; },
  };
}

test('initial catch-up stays in the inbox and later events notify once', async () => {
  const dir = mkdtempSync(join(tempRoot, 'work-notifications-state-'));
  try {
    const store = join(dir, 'state.json');
    const pages = [event('event-1')];
    const first = fixture(store, pages);
    await first.center.poll();
    assert.equal(first.center.snapshot().items.length, 1);
    assert.equal(first.center.snapshot().unread_count, 0);
    assert.equal(first.center.snapshot().items[0].receipt_origin, 'initial_baseline');
    assert.equal(first.shown.length, 0);

    pages.push(event('event-2', 'failed', 'task_failed'));
    await first.center.poll();
    await first.center.poll();
    assert.equal(first.center.snapshot().items.length, 2);
    assert.equal(first.center.snapshot().unread_count, 1);
    assert.equal(first.shown.length, 1);
    assert.match(first.shown[0].title, /AI Work Orchestrator/);

    const restarted = fixture(store, pages);
    await restarted.center.poll();
    assert.equal(restarted.center.snapshot().items.length, 2);
    assert.equal(restarted.shown.length, 0);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('failed read persistence keeps the item unread until retry succeeds', async () => {
  const dir = mkdtempSync(join(tempRoot, 'work-notifications-state-'));
  try {
    const store = join(dir, 'state.json');
    const pages = [];
    const current = fixture(store, pages);
    await current.center.poll();
    pages.push(event('event-6'));
    await current.center.poll();
    assert.equal(current.center.snapshot().unread_count, 1);

    rmSync(store);
    mkdirSync(store);
    assert.throws(() => current.center.markRead('event-6'), /could not be saved/);
    assert.equal(current.center.snapshot().unread_count, 1);

    rmSync(store, { recursive: true, force: true });
    current.center.markRead('event-6');
    assert.equal(current.center.snapshot().unread_count, 0);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('a corrupt primary state restores the last readable backup', async () => {
  const dir = mkdtempSync(join(tempRoot, 'work-notifications-state-'));
  try {
    const store = join(dir, 'state.json');
    const pages = [];
    const current = fixture(store, pages);
    await current.center.poll();
    pages.push(event('event-7'));
    await current.center.poll();
    current.center.markRead('event-7');
    current.center.updateSettings({ enabled: true, completion: false, failure: true, attention_required: true });
    writeFileSync(store, '{broken', 'utf8');

    const restarted = fixture(store, pages);
    assert.equal(restarted.center.snapshot().unread_count, 0);
    assert.equal(restarted.center.snapshot().settings.completion, true);
    assert.equal(restarted.center.snapshot().read_state_notice, 'read_state_recovered_from_backup');
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('unrecoverable state creates a read baseline instead of reviving old unread items', async () => {
  const dir = mkdtempSync(join(tempRoot, 'work-notifications-state-'));
  try {
    const store = join(dir, 'state.json');
    writeFileSync(store, '{broken', 'utf8');
    writeFileSync(`${store}.bak`, '{also-broken', 'utf8');
    const pages = [event('event-8', 'failed', 'task_failed')];
    const recovered = fixture(store, pages);
    assert.equal(recovered.center.snapshot().read_state_notice, 'read_state_recovered_with_baseline');
    await recovered.center.poll();
    assert.equal(recovered.center.snapshot().items.length, 1);
    assert.equal(recovered.center.snapshot().unread_count, 0);
    assert.equal(recovered.center.snapshot().items[0].receipt_origin, 'initial_baseline');
    assert.equal(recovered.shown.length, 0);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('schema v1 read state migrates without losing read receipts', () => {
  const dir = mkdtempSync(join(tempRoot, 'work-notifications-state-'));
  try {
    const store = join(dir, 'state.json');
    const oldItem = {
      ...event('event-9'),
      project_name: 'project',
      received_at: '2026-09-11T00:00:09+00:00',
      read_at: '2026-09-11T00:01:00+00:00',
      os_delivery_attempted_at: '',
    };
    writeFileSync(store, JSON.stringify({
      schema_version: 1,
      projects: { project: { cursor: 'event-9', initialized: true, project_key: 'C:/repo' } },
      items: [oldItem, { malformed: true }],
      settings: { enabled: true, completion: false, failure: true, attention_required: true },
      delivery_error: '',
    }), 'utf8');

    const migrated = fixture(store, [event('event-9')]);
    assert.equal(migrated.center.snapshot().items.length, 1);
    assert.equal(migrated.center.snapshot().unread_count, 0);
    assert.equal(migrated.center.snapshot().settings.completion, false);
    migrated.center.markAllRead();
    assert.equal(JSON.parse(readFileSync(store, 'utf8')).schema_version, 1);
    migrated.center.updateSettings({ enabled: true, completion: true, failure: true, attention_required: true });
    assert.equal(JSON.parse(readFileSync(store, 'utf8')).schema_version, 4);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('a future schema is reported and never overwritten by this version', async () => {
  const dir = mkdtempSync(join(tempRoot, 'work-notifications-state-'));
  try {
    const store = join(dir, 'state.json');
    writeFileSync(store, JSON.stringify({ schema_version: 99, future_state: true }), 'utf8');
    const current = fixture(store, []);
    assert.equal(current.center.snapshot().read_state_notice, 'read_state_future_schema');
    assert.throws(
      () => current.center.updateSettings({ enabled: false, completion: false, failure: false, attention_required: false }),
      /could not be saved/,
    );
    await current.center.poll();
    assert.equal(JSON.parse(readFileSync(store, 'utf8')).schema_version, 99);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('foreground events update the inbox and read/settings survive restart', async () => {
  const dir = mkdtempSync(join(tempRoot, 'work-notifications-state-'));
  try {
    const store = join(dir, 'state.json');
    const pages = [];
    const current = fixture(store, pages);
    await current.center.poll();
    current.setBackground(false);
    pages.push(event('event-3'));
    await current.center.poll();
    assert.equal(current.shown.length, 0);
    assert.equal(current.center.snapshot().unread_count, 1);
    current.center.markRead('event-3');
    current.center.updateSettings({ enabled: true, completion: false, failure: true, attention_required: true });

    const restarted = fixture(store, pages);
    assert.equal(restarted.center.snapshot().unread_count, 0);
    assert.equal(restarted.center.snapshot().settings.completion, false);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('events from the same group in one delivery window use one OS notification', async () => {
  const dir = mkdtempSync(join(tempRoot, 'work-notifications-state-'));
  try {
    const pages = [];
    const current = fixture(join(dir, 'state.json'), pages);
    await current.center.poll();
    pages.push(event('event-4', 'failed', 'task_failed'));
    pages.push({ ...event('event-5', 'attention_required', 'manual_task_required'), target_kind: 'task', target_id: 'task-2' });
    await current.center.poll();
    assert.equal(current.shown.length, 1);
    assert.match(current.shown[0].body, /2건/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('schema v2 migrates to v4 without losing items or read receipts', () => {
  const dir = mkdtempSync(join(tempRoot, 'work-notifications-state-'));
  try {
    const store = join(dir, 'state.json');
    const oldItem = {
      ...event('event-10'),
      project_name: 'project',
      received_at: '2026-09-11T00:00:10+00:00',
      read_at: '2026-09-11T00:01:00+00:00',
      os_delivery_attempted_at: '',
      receipt_origin: 'live',
    };
    writeFileSync(store, JSON.stringify({
      schema_version: 2,
      revision: 4,
      storage_identity: 'existing-storage',
      projects: {},
      items: [oldItem],
      read_receipts: [{ stable_event_key: 'repo\0event-10', stable_source_key: 'repo\0source:event-10', read_at: oldItem.read_at }],
      settings: { enabled: true, completion: true, failure: true, attention_required: true },
      delivery_error: '',
      last_successful_write_at: '',
    }), 'utf8');

    const migrated = fixture(store, []);
    assert.equal(migrated.center.snapshot().items.length, 1);
    assert.equal(migrated.center.snapshot().unread_count, 0);
    migrated.center.dismissNotification('event-10');
    const persisted = JSON.parse(readFileSync(store, 'utf8'));
    assert.equal(persisted.schema_version, 4);
    assert.equal(persisted.read_receipts.length, 1);
    assert.equal(persisted.dismissed_receipts.length, 1);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('dismissed notifications stay removed across restart and repeated polling', async () => {
  const dir = mkdtempSync(join(tempRoot, 'work-notifications-state-'));
  try {
    const store = join(dir, 'state.json');
    const pages = [];
    const current = fixture(store, pages);
    await current.center.poll();
    pages.push(event('event-11', 'failed', 'task_failed'));
    await current.center.poll();
    assert.equal(current.center.snapshot().unread_count, 1);

    current.center.dismissNotification('event-11');
    assert.equal(current.center.snapshot().items.length, 0);
    pages.push({ ...event('event-15', 'failed', 'task_failed'), source_key: 'source:event-11' });
    await current.center.poll();
    assert.equal(current.center.snapshot().items.length, 0);

    const restarted = fixture(store, pages);
    await restarted.center.poll();
    assert.equal(restarted.center.snapshot().items.length, 0);
    assert.equal(restarted.shown.length, 0);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('read and all dismissal scopes use current items and preserve state on save failure', async () => {
  const dir = mkdtempSync(join(tempRoot, 'work-notifications-state-'));
  try {
    const store = join(dir, 'state.json');
    const pages = [];
    const current = fixture(store, pages);
    await current.center.poll();
    pages.push(event('event-12'));
    pages.push(event('event-13', 'failed', 'task_failed'));
    await current.center.poll();
    current.center.markRead('event-12');

    current.center.dismissNotifications('read');
    assert.deepEqual(current.center.snapshot().items.map((item) => item.event_id), ['event-13']);
    assert.equal(current.center.snapshot().unread_count, 1);

    rmSync(store);
    mkdirSync(store);
    assert.throws(() => current.center.dismissNotifications('all'), /could not be saved/);
    assert.deepEqual(current.center.snapshot().items.map((item) => item.event_id), ['event-13']);
    assert.equal(current.center.snapshot().unread_count, 1);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('dismissal removes an event waiting for grouped OS delivery', async () => {
  const dir = mkdtempSync(join(tempRoot, 'work-notifications-state-'));
  try {
    const pages = [];
    const current = fixture(join(dir, 'state.json'), pages, 60_000);
    await current.center.poll();
    pages.push(event('event-14', 'failed', 'task_failed'));
    await current.center.poll();
    current.center.dismissNotification('event-14');
    current.center.stop();
    assert.equal(current.shown.length, 0);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('waiting notifications recheck their current source, open a view, and never replay after restart', async () => {
  const dir = mkdtempSync(join(tempRoot, 'work-notifications-state-'));
  try {
    for (const code of ['task_retry_required', 'remaining_tasks_resume_required', 'integration_verification_required', 'main_apply_required']) {
      const pages = [];
      const item = event('event-21', 'attention_required', code);
      const store = join(dir, `${code}.json`);
      const reads = [];
      const current = fixture(store, pages, 0, async (params) => {
        reads.push(params);
        return { id: item.run_id, waiting_prompt: { source_key: item.source_key } };
      });
      await current.center.poll();
      pages.push(item);
      await current.center.poll();
      assert.equal(current.shown.length, 1);
      assert.deepEqual(reads, [{ projectName: 'project', runId: item.run_id }]);
      assert.equal(current.opened.length, 0);
      current.shown[0].onClick();
      assert.equal(current.opened[0].source_key, item.source_key);
      await current.center.poll();
      assert.equal(current.shown.length, 1);
      const restarted = fixture(store, pages, 0, () => { throw new Error('old event queried'); });
      await restarted.center.poll();
      assert.equal(restarted.shown.length, 0);
    }
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test('stale and unknown waiting proof stays in the inbox without recommending execution', async () => {
  const dir = mkdtempSync(join(tempRoot, 'work-notifications-state-'));
  try {
    const pages = [];
    let proof = { id: 'run-1', waiting_prompt: null };
    const current = fixture(join(dir, 'state.json'), pages, 0, async () => proof);
    await current.center.poll();
    pages.push(event('event-22', 'attention_required', 'remaining_tasks_resume_required'));
    await current.center.poll();
    proof = { id: 'run-1', waiting_prompt: { source_key: 'different-plan' } };
    pages.push(event('event-23', 'attention_required', 'task_retry_required'));
    await current.center.poll();
    proof = { id: 'different-run', waiting_prompt: { source_key: 'source:event-24' } };
    pages.push(event('event-24', 'attention_required', 'integration_verification_required'));
    await current.center.poll();
    assert.equal(current.shown.length, 0);
    assert.equal(current.center.snapshot().unread_count, 3);
    assert.equal(current.center.snapshot().delivery_error, '');
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test('read, dismiss, foreground changes, and stopping during an awaited check suppress the late popup', async () => {
  const dir = mkdtempSync(join(tempRoot, 'work-notifications-state-'));
  try {
    for (const change of ['read', 'dismiss', 'foreground', 'stop']) {
      const pages = [];
      let finish;
      let queried;
      const entered = new Promise((resolve) => { queried = resolve; });
      const pending = new Promise((resolve) => { finish = resolve; });
      const current = fixture(join(dir, `${change}.json`), pages, 0, () => { queried(); return pending; });
      await current.center.poll();
      const item = event('event-25', 'attention_required', 'task_retry_required');
      pages.push(item);
      const polling = current.center.poll();
      await entered;
      if (change === 'read') current.center.markRead(item.event_id);
      if (change === 'dismiss') current.center.dismissNotification(item.event_id);
      if (change === 'foreground') current.setBackground(false);
      if (change === 'stop') current.center.stop();
      finish({ id: item.run_id, waiting_prompt: { source_key: item.source_key } });
      await polling;
      assert.equal(current.shown.length, 0);
    }
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test('a failed current-state read exposes delivery error without a popup or an action', async () => {
  const dir = mkdtempSync(join(tempRoot, 'work-notifications-state-'));
  try {
    const pages = [];
    const current = fixture(join(dir, 'state.json'), pages, 0, async () => { throw new Error('state read unavailable'); });
    await current.center.poll();
    pages.push(event('event-26', 'attention_required', 'remaining_tasks_resume_required'));
    await current.center.poll();
    assert.equal(current.shown.length, 0);
    assert.equal(current.opened.length, 0);
    assert.equal(current.center.snapshot().unread_count, 1);
    assert.match(current.center.snapshot().delivery_error, /state read unavailable/);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
