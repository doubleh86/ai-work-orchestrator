const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');
const { createCipheriv, createDecipheriv, randomBytes } = require('node:crypto');
const { renderToStaticMarkup } = require('react-dom/server');
const root = resolve(__dirname, '../..'), temp = join(root, '.tmp');
fs.mkdirSync(temp, { recursive: true });
const output = fs.mkdtempSync(join(temp, 'claude-api-key-'));
process.on('exit', () => { assert.equal(dirname(output), temp); fs.rmSync(output, { recursive: true, force: true }); });
const pkg = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(pkg), require(pkg).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
  'desktop/main/claudeCredentials.ts', 'desktop/main/preload.ts', 'desktop/renderer/src/ClaudeApiKeyConnection.tsx',
  'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });
const storePath = join(output, 'main/claudeCredentials.js');
const { ClaudeCredentialStore } = require(storePath);
const encryptionKey = randomBytes(32);
const encryption = {
  isEncryptionAvailable: () => true, getSelectedStorageBackend: () => 'gnome_libsecret',
  encryptString(value) {
    const nonce = randomBytes(12), cipher = createCipheriv('aes-256-gcm', encryptionKey, nonce);
    const body = Buffer.concat([cipher.update(value, 'utf8'), cipher.final()]);
    return Buffer.concat([nonce, cipher.getAuthTag(), body]);
  },
  decryptString(value) {
    const cipher = createDecipheriv('aes-256-gcm', encryptionKey, value.subarray(0, 12));
    cipher.setAuthTag(value.subarray(12, 28));
    return Buffer.concat([cipher.update(value.subarray(28)), cipher.final()]).toString('utf8');
  },
};
function loadStore({ filesystem = fs, platform = process.platform } = {}) {
  const exports = {};
  runInNewContext(fs.readFileSync(storePath, 'utf8'), { exports, process: { platform },
    require: name => name === 'node:fs' ? filesystem : require(name) });
  return exports.ClaudeCredentialStore;
}

test('Claude app key is encrypted, survives restart, and replacement/deletion never expose the value', () => {
  const path = join(output, 'key.bin'), subject = new ClaudeCredentialStore(path, encryption, () => true);
  assert.equal(subject.status().source, 'environment');
  const status = subject.save('fixture-private-first');
  assert.equal(status.source, 'app'); assert.equal(status.error, '');
  assert.equal(fs.readFileSync(path).includes(Buffer.from('fixture-private-first')), false);
  assert.equal(JSON.stringify(status).includes('fixture-private-first'), false);
  const reopened = new ClaudeCredentialStore(path, encryption, () => false);
  assert.equal(reopened.apiKey(), 'fixture-private-first');
  reopened.save('fixture-private-second');
  assert.equal(new ClaudeCredentialStore(path, encryption, () => false).apiKey(), 'fixture-private-second');
  assert.ok(reopened.save('invalid\nkey').error); assert.equal(reopened.apiKey(), 'fixture-private-second');
  subject.delete(); assert.equal(subject.status().source, 'environment'); assert.equal(subject.apiKey(), undefined);
  assert.equal(fs.existsSync(path), false);
});

test('Claude secure-store failures are explicit, never use plaintext, and preserve the previous key on write failure', () => {
  for (const [name, Store, crypto] of [
    ['unavailable', ClaudeCredentialStore, { ...encryption, isEncryptionAvailable: () => false }],
    ['basic-text', loadStore({ platform: 'linux' }), { ...encryption, getSelectedStorageBackend: () => 'basic_text' }],
  ]) {
    const path = join(output, name), subject = new Store(path, crypto, () => false);
    assert.ok(subject.save('fixture-key').error); assert.equal(subject.apiKey(), undefined); assert.equal(fs.existsSync(path), false);
  }
  const path = join(output, 'atomic-key');
  new ClaudeCredentialStore(path, encryption, () => false).save('fixture-old');
  const Store = loadStore({ filesystem: { ...fs, renameSync() { throw Error('disk failure'); } } });
  const failing = new Store(path, encryption, () => false);
  assert.ok(failing.save('fixture-new').error); assert.equal(failing.apiKey(), 'fixture-old');
  assert.equal(new ClaudeCredentialStore(path, encryption, () => false).apiKey(), 'fixture-old');
  fs.writeFileSync(path, 'corrupt fixture');
  const corrupt = new ClaudeCredentialStore(path, encryption, () => false);
  assert.ok(corrupt.status().error); assert.equal(corrupt.status().hasStoredKey, true);
  assert.equal(corrupt.delete().hasStoredKey, false); assert.equal(corrupt.status().error, '');
});

