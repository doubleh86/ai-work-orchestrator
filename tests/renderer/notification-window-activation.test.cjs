const { test } = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { mkdirSync, mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');
const root = resolve(__dirname, '../..');
const tempRoot = join(root, '.tmp');
mkdirSync(tempRoot, { recursive: true });
const output = mkdtempSync(join(tempRoot, 'notification-window-'));
process.on('exit', () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); });
const packagePath = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig', '--strict',
  '--target', 'ES2022', '--module', 'commonjs', '--skipLibCheck', '--types', 'node', '--outDir', output,
  'desktop/main/main.ts'], { cwd: root, stdio: 'inherit' });
const mainPath = join(output, 'main/main.js');
const mainRequire = createRequire(mainPath);

async function host() {
  const windows = [], notifications = [], handlers = new Map(), deferred = [], requests = [];
  let focused, notificationHost;
  class Window extends EventEmitter {
    constructor(options) {
      super(); this.options = options; this.calls = []; this.minimized = false; this.destroyed = false; this.visible = false;
      this.webContents = Object.assign(new EventEmitter(), { loading: false, sent: [], setWindowOpenHandler() {},
        isLoadingMainFrame() { return this.loading; }, isDestroyed: () => this.destroyed,
        send(channel, value) { this.sent.push([channel, value]); } });
      windows.push(this);
    }
    static getFocusedWindow() { return focused; }
    static getAllWindows() { return windows; }
    loadFile() {} loadURL() {}
    isDestroyed() { return this.destroyed; }
    isMinimized() { return this.minimized; }
    isVisible() { return this.visible; }
    isFocused() { return focused === this; }
    restore() { this.calls.push('restore'); this.minimized = false; }
    show() { this.calls.push('show'); this.visible = true; }
    moveTop() { this.calls.push('moveTop'); }
    focus() { this.calls.push('focus'); focused = this; }
  }
  class OsNotification extends EventEmitter {
    constructor(options) { super(); this.options = options; notifications.push(this); }
    static isSupported() { return true; }
    show() { this.shown = true; }
  }
  const app = Object.assign(new EventEmitter(), { whenReady: () => Promise.resolve(), getPath: () => output, quit() {} });
  const electron = { app, BrowserWindow: Window, Notification: OsNotification, ipcMain: { handle: (name, fn) => handlers.set(name, fn), removeHandler() {} },
    Menu: { setApplicationMenu() {}, buildFromTemplate() {} }, clipboard: {}, shell: {}, dialog: {} };
  const bridge = { bundledBackendExecutable() {}, PythonBridge: class {
    setNvidiaApiKey() {} start() {} request(...args) { requests.push(args); return Promise.resolve(); }
  } };
  const center = { WorkNotificationCenter: class {
    constructor(_path, _bridge, value) { notificationHost = value; }
    start() {} snapshot() { return { items: [] }; } markRead(id) { return { read: id }; }
  } };
  runInNewContext(readFileSync(mainPath, 'utf8'), { exports: {}, __dirname: dirname(mainPath),
    process: { platform: 'win32', resourcesPath: output, env: {}, stderr: { write() {} } },
    setImmediate: fn => deferred.push(fn),
    require: name => name === 'electron' ? electron : name === './pythonBridge' ? bridge
      : name === './workNotifications' ? center : name === './codexAuth' ? { CodexAuthController: class {} } : mainRequire(name) });
  await Promise.resolve();
  return { windows, notifications, handlers, deferred, requests, Window,
    get notificationHost() { return notificationHost; }, setFocused(value) { focused = value; } };
}
const item = id => ({ event_id: id, project_name: 'project', run_id: id, target_kind: 'task', target_id: `task-${id}` });

test('OS notification click restores and explicitly raises the same window before opening its task', async () => {
  for (const minimized of [false, true]) {
    const h = await host(), w = h.windows[0], n = item('event');
    w.minimized = minimized; w.visible = !minimized;
    h.notificationHost.showOs('title', 'body', () => h.notificationHost.open(n));
    assert.deepEqual(w.calls, [], 'receiving an OS notification must not steal focus');
    assert.equal(h.notifications[0].shown, true); h.notifications[0].emit('click');
    assert.deepEqual(w.calls, minimized ? ['restore', 'show', 'moveTop', 'focus'] : ['show', 'moveTop', 'focus']);
    assert.deepEqual(w.webContents.sent, [['orchestrator:notification-open', n]]);
    assert.equal(h.windows.length, 1); assert.deepEqual(h.requests, []);
  }
});

test('hidden and focused windows use the clicked target without always-on-top or extra windows', async () => {
  const h = await host(), first = h.windows[0], second = new h.Window({});
  h.setFocused(second); h.notificationHost.open(item('chosen'));
  assert.deepEqual(first.calls, []); assert.deepEqual(second.calls, ['show', 'moveTop', 'focus']);
  assert.equal(second.visible, true); assert.equal(second.options.alwaysOnTop, undefined);
  assert.equal(second.webContents.sent[0][1].event_id, 'chosen');
});

test('destroyed windows are skipped and newly created windows are raised again when ready', async () => {
  const h = await host(), old = h.windows[0]; old.destroyed = true; h.setFocused(old);
  const n = item('new'); h.notificationHost.open(n);
  const created = h.windows[1]; assert.ok(created); assert.deepEqual(old.calls, []);
  assert.deepEqual(created.calls, ['show', 'moveTop', 'focus']);
  created.emit('ready-to-show');
  assert.deepEqual(created.calls.slice(-3), ['show', 'moveTop', 'focus']);
  assert.equal(created.options.webPreferences.sandbox, true);
});

test('loading windows only deliver the newest clicked notification and never send to a destroyed window', async () => {
  const h = await host(), w = h.windows[0]; w.webContents.loading = true;
  h.notificationHost.open(item('old')); h.notificationHost.open(item('latest'));
  assert.deepEqual(w.webContents.sent, []); w.webContents.emit('did-finish-load');
  assert.equal(w.webContents.sent.length, 1); assert.equal(w.webContents.sent[0][1].event_id, 'latest');
  h.notificationHost.open(item('closed')); w.destroyed = true; w.webContents.emit('did-finish-load');
  assert.equal(w.webContents.sent.length, 1);
});

test('pending notification replay cannot overwrite a newer click or a completed read acknowledgment', async () => {
  const h = await host(), w = h.windows[0];
  const list = h.handlers.get('orchestrator:notifications-list'), markRead = h.handlers.get('orchestrator:notifications-mark-read');
  h.notificationHost.open(item('old')); await list({ sender: w.webContents });
  h.notificationHost.open(item('latest')); h.deferred.shift()();
  assert.deepEqual(w.webContents.sent.map(entry => entry[1].event_id), ['old', 'latest']);
  await list({ sender: w.webContents }); markRead({}, 'latest'); h.deferred.shift()();
  assert.equal(w.webContents.sent.length, 2); assert.deepEqual(h.requests, []);
});

test('late ready-to-show from an older notification cannot raise a now unrelated window', async () => {
  const h = await host(); h.windows[0].destroyed = true;
  h.notificationHost.open(item('first')); const created = h.windows[1];
  const other = new h.Window({}); h.setFocused(other); h.notificationHost.open(item('second'));
  const before = created.calls.length; created.emit('ready-to-show');
  assert.equal(created.calls.length, before + 1, 'existing startup show remains, but old notification must not raise/focus');
  assert.deepEqual(other.calls, ['show', 'moveTop', 'focus']);
});
