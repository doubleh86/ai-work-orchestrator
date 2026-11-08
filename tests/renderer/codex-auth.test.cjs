const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');
const { createRequire } = require('node:module');

const root = resolve(__dirname, '../..');
const tempRoot = join(root, '.tmp');
mkdirSync(tempRoot, { recursive: true });
const output = resolve(mkdtempSync(join(tempRoot, 'codex-auth-build-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/global.d.ts', 'desktop/renderer/src/CodexApiKeyConnection.tsx',
    'desktop/main/codexAuth.ts', 'desktop/shared/codexAuth.ts', 'desktop/shared/rpc.ts'],
  { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const { CodexAuthController, isOfficialAuthUrl } = require(join(output, 'main/codexAuth.js'));
const { codexAccountDetails } = require(join(output, 'shared/codexAuth.js'));

function waiting(overrides = {}) {
  return {
    status: 'waiting', attempt_id: 'attempt-1', method: 'device_code', started_at: '2026-09-11T00:00:00Z',
    auth_method: 'none', auth_label: '로그인 필요', auth_url: 'https://auth.openai.com/codex/device?state=secret',
    user_code: 'ABCD-EFGH', error_code: '', message: '', ...overrides,
  };
}

function fixture(response, openError = false) {
  const calls = [];
  const opened = [];
  const copied = [];
  const bridge = { async request(method, params) { calls.push([method, params]); return response; } };
  const host = {
    async openExternal(url) { opened.push(url); if (openError) throw new Error('browser failed'); },
    copyText(value) { copied.push(value); },
  };
  return { controller: new CodexAuthController(bridge, host), calls, opened, copied };
}

test('API key connection forwards only explicit SDK arguments without opening a browser or exposing identity', async () => {
  const { controller, calls, opened } = fixture(waiting({ status: 'connected', attempt_id: '', method: '',
    auth_method: 'api_key', auth_label: 'API 키 · 사용량 과금', account_email: 'old@example.invalid', plan_type: 'pro',
    apiKey: 'sk-fixture-only', access_token: 'private-token' }));
  const state = await controller.connectApiKey(' sk-fixture-only ', ' key-request ');
  assert.deepEqual(calls, [['auth.codex.apiKey', { apiKey: 'sk-fixture-only', requestId: 'key-request' }]]);
  assert.equal(opened.length, 0);
  assert.equal(state.auth_method, 'api_key');
  assert.equal(state.account_email, ''); assert.equal(state.plan_type, '');
  assert.doesNotMatch(JSON.stringify(state), /sk-fixture-only|private-token|old@example/);
  assert.match(codexAccountDetails(state).plan, /OpenAI API.*별도 과금/);
});

test('API key input validation stops malformed requests and transport errors never expose credentials', async () => {
  const { controller, calls } = fixture({});
  for (const key of ['', ' ', 'sk private', 'private\n', 'private\0', 's'.repeat(4097)]) {
    await assert.rejects(() => controller.connectApiKey(key, 'key-request'), /한 줄/);
  }
  assert.equal(calls.length, 0);
  controller.bridge = { async request() { throw new Error('private sk-fixture-only payload'); } };
  await assert.rejects(() => controller.connectApiKey('sk-fixture-only', 'key-request'), error => {
    assert.match(error.message, /연결을 확인하지 못했습니다/);
    assert.doesNotMatch(error.message, /sk-fixture-only|payload/);
    return true;
  });
});

function nodes(value) {
  return !value || typeof value !== 'object' ? []
    : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children)];
}

test('API key replacement opens on request and clears secrets before submission or on cancel', async () => {
  const path = join(output, 'renderer/src/CodexApiKeyConnection.js');
  const components = {}; const states = []; const refs = []; let stateIndex = 0; let refIndex = 0;
  runInNewContext(readFileSync(path, 'utf8'), { exports: components, require: name => name === 'react' ? {
    useState(initial) { const i = stateIndex++; if (!(i in states)) states[i] = initial; return [states[i], value => { states[i] = value; }]; },
    useRef(initial) { const i = refIndex++; return refs[i] ||= { current: initial }; },
  } : createRequire(path)(name) });
  let finish; const sent = [];
  const props = { connected: true, hasApiKey: true, busy: '', onConnect: key => {
    assert.equal(states[0], ''); sent.push(key); return new Promise(resolve => { finish = resolve; });
  } };
  const render = () => { stateIndex = 0; refIndex = 0; return components.CodexApiKeyConnection(props); };
  let tree = render();
  const openEditor = () => nodes(render()).find(n => n.type === 'button').props.onClick();
  assert.equal(nodes(tree).some(n => n.type === 'input'), false);
  assert.match(nodes(tree).find(n => n.type === 'button').props.children, /API 키 변경/);
  openEditor();
  tree = render();
  assert.equal(nodes(tree).find(n => n.type === 'input').props.type, 'password');
  assert.equal(nodes(tree).find(n => n.type === 'input').props.autoComplete, 'off');
  assert.equal(nodes(tree).find(n => n.type === 'button').props.disabled, true);
  nodes(tree).find(n => n.type === 'input').props.onChange({ target: { value: 'sk-fixture-only' } });
  tree = render();
  const form = nodes(tree).find(n => n.type === 'form');
  assert.equal(nodes(tree).find(n => n.type === 'button').props.disabled, false);
  const submitted = form.props.onSubmit({ preventDefault() {} });
  await form.props.onSubmit({ preventDefault() {} });
  assert.deepEqual(sent, ['sk-fixture-only']);
  assert.equal(nodes(render()).find(n => n.type === 'input').props.value, '');
  finish(false); await submitted;
  tree = render();
  nodes(tree).find(n => n.type === 'input').props.onChange({ target: { value: 'sk-fixture-only' } });
  props.blockedReason = '연결 상태 확인 후 연결';
  tree = render();
  assert.equal(nodes(tree).find(n => n.type === 'input').props.disabled, true);
  assert.equal(nodes(tree).find(n => n.type === 'button' && n.props.type === 'submit').props.disabled, true);
  await nodes(tree).find(n => n.type === 'form').props.onSubmit({ preventDefault() {} });
  assert.deepEqual(sent, ['sk-fixture-only'], 'unconfirmed auth cannot register another credential');

  props.blockedReason = '';
  nodes(render()).find(n => n.type === 'button' && n.props.children === '취소').props.onClick();
  assert.equal(nodes(render()).some(n => n.type === 'input'), false);
  openEditor();
  const input = nodes(render()).find(n => n.type === 'input');
  assert.equal(input.props.value, '');
  input.props.onChange({ target: { value: 'sk-fixture-replacement' } });
  const replacement = nodes(render()).find(n => n.type === 'form').props.onSubmit({ preventDefault() {} });
  finish(true); await replacement;
  assert.deepEqual(sent, ['sk-fixture-only', 'sk-fixture-replacement']);
  assert.equal(nodes(render()).some(n => n.type === 'input'), false);
});

test('only explicit HTTPS Codex authentication hosts are accepted', () => {
  assert.equal(isOfficialAuthUrl('https://auth.openai.com/oauth/authorize'), true);
  assert.equal(isOfficialAuthUrl('https://chatgpt.com/device'), true);
  assert.equal(isOfficialAuthUrl('http://auth.openai.com/oauth/authorize'), false);
  assert.equal(isOfficialAuthUrl('https://auth.openai.com:444/oauth/authorize'), false);
  assert.equal(isOfficialAuthUrl('https://auth.openai.com.evil.example/oauth'), false);
  assert.equal(isOfficialAuthUrl('file:///C:/secret'), false);
});

test('start opens the official URL but returns no URL to the renderer', async () => {
  const { controller, calls, opened, copied } = fixture(waiting());
  const state = await controller.start('device_code', 'request-1');
  assert.deepEqual(calls, [['auth.codex.start', { method: 'device_code', requestId: 'request-1' }]]);
  assert.equal(opened.length, 1);
  assert.match(opened[0], /^https:\/\/auth\.openai\.com\//);
  assert.equal(Object.hasOwn(state, 'auth_url'), false);
  assert.equal(state.user_code, 'ABCD-EFGH');
  assert.equal(controller.copyDeviceCode('attempt-1'), true);
  assert.deepEqual(copied, ['ABCD-EFGH']);
});

test('recovered login opens the official URL after a failed preflight and preserves its honest waiting notice', async () => {
  const notice = '기존 연결 상태를 확인하지 못해 새 인증 연결로 로그인을 시작했습니다.';
  const { controller, opened } = fixture(waiting({ method: 'browser', message: notice }));
  const state = await controller.start('browser', 'request-recovery');
  assert.equal(opened.length, 1);
  assert.equal(state.status, 'waiting');
  assert.equal(state.message, notice);
  assert.equal(Object.hasOwn(state, 'auth_url'), false);
});







test('untrusted URL is blocked without exposing it in the error', async () => {
  const { controller, opened } = fixture(waiting({ auth_url: 'https://evil.example/?token=private' }));
  const state = await controller.start('browser', 'request-1');
  assert.equal(opened.length, 0);
  assert.match(state.browser_open_error, /공식 Codex 로그인 주소/);
  assert.doesNotMatch(state.browser_open_error, /private/);
});

test('browser failures preserve the same attempt for reopen', async () => {
  const { controller, opened } = fixture(waiting({ method: 'browser', user_code: '' }), true);
  const state = await controller.start('browser', 'request-1');
  assert.match(state.browser_open_error, /기본 브라우저/);
  const polled = await controller.get('attempt-1');
  assert.match(polled.browser_open_error, /기본 브라우저/);
  const reopened = await controller.reopen('attempt-1');
  assert.match(reopened.browser_open_error, /다시 열기/);
  assert.equal(opened.length, 2);
});

test('terminal states discard device codes', async () => {
  const { controller } = fixture(waiting());
  await controller.start('device_code', 'request-1');
  const completed = waiting({ status: 'connected', auth_url: '', user_code: '', auth_method: 'chatgpt', auth_label: 'ChatGPT 구독 로그인' });
  controller.bridge = { async request() { return completed; } };
  await controller.get('attempt-1');
  assert.equal(controller.copyDeviceCode('attempt-1'), false);
});

test('public account display survives IPC while auth URL, raw account and tokens are excluded', async () => {
  const { controller } = fixture(waiting({ status: 'connected', auth_method: 'chatgpt', auth_label: 'ChatGPT 구독 로그인',
    account_email: 'fixture@example.invalid', plan_type: 'pro', access_token: 'do-not-forward', account: { raw: 'do-not-forward' } }));
  const state = await controller.status();
  assert.equal(state.account_email, 'fixture@example.invalid');
  assert.equal(state.plan_type, 'pro');
  assert.deepEqual(codexAccountDetails(state), { email: 'fixture@example.invalid', method: 'ChatGPT 구독 로그인', plan: 'Pro' });
  for (const key of ['auth_url', 'account', 'access_token']) assert.equal(Object.hasOwn(state, key), false);
});

test('refresh and new controller reflect the new account and discard values for non-ChatGPT or disconnected states', async () => {
  const connected = waiting({ status: 'connected', auth_method: 'chatgpt', account_email: 'first@example.invalid', plan_type: 'plus' });
  const { controller } = fixture(connected);
  assert.equal((await controller.status()).account_email, 'first@example.invalid');
  const next = { ...connected, account_email: 'next@example.invalid', plan_type: 'pro' };
  controller.bridge = { async request() { return next; } };
  assert.equal((await controller.status()).account_email, 'next@example.invalid');
  assert.equal((await fixture(next).controller.status()).account_email, 'next@example.invalid');
  for (const changes of [{ status: 'signed_out' }, { status: 'status_error' }, { auth_method: 'api_key' }, { auth_method: 'external' }]) {
    controller.bridge = { async request() { return { ...connected, ...changes }; } };
    const state = await controller.status();
    assert.equal(state.account_email, ''); assert.equal(state.plan_type, '');
    if (state.status !== 'connected') assert.equal(codexAccountDetails(state), undefined);
    else assert.doesNotMatch(codexAccountDetails(state).email, /first@example/);
  }
});

test('missing metadata stays explicit, long email is preserved and malformed metadata fails with no raw value', async () => {
  const missing = waiting({ status: 'connected', auth_method: 'chatgpt', account_email: null, plan_type: null });
  const { controller } = fixture(missing);
  const state = await controller.status();
  assert.match(codexAccountDetails(state).email, /이메일 정보가 제공되지/);
  assert.match(codexAccountDetails(state).plan, /요금제 정보가 제공되지/);
  const long = 'long-fixture'.repeat(18) + '@example.invalid';
  controller.bridge = { async request() { return { ...missing, account_email: long }; } };
  assert.equal((await controller.status()).account_email, long);
  for (const value of [3, 'secret-value\n@example.invalid', 'a'.repeat(321)]) {
    controller.bridge = { async request() { return { ...missing, account_email: value }; } };
    await assert.rejects(() => controller.status(), (error) => /계정 표시 정보를 확인하지/.test(error.message) && !error.message.includes('secret-value'));
  }
});
