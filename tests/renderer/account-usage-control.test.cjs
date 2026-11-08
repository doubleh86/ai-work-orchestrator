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
const output = mkdtempSync(join(temp, 'account-usage-control-'));
process.on('exit', () => { assert.equal(dirname(output), temp); rmSync(output, { recursive: true, force: true }); });
const pkg = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(pkg), require(pkg).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'Node16', '--types', 'node', '--jsx', 'react-jsx', '--skipLibCheck', '--rootDir', 'desktop', '--outDir', output,
  'desktop/renderer/src/AccountUsageControl.tsx', 'desktop/main/claudeLogin.ts', 'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });

test('AI usage opens two independent read-only queries and displays quota windows next to the other account state', async () => {
  const path = join(output, 'renderer/src/AccountUsageControl.js');
  const localRequire = createRequire(path);
  const slots = [], calls = [], responses = {};
  let cursor = 0;
  const hooks = {
    useRef(value) { return slots[cursor++] ||= { current: value }; },
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = initial;
      return [slots[index], (next) => { slots[index] = typeof next === 'function' ? next(slots[index]) : next; }];
    },
  };
  const exports = {};
  runInNewContext(readFileSync(path, 'utf8'), { exports, window: { orchestrator: {
    request(method, { provider }) {
      calls.push([method, provider]);
      return new Promise((resolve, reject) => { responses[provider] = { resolve, reject }; });
    },
  } }, require: (name) => name === 'react' ? hooks : localRequire(name) });
  const render = () => { cursor = 0; return exports.AccountUsageControl(); };

  let [button, dialog] = render().props.children;
  assert.equal(dialog, null);
  assert.deepEqual(calls, []);
  button.props.onClick();
  button.props.onClick();
  assert.deepEqual(calls, [['providers.accountUsage', 'codex'], ['providers.accountUsage', 'claude']]);
  responses.claude.resolve({ status: 'available',
    five_hour: { used_percent: 42, resets_at: null, reset_label: 'Nov 6, 3:29pm (Asia/Seoul)' }, weekly: null });
  responses.codex.reject(Error('Codex connection failed'));
  await new Promise((done) => setImmediate(done));
  [button, dialog] = render().props.children;
  const markup = renderToStaticMarkup(dialog.props.children);
  assert.match(markup, /Codex.*사용량을 확인하지 못했습니다/);
  assert.match(markup, /Claude.*5시간.*42% 사용.*Nov 6, 3:29pm.*주간.*미제공/);
  assert.equal(dialog.props.footer.props.disabled, false);
  dialog.props.footer.props.onClick();
  assert.equal(calls.length, 4);
  responses.codex.resolve({ status: 'api_key', five_hour: null, weekly: null });
  responses.claude.resolve({ status: 'signed_out', five_hour: null, weekly: null });
  await new Promise((done) => setImmediate(done));
  assert.match(renderToStaticMarkup(render().props.children[1].props.children), /API 키로 연결됨.*구독 계정으로 로그인/);
});

test('Claude login exposes only a fixed official command, propagates spawn errors and never requests a shell', async () => {
  const modulePath = join(output, 'main/claudeLogin.js'), local = createRequire(modulePath), exports = {};
  let options, command, child;
  const listeners = new Map();
  runInNewContext(readFileSync(modulePath, 'utf8'), { exports, process: { platform: 'win32' },
    require: name => name === 'node:child_process' ? { spawn(executable, args, opts) {
      command = [executable, args]; options = opts;
      child = { once(event, callback) { listeners.set(event, callback); }, unref() {} }; return child;
    } } : local(name) });
  const pending = exports.openClaudeLogin('isolated-temp');
  assert.equal(command[0], 'powershell.exe'); assert.equal(command[1].at(-1), 'claude auth login');
  assert.equal(options.shell, false); assert.equal(options.windowsHide, false); assert.equal(options.cwd, 'isolated-temp');
  listeners.get('spawn')(); assert.equal(await pending, true);
  const failure = exports.openClaudeLogin('isolated-temp'); listeners.get('error')(new Error('private detail'));
  await assert.rejects(failure, /Claude 로그인 터미널/);
  const selected = String.raw`C:\Program Files\O'Neil\claude.cmd`;
  const selectedLogin = exports.openClaudeLogin('isolated-temp', selected);
  assert.equal(command[1].at(-1), String.raw`& 'C:\Program Files\O''Neil\claude.cmd' auth login`);
  assert.equal(options.shell, false);
  listeners.get('spawn')(); assert.equal(await selectedLogin, true);
});

test('macOS Claude login passes a selected executable as an AppleScript argument', () => {
  const modulePath = join(output, 'main/claudeLogin.js'), local = createRequire(modulePath), exports = {};
  runInNewContext(readFileSync(modulePath, 'utf8'), { exports, process: { platform: 'darwin' }, require: local });
  const selected = "/Users/example/Claude's Tools/claude";
  const command = exports.claudeLoginCommand('darwin', selected);
  assert.equal(command.executable, 'osascript');
  assert.equal(command.args.at(-1), selected);
  assert.match(command.args.join(' '), /quoted form of item 1 of argv/);
  assert.equal(command.args.filter(value => value.includes(selected)).length, 1);
  assert.deepEqual(Array.from(exports.claudeLoginCommand('linux', selected).args), ['-e', selected, 'auth', 'login']);
});
