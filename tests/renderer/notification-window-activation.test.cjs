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

async function host({ trayUnavailable = false, stopBackend = () => Promise.resolve(), platform = 'win32' } = {}) {
  const windows = [], notifications = [], handlers = new Map(), deferred = [], requests = [], trays = [], errors = [];
  const shutdown = { backend: 0, notifications: 0 };
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
    hide() { this.calls.push('hide'); this.visible = false; }
    moveTop() { this.calls.push('moveTop'); }
    focus() { this.calls.push('focus'); focused = this; }
  }
  class OsNotification extends EventEmitter {
    constructor(options) { super(); this.options = options; notifications.push(this); }
    static isSupported() { return true; }
    show() { this.shown = true; }
  }
  class Tray extends EventEmitter {
    constructor() { super(); if (trayUnavailable) throw new Error('Tray unavailable'); this.destroyed = false; trays.push(this); }
    setToolTip(value) { this.tooltip = value; }
    setContextMenu(value) { this.menu = value; }
    isDestroyed() { return this.destroyed; }
    destroy() { this.destroyed = true; }
  }
  const dock = { visible: true, calls: [], isVisible() { return this.visible; }, hide() { this.calls.push('hide'); this.visible = false; },
    show() { this.calls.push('show'); this.visible = true; return Promise.resolve(); } };
  const app = Object.assign(new EventEmitter(), { quitCount: 0, dock, whenReady: () => Promise.resolve(), getPath: () => output,
    quit() { this.quitCount++; this.emit('before-quit'); } });
  const dialog = { choice: 0, showMessageBoxSync() { return this.choice; }, showErrorBox(...args) { errors.push(args); } };
  const electron = { app, BrowserWindow: Window, Notification: OsNotification, Tray,
    nativeImage: { createFromDataURL: () => ({ isEmpty: () => false, resize() { return this; }, setTemplateImage() {} }) },
    ipcMain: { handle: (name, fn) => handlers.set(name, fn), removeHandler: name => handlers.delete(name) },
    Menu: { setApplicationMenu() {}, buildFromTemplate: template => template }, clipboard: {}, shell: {}, dialog };
  const bridge = { bundledBackendExecutable() {}, PythonBridge: class {
    setNvidiaApiKey() {} setClaudeApiKey() {} start() {} request(...args) { requests.push(args); return Promise.resolve(); }
    stop() { shutdown.backend++; return stopBackend(); }
  } };
  const center = { WorkNotificationCenter: class {
    constructor(_path, _bridge, value) { notificationHost = value; }
    start() {} snapshot() { return { items: [] }; } markRead(id) { return { read: id }; }
    stop() { shutdown.notifications++; }
  } };
  const desktopTray = {};
  runInNewContext(readFileSync(join(output, 'main/desktopTray.js'), 'utf8'), {
    exports: desktopTray, require: name => name === 'electron' ? electron : mainRequire(name), process: { platform, stderr: { write() {} } },
  });
  runInNewContext(readFileSync(mainPath, 'utf8'), { exports: {}, __dirname: dirname(mainPath),
    process: { platform, resourcesPath: output, env: {}, stderr: { write() {} } },
    setImmediate: fn => deferred.push(fn),
    require: name => name === 'electron' ? electron : name === './pythonBridge' ? bridge
      : name === './workNotifications' ? center : name === './desktopTray' ? desktopTray
      : name === './codexAuth' ? { CodexAuthController: class { clear() {} } } : mainRequire(name) });
  await Promise.resolve();
  return { windows, notifications, handlers, deferred, requests, Window, app, dock, trays, dialog, errors, shutdown,
    get notificationHost() { return notificationHost; }, setFocused(value) { focused = value; } };
}
const item = id => ({ event_id: id, project_name: 'project', run_id: id, target_kind: 'task', target_id: `task-${id}` });
function cancellableEvent() {
  return { prevented: false, preventDefault() { this.prevented = true; } };
}