function nodes(tree) { if (!tree || typeof tree !== 'object') return []; return Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)]; }
const tick = () => new Promise(resolve => setImmediate(resolve));
const status = extra => ({ source: 'none', hasStoredKey: false, storageAvailable: true, error: '', ...extra });
function view() {
  let cursor = 0, props = { visible: true, busy: false }, changed = 0;
  const slots = [], effects = [], scheduled = [], calls = [];
  const api = Object.fromEntries(['claudeCredentialStatus', 'saveClaudeCredential', 'deleteClaudeCredential'].map(method =>
    [method, (...args) => new Promise((resolve, reject) => calls.push({ method, args, resolve, reject }))]));
  const hooks = {
    useState(initial) { const index = cursor++; if (!(index in slots)) slots[index] = initial; return [slots[index], value => { slots[index] = value; }]; },
    useRef(initial) { const index = cursor++; return slots[index] ||= { current: initial }; },
    useEffect(callback, deps) {
      const index = cursor++, previous = effects[index];
      if (!previous || deps.some((value, i) => value !== previous.deps[i])) {
        effects[index] = { deps, cleanup: previous?.cleanup };
        scheduled.push(() => { effects[index].cleanup?.(); effects[index].cleanup = callback(); });
      }
    },
  };
  const modulePath = join(output, 'renderer/src/ClaudeApiKeyConnection.js'), local = createRequire(modulePath), exports = {};
  runInNewContext(fs.readFileSync(modulePath, 'utf8'), { exports, window: { orchestrator: api }, require: name => name === 'react' ? hooks : local(name) });
  return { calls, get changed() { return changed; }, render(patch = {}) {
    props = { ...props, ...patch }; cursor = 0;
    const tree = exports.ClaudeApiKeyConnection({ ...props, onChanged: async () => { changed++; } });
    for (const effect of scheduled.splice(0)) effect(); return tree;
  } };
}

test('Claude key form clears input before sending, blocks duplicate saves, and refreshes after save and delete', async () => {
  const h = view(); h.render(); h.calls[0].resolve(status()); await tick();
  let tree = h.render(), input = nodes(tree).find(node => node.type === 'input');
  assert.equal(input.props.type, 'password'); assert.equal(input.props.autoComplete, 'off');
  input.props.onChange({ target: { value: 'fixture-private-key' } }); tree = h.render();
  const submit = nodes(tree).find(node => node.type === 'form').props.onSubmit;
  submit({ preventDefault() {} }); submit({ preventDefault() {} });
  assert.equal(h.calls.filter(call => call.method === 'saveClaudeCredential').length, 1);
  assert.equal(h.calls.at(-1).args[0], 'fixture-private-key');
  tree = h.render(); assert.equal(nodes(tree).find(node => node.type === 'input').props.value, '');
  assert.doesNotMatch(renderToStaticMarkup(tree), /fixture-private-key/);
  h.calls.at(-1).resolve(status({ source: 'app', hasStoredKey: true })); await tick();
  tree = h.render(); assert.equal(h.changed, 1); assert.match(renderToStaticMarkup(tree), /별도 과금|다음 Claude 요청/);
  nodes(tree).find(node => node.type === 'button' && node.props.children === '앱 키 삭제').props.onClick();
  assert.equal(h.calls.at(-1).method, 'deleteClaudeCredential');
  h.calls.at(-1).resolve(status()); await tick(); assert.equal(h.changed, 2);
});

test('failed and late key requests never echo the secret or overwrite a newly opened panel', async () => {
  const h = view(); h.render(); h.calls[0].resolve(status()); await tick();
  let tree = h.render(); nodes(tree).find(node => node.type === 'input').props.onChange({ target: { value: 'fixture-secret' } });
  tree = h.render(); nodes(tree).find(node => node.type === 'form').props.onSubmit({ preventDefault() {} });
  h.calls.at(-1).reject(Error('transport echoed fixture-secret')); await tick();
  tree = h.render(); assert.doesNotMatch(renderToStaticMarkup(tree), /fixture-secret/); assert.match(renderToStaticMarkup(tree), /변경하지 못했습니다/);
  h.render({ visible: false }); h.render({ visible: true }); const old = h.calls.at(-1);
  h.render({ visible: false }); h.render({ visible: true }); h.calls.at(-1).resolve(status()); await tick();
  old.resolve(status({ source: 'app', hasStoredKey: true })); await tick();
  assert.doesNotMatch(renderToStaticMarkup(h.render()), /앱에 API 키가 저장/); assert.equal(h.changed, 0);
});

test('Claude preload only exposes status/save/delete and sends secrets through dedicated main IPC', async () => {
  let api; const calls = [];
  runInNewContext(fs.readFileSync(join(output, 'main/preload.js'), 'utf8'), { exports: {}, require: name => {
    if (name === 'electron') return { contextBridge: { exposeInMainWorld(_name, value) { api = value; } },
      ipcRenderer: { invoke: async (...args) => { calls.push(args); return status(); } } };
    return createRequire(join(output, 'main/preload.js'))(name);
  } });
  await api.claudeCredentialStatus(); await api.saveClaudeCredential('fixture-secret'); await api.deleteClaudeCredential();
  assert.equal(calls[0][0], 'orchestrator:claude-credential-status');
  assert.equal(calls[1][0], 'orchestrator:claude-credential-save'); assert.equal(calls[1][1], 'fixture-secret');
  assert.equal(calls[2][0], 'orchestrator:claude-credential-delete'); assert.equal(api.getClaudeApiKey, undefined);
});
