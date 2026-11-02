const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');
const { createCipheriv, createDecipheriv, randomBytes } = require('node:crypto');

const root = resolve(__dirname, '../..'), temp = join(root, '.tmp');
fs.mkdirSync(temp, { recursive: true });
const output = fs.mkdtempSync(join(temp, 'nvidia-credentials-'));
process.on('exit', () => { assert.equal(dirname(output), temp); fs.rmSync(output, { recursive: true, force: true }); });
const pkg = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(pkg), require(pkg).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
  'desktop/main/nvidiaCredentials.ts', 'desktop/main/preload.ts', 'desktop/renderer/src/NvidiaConnectionPanel.tsx',
  'desktop/renderer/src/AiConnectionDialog.tsx',
  'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });
const storePath = join(output, 'main/nvidiaCredentials.js');
const { NvidiaCredentialStore } = require(storePath);
const encryptionKey = randomBytes(32);
const encryption = {
  isEncryptionAvailable: () => true, getSelectedStorageBackend: () => 'gnome_libsecret',
  encryptString(value) {
    const nonce = randomBytes(12), cipher = createCipheriv('aes-256-gcm', encryptionKey, nonce);
    const body = Buffer.concat([cipher.update(value, 'utf8'), cipher.final()]);
    return Buffer.concat([nonce, cipher.getAuthTag(), body]);
  },
  decryptString(value) {
    const cipher = createDecipheriv('aes-256-gcm', encryptionKey, value.subarray(0, 12), { authTagLength: 16 });
    cipher.setAuthTag(value.subarray(12, 28));
    return Buffer.concat([cipher.update(value.subarray(28)), cipher.final()]).toString('utf8');
  },
};
function file(name) { return join(output, `${name}.bin`); }
function store(name, crypto = encryption, env = false) { return new NvidiaCredentialStore(file(name), crypto, () => env); }
function loadStore({ filesystem = fs, platform = process.platform } = {}) {
  const exports = {};
  runInNewContext(fs.readFileSync(storePath, 'utf8'), { exports, process: { platform },
    require: name => name === 'node:fs' ? filesystem : require(name) });
  return exports.NvidiaCredentialStore;
}

test('encrypted key survives restart, replacement and deletion without a public readback', () => {
  const first = store('roundtrip', encryption, true);
  assert.equal(first.status().source, 'environment');
  const saved = first.save('fixture-secret-first');
  assert.equal(saved.source, 'app'); assert.equal(saved.error, '');
  assert.ok(!fs.readFileSync(file('roundtrip')).includes(Buffer.from('fixture-secret-first')));
  assert.ok(!JSON.stringify(saved).includes('fixture-secret-first'));
  const restored = store('roundtrip', encryption, true);
  assert.equal(restored.apiKey(), 'fixture-secret-first');
  restored.save('fixture-secret-second');
  assert.equal(store('roundtrip').apiKey(), 'fixture-secret-second');
  assert.equal(restored.delete().source, 'environment');
  assert.equal(restored.apiKey(), undefined);
  assert.equal(fs.existsSync(file('roundtrip')), false);
  assert.equal(store('roundtrip').status().source, 'none');
});

test('unavailable secure storage and Linux basic_text never write a credential', () => {
  for (const [name, Store, crypto] of [
    ['unavailable', NvidiaCredentialStore, { ...encryption, isEncryptionAvailable: () => false }],
    ['basic-text', loadStore({ platform: 'linux' }), { ...encryption, getSelectedStorageBackend: () => 'basic_text' }],
  ]) {
    const subject = new Store(file(name), crypto, () => false);
    assert.equal(subject.status().storageAvailable, false);
    assert.ok(subject.save('fixture-secret-first').error);
    assert.equal(subject.apiKey(), undefined); assert.equal(fs.existsSync(file(name)), false);
  }
});

test('corrupt stored data is explicit and can be replaced or removed', () => {
  fs.writeFileSync(file('corrupt'), 'not an encrypted key');
  const subject = store('corrupt');
  assert.ok(subject.status().error); assert.equal(subject.status().hasStoredKey, true);
  assert.equal(subject.apiKey(), undefined);
  assert.equal(subject.save('replacement-fixture').error, '');
  assert.equal(store('corrupt').apiKey(), 'replacement-fixture');
  assert.equal(subject.delete().hasStoredKey, false);
});