test('window close hides without stopping work, and tray actions reopen the same window', async () => {
  const h = await host(), w = h.windows[0], tray = h.trays[0];
  w.visible = true;
  const close = cancellableEvent(); w.emit('close', close);
  assert.equal(close.prevented, true); assert.equal(w.visible, false); assert.equal(w.destroyed, false);
  assert.equal(h.app.quitCount, 0); assert.equal(h.shutdown.backend, 0); assert.equal(h.shutdown.notifications, 0);
  assert.ok(h.handlers.has('orchestrator:request'));
  assert.equal(tray.tooltip, 'AI Work Orchestrator');
  for (const open of [() => tray.emit('click'), () => tray.menu.find(entry => entry.label === '열기').click()]) {
    w.calls = []; w.minimized = true; open();
    assert.deepEqual(w.calls, ['restore', 'show', 'moveTop', 'focus']);
    assert.equal(w.visible, true); assert.equal(h.windows.length, 1);
  }
  w.visible = false; w.calls = []; h.app.emit('activate');
  assert.deepEqual(w.calls, ['show', 'moveTop', 'focus']);
});

test('macOS close hides the Electron Dock icon and tray restore shows it again', async () => {
  const h = await host({ platform: 'darwin' }), w = h.windows[0], tray = h.trays[0];
  w.visible = true;
  const close = cancellableEvent(); w.emit('close', close);
  assert.equal(close.prevented, true);
  assert.equal(w.visible, false);
  assert.deepEqual(h.dock.calls, ['hide']);
  assert.equal(h.app.quitCount, 0);
  tray.menu.find(entry => entry.label === '열기').click();
  await Promise.resolve();
  assert.deepEqual(h.dock.calls, ['hide', 'show']);
  assert.equal(w.visible, true);
  assert.equal(h.windows.length, 1);
});

test('cancelling quit preserves drafts and restores close-to-tray for a later quit attempt', async () => {
  const h = await host(), w = h.windows[0], tray = h.trays[0];
  const quit = () => tray.menu.find(entry => entry.label === '종료').click();
  quit();
  const closing = cancellableEvent(); w.emit('close', closing);
  assert.equal(closing.prevented, false);
  const unload = cancellableEvent(); w.webContents.emit('will-prevent-unload', unload);
  assert.equal(unload.prevented, false, 'continue editing must keep Electron from discarding drafts');
  assert.equal(w.visible, true); assert.equal(h.shutdown.backend, 0);
  const hide = cancellableEvent(); w.emit('close', hide);
  assert.equal(hide.prevented, true); assert.equal(w.visible, false);
  quit();
  h.dialog.choice = 1;
  const discard = cancellableEvent(); w.webContents.emit('will-prevent-unload', discard);
  assert.equal(discard.prevented, true, 'discard explicitly permits Electron to close');
  const retried = cancellableEvent(); w.emit('close', retried);
  assert.equal(retried.prevented, false); assert.equal(h.app.quitCount, 2);
});

test('actual quit stops the backend once and removes the tray only after cleanup', async () => {
  let finish;
  const stopped = new Promise(resolve => { finish = resolve; });
  const h = await host({ stopBackend: () => stopped }), tray = h.trays[0];
  h.app.quit();
  const closing = cancellableEvent(); h.windows[0].emit('close', closing);
  assert.equal(closing.prevented, false, 'app quit also bypasses hiding');
  const first = cancellableEvent(), repeated = cancellableEvent();
  h.app.emit('will-quit', first); h.app.emit('will-quit', repeated);
  assert.equal(first.prevented, true); assert.equal(repeated.prevented, true);
  assert.equal(h.shutdown.backend, 1); assert.equal(h.shutdown.notifications, 1);
  assert.equal(h.handlers.has('orchestrator:request'), false); assert.equal(tray.isDestroyed(), false);
  const calls = h.windows[0].calls.length; tray.emit('click');
  assert.equal(h.windows[0].calls.length, calls, 'do not reopen a window during shutdown');
  finish(); await stopped; await Promise.resolve();
  assert.equal(tray.isDestroyed(), true); assert.equal(h.app.quitCount, 2);
  const final = cancellableEvent(); h.app.emit('will-quit', final);
  assert.equal(final.prevented, false); assert.equal(h.shutdown.backend, 1);
});

test('tray creation failure is visible and leaves normal window closing available', async () => {
  const h = await host({ trayUnavailable: true }), close = cancellableEvent();
  assert.equal(h.errors.length, 1); assert.equal(h.trays.length, 0);
  h.windows[0].emit('close', close); assert.equal(close.prevented, false);
  h.app.emit('window-all-closed'); assert.equal(h.app.quitCount, 1);
});

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