test('a keychain missing-item error cannot hide an existing encrypted credential as absent', () => {
  const initial = store('keychain-missing'); initial.save('fixture-kept-secret');
  const before = fs.readFileSync(file('keychain-missing'));
  const restored = store('keychain-missing', { ...encryption, decryptString() {
    throw Object.assign(Error('fixture-kept-secret'), { code: 'ENOENT' });
  } });
  assert.ok(restored.status().error); assert.equal(restored.status().hasStoredKey, true);
  assert.equal(restored.apiKey(), undefined); assert.ok(!JSON.stringify(restored.status()).includes('fixture-kept-secret'));
  assert.deepEqual(fs.readFileSync(file('keychain-missing')), before);
});

test('atomic write, encryption and deletion failures preserve the old credential and sanitize errors', () => {
  const initial = store('failure'); initial.save('old-fixture-secret');
  const encrypted = fs.readFileSync(file('failure'));
  const Store = loadStore({ filesystem: { ...fs,
    renameSync() { throw new Error('new-fixture-secret permission denied'); },
    unlinkSync(path) { if (path === file('failure')) throw new Error('old-fixture-secret denied'); fs.unlinkSync(path); },
  } });
  const subject = new Store(file('failure'), encryption, () => false);
  for (const status of [subject.save('new-fixture-secret'), subject.delete(), subject.save('bad\nkey')]) {
    assert.ok(status.error); assert.ok(!JSON.stringify(status).includes('fixture-secret'));
    assert.equal(subject.apiKey(), 'old-fixture-secret');
    assert.deepEqual(fs.readFileSync(file('failure')), encrypted);
  }
  const broken = store('failure', { ...encryption, encryptString() { throw new Error('new-fixture-secret'); } });
  assert.ok(broken.save('new-fixture-secret').error);
  assert.deepEqual(fs.readFileSync(file('failure')), encrypted);
  assert.equal(fs.readdirSync(output).filter(name => name.endsWith('.tmp')).length, 0);
});

test('legacy single-key ciphertext migrates without losing its credential or exposing plaintext metadata', () => {
  fs.writeFileSync(file('legacy'), encryption.encryptString('legacy-fixture-secret'));
  const subject = store('legacy');
  assert.equal(subject.apiKey(), 'legacy-fixture-secret'); assert.equal(subject.status().keys.length, 1);
  const original = subject.status().defaultKeyId;
  assert.equal(subject.save('review-fixture-secret', { label: '리뷰용' }).error, '');
  const reviewId = subject.status().keys.find(key => key.label === '리뷰용').id;
  assert.equal(subject.setRouting(original, { 'vendor/review-model': reviewId }).error, '');
  const restarted = store('legacy');
  assert.equal(restarted.apiKey(), 'legacy-fixture-secret');
  assert.deepEqual(restarted.modelApiKeys(), { 'vendor/review-model': 'review-fixture-secret' });
  assert.ok(!JSON.stringify(restarted.status()).includes('fixture-secret'));
  assert.ok(!fs.readFileSync(file('legacy')).includes(Buffer.from('fixture-secret')));
});

test('named keys retain routing across replacement and require explicit reassignment before deletion', () => {
  const subject = store('named'); subject.save('first-fixture', { label: '코딩용' });
  const first = subject.status().defaultKeyId;
  subject.save('second-fixture', { label: '리뷰용' });
  const second = subject.status().keys.find(key => key.label === '리뷰용').id;
  assert.equal(subject.status().defaultKeyId, first);
  assert.ok(subject.delete(first).error); assert.equal(subject.apiKey(), 'first-fixture');
  subject.setRouting(first, { 'vendor/review': second });
  assert.ok(subject.delete(second).error); assert.equal(subject.status().keys.length, 2);
  subject.save('second-replaced-fixture', { id: second, label: '리뷰용' });
  assert.equal(subject.modelApiKeys()['vendor/review'], 'second-replaced-fixture');
  assert.ok(subject.setRouting(first, { 'vendor/review': 'nonexistent-id' }).error);
  assert.equal(subject.modelApiKeys()['vendor/review'], 'second-replaced-fixture');
  assert.ok(subject.save('invalid-fixture', { label: '리뷰용' }).error);
  assert.equal(subject.setRouting(second, {}).error, ''); assert.equal(subject.apiKey(), 'second-replaced-fixture');
  assert.equal(subject.delete(first).error, ''); assert.equal(subject.status().keys.length, 1);
  assert.equal(subject.delete(second).error, ''); assert.equal(subject.status().source, 'none');
});

test('failed routing persistence preserves the previous encrypted mapping and private snapshot', () => {
  const subject = store('routing-failure'); subject.save('default-fixture', { label: '코딩용' });
  subject.save('review-fixture', { label: '리뷰용' });
  const status = subject.status(), before = fs.readFileSync(file('routing-failure'));
  const Store = loadStore({ filesystem: { ...fs, renameSync() { throw Error('review-fixture'); } } });
  const restored = new Store(file('routing-failure'), encryption, () => false);
  assert.ok(restored.setRouting(status.keys[1].id, { 'vendor/model': status.keys[1].id }).error);
  assert.equal(restored.apiKey(), 'default-fixture'); assert.equal(Object.keys(restored.modelApiKeys()).length, 0);
  assert.deepEqual(fs.readFileSync(file('routing-failure')), before);
  assert.equal(restored.status().defaultKeyId, status.defaultKeyId);
});

test('a registered model can follow default key changes without losing its model entry', () => {
  const subject = store('inherit-default'); subject.save('first-fixture', { label: '코딩용' });
  const first = subject.status().defaultKeyId;
  subject.save('second-fixture', { label: '리뷰용' }); const second = subject.status().keys[1].id;
  assert.equal(subject.setRouting(first, { 'vendor/model': '' }).error, '');
  assert.equal(subject.modelApiKeys()['vendor/model'], 'first-fixture');
  subject.setRouting(second, subject.status().modelBindings);
  assert.equal(subject.modelApiKeys()['vendor/model'], 'second-fixture');
  assert.ok(Object.hasOwn(subject.status().modelBindings, 'vendor/model'));
  assert.equal(store('inherit-default').modelApiKeys()['vendor/model'], 'second-fixture');
  subject.delete(first); assert.ok(subject.delete(second).error);
  assert.equal(subject.apiKey(), 'second-fixture');
  subject.setRouting(second, {}); assert.equal(subject.delete(second).error, '');
});

test('preload exposes fixed credential operations without generic secret or environment APIs', async () => {
  const calls = []; let api;
  runInNewContext(fs.readFileSync(join(output, 'main/preload.js'), 'utf8'), { exports: {},
    require: name => {
      assert.equal(name, 'electron');
      return { contextBridge: { exposeInMainWorld(_name, value) { api = value; } },
        ipcRenderer: { async invoke(...args) { calls.push(args); return { configured: false }; } } };
    } });
  await api.nvidiaCredentialStatus(); await api.saveNvidiaCredential('fixture-only'); await api.deleteNvidiaCredential();
  await api.setNvidiaCredentialRouting('key-id', { 'vendor/model': 'key-id' });
  assert.deepEqual(calls, [['orchestrator:nvidia-credential-status'], ['orchestrator:nvidia-credential-save', 'fixture-only', undefined],
    ['orchestrator:nvidia-credential-delete', undefined], ['orchestrator:nvidia-credential-routing', 'key-id', { 'vendor/model': 'key-id' }]]);
  await assert.rejects(api.request('environment.set', { name: 'PATH' }), /Unsupported RPC/);
  assert.equal(calls.length, 4);
});

function panelHarness(initial) {
  const path = join(output, 'renderer/src/NvidiaConnectionPanel.js'), local = createRequire(path), exports = {};
  let index = 0, effectDeps, pendingEffect, cleanup;
  const state = [], calls = [], status = { configured: false, source: 'none', hasStoredKey: false, storageAvailable: true,
    keys: [], defaultKeyId: '', modelBindings: {}, error: '', ...initial };
  const api = {
    async nvidiaCredentialStatus() { return { ...status }; },
    async saveNvidiaCredential(key, options) { calls.push(['save', key, { ...options }]);
      const id = options.id || `key-${status.keys.length + 1}`;
      Object.assign(status, { source: 'app', hasStoredKey: true, defaultKeyId: status.defaultKeyId || id,
        keys: [...status.keys.filter(item => item.id !== id), { id, label: options.label }] }); return { ...status }; },
    async deleteNvidiaCredential(id) { calls.push(['delete', id]);
      Object.assign(status, { source: 'environment', hasStoredKey: false, keys: [], defaultKeyId: '' }); return { ...status }; },
    async setNvidiaCredentialRouting(defaultKeyId, modelBindings) {
      calls.push(['route', defaultKeyId, { ...modelBindings }]); Object.assign(status, { defaultKeyId, modelBindings }); return { ...status }; },
  };
  runInNewContext(fs.readFileSync(path, 'utf8'), { exports, window: { orchestrator: api }, require: name => name === 'react' ? {
    useId: () => 'key-input', useState(initial) { const slot = index++; if (!(slot in state)) state[slot] = initial;
      return [state[slot], value => { state[slot] = value; }]; },
    useEffect(callback, deps) { if (!effectDeps || deps.some((v, i) => v !== effectDeps[i])) { effectDeps = deps; pendingEffect = callback; } },
  } : local(name) });
  const props = { visible: true, async onChanged() { calls.push(['refresh']); } };
  return { calls, status, api, props, render() { index = 0; const tree = exports.NvidiaConnectionPanel(props);
    if (pendingEffect) { cleanup?.(); cleanup = pendingEffect(); pendingEffect = undefined; } return tree; } };
}
const tick = () => new Promise(resolve => setImmediate(resolve));
function nodes(tree) { if (!tree || typeof tree !== 'object') return []; return Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)]; }
function text(tree) { return typeof tree === 'string' ? tree : Array.isArray(tree) ? tree.map(text).join('') : text(tree?.props?.children || ''); }
const password = tree => nodes(tree).find(node => node.type === 'input' && node.props.type === 'password');
function submit(tree, label = 'NVIDIA 키 추가') {
  nodes(tree).find(node => node.type === 'form' && node.props['aria-label'] === label).props.onSubmit({ preventDefault() {} });
}

test('masked form saves once, clears plaintext, refreshes choices and explains environment fallback on delete', async () => {
  const h = panelHarness(); h.render(); await tick();
  let tree = h.render(), input = password(tree);
  assert.equal(input.props.type, 'password'); assert.equal(input.props.autoComplete, 'off');
  assert.equal(nodes(tree).find(node => node.type === 'button').props.disabled, true);
  input.props.onChange({ target: { value: 'fixture-secret-input' } }); tree = h.render();
  submit(tree); await tick(); tree = h.render();
  assert.deepEqual(h.calls, [['save', 'fixture-secret-input', { label: '기본 키' }], ['refresh']]);
  assert.equal(password(tree).props.value, '');
  assert.match(text(tree), /다음 요청부터/);
  nodes(tree).find(node => node.type === 'button' && text(node) === '삭제').props.onClick();
  await tick(); tree = h.render(); assert.match(text(tree), /환경 변수의 키를 사용/);
  assert.deepEqual(h.calls.at(-1), ['refresh']);
});

test('save errors stay visible without refresh and IPC errors never echo the key', async () => {
  const h = panelHarness(); h.render(); await tick();
  h.api.saveNvidiaCredential = async () => ({ ...h.status, error: '저장 실패' });
  let tree = h.render(); password(tree).props.onChange({ target: { value: 'fixture-secret' } });
  tree = h.render(); submit(tree); await tick();
  assert.match(text(h.render()), /저장 실패/); assert.equal(h.calls.length, 0);
  h.api.saveNvidiaCredential = async () => { throw Error('fixture-secret'); };
  submit(h.render()); await tick();
  assert.ok(!text(h.render()).includes('fixture-secret'));
  h.props.visible = false; h.render(); assert.equal(password(h.render()).props.value, '');
});

test('a refresh failure does not misreport a successfully saved credential', async () => {
  const h = panelHarness(); h.props.onChanged = async () => { throw Error('fixture-secret'); };
  h.render(); await tick();
  let tree = h.render(); password(tree).props.onChange({ target: { value: 'fixture-secret' } });
  tree = h.render(); submit(tree); await tick(); tree = h.render();
  assert.equal(password(tree).props.value, '');
  assert.match(text(tree), /키를 저장했습니다/); assert.match(text(tree), /키 설정은 반영했지만 연결 상태/);
  assert.ok(!text(tree).includes('fixture-secret'));
});

test('model routing is changed by key ID while password replacement preserves its named entry', async () => {
  const h = panelHarness({ source: 'app', configured: true, hasStoredKey: true, defaultKeyId: 'first',
    keys: [{ id: 'first', label: '코딩용' }, { id: 'second', label: '리뷰용' }], modelBindings: { 'vendor/review': 'second' } });
  h.render(); await tick();
  let tree = h.render();
  nodes(tree).find(node => node.type === 'select' && node.props['aria-label'] === 'NVIDIA 기본 키').props.onChange({ target: { value: 'second' } });
  await tick(); assert.deepEqual(h.calls[0], ['route', 'second', { 'vendor/review': 'second' }]);
  tree = h.render(); nodes(tree).find(node => node.type === 'button' && node.props['aria-label'] === 'vendor/review 모델 삭제').props.onClick();
  await tick(); assert.deepEqual(h.calls.at(-2), ['route', 'second', {}]);
  tree = h.render(); nodes(tree).find(node => node.type === 'button' && node.props['aria-label'] === '리뷰용 교체').props.onClick();
  tree = h.render(); password(tree).props.onChange({ target: { value: 'replacement-fixture' } });
  submit(h.render(), 'NVIDIA 키 교체'); await tick();
  assert.deepEqual(h.calls.at(-2), ['save', 'replacement-fixture', { id: 'second', label: '리뷰용' }]);
  assert.equal(password(h.render()).props.value, '');
});

test('the common AI connection dialog exposes NVIDIA even when Codex is connected and preserves both connections on selection', () => {
  const path = join(output, 'renderer/src/AiConnectionDialog.js'), local = createRequire(path), exports = {}, states = [];
  let index = 0, closed = 0, refreshed = 0;
  const props = { codexState: { status: 'connected' }, children: { type: 'p', props: { children: '현재 Codex 계정' } },
    onClose() { closed++; }, async onNvidiaChanged() { refreshed++; } };
  runInNewContext(fs.readFileSync(path, 'utf8'), { exports, require: name => name === 'react' ? {
    useState(initial) { const slot = index++; if (!(slot in states)) states[slot] = initial;
      return [states[slot], value => { states[slot] = value; }]; }, useRef: () => ({ current: null }), useEffect() {},
  } : local(name) });
  const render = () => { index = 0; return exports.AiConnectionDialog(props); };
  let tree = render(); assert.match(text(tree), /AI 연결/);
  const codexPanel = nodes(tree).find(node => node.props?.id === 'codex-connection-panel');
  assert.equal(codexPanel.props.hidden, false); assert.equal(codexPanel.props.children, props.children);
  const nvidia = nodes(tree).find(node => node.type === 'button' && text(node).startsWith('NVIDIA'));
  nvidia.props.onClick(); tree = render();
  assert.equal(nodes(tree).find(node => node.props?.id === 'codex-connection-panel').props.hidden, true);
  assert.equal(nodes(tree).find(node => node.props?.id === 'nvidia-connection-panel').props.hidden, false);
  assert.ok(text(tree).includes('연결됨'));
  nodes(tree).find(node => node.type === 'button' && text(node).startsWith('Codex')).props.onClick(); tree = render();
  assert.equal(nodes(tree).find(node => node.props?.id === 'codex-connection-panel').props.children, props.children);
  assert.equal(closed, 0); assert.equal(refreshed, 0);
});
