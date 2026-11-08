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
const output = mkdtempSync(join(temp, 'work-dialog-'));
process.on('exit', () => { assert.equal(dirname(output), temp); rmSync(output, { recursive: true, force: true }); });
const pkg = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(pkg), require(pkg).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--rootDir', 'desktop', '--outDir', output,
  'desktop/renderer/src/WorkDialog.tsx', 'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });

function elements(tree, predicate) {
  if (!tree || typeof tree !== 'object') return [];
  return Array.isArray(tree) ? tree.flatMap(child => elements(child, predicate))
    : [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)];
}

test('native Task dialog Escape closes only the surface and restores focus; children and requests are retained', () => {
  const file = join(output, 'renderer/src/WorkDialog.js');
  const localRequire = createRequire(file);
  let closed = 0; let shown = 0; let focused = 0; let prevented = 0;
  class Element { constructor() { this.isConnected = true; } focus() { focused++; } }
  const origin = new Element();
  const dialog = { showModal: () => shown++, close: () => closed++ };
  const effects = []; let index = 0;
  const refs = [{ current: dialog }, { current: null }];
  const exported = {};
  runInNewContext(readFileSync(file, 'utf8'), { exports: exported, HTMLElement: Element, document: { activeElement: origin },
    require(name) { if (name !== 'react') return localRequire(name);
      return { useRef: () => refs[index++], useEffect: (effect) => effects.push(effect) }; } });
  const draft = { text: 'keep this draft', busy: true };
  let viewClosed = 0;
  const tree = exported.WorkDialog({ title: 'Task 3', children: draft, onClose: () => viewClosed++ });
  const cleanup = effects[0]();
  assert.equal(shown, 1);
  tree.props.onCancel({ preventDefault: () => prevented++ });
  assert.equal(viewClosed, 1); assert.equal(prevented, 1);
  elements(tree, (item) => item.type === 'button' && item.props.children === '닫기')[0].props.onClick();
  assert.equal(viewClosed, 2);
  assert.equal(draft.text, 'keep this draft'); assert.equal(draft.busy, true);
  cleanup(); assert.equal(closed, 1); assert.equal(focused, 1);
});

test('a closed dialog does not open a modal or capture focus', () => {
  const file = join(output, 'renderer/src/WorkDialog.js'), local = createRequire(file), exported = {}, effects = [];
  let opened = 0;
  runInNewContext(readFileSync(file, 'utf8'), { exports: exported, require: name => name === 'react' ? {
    useRef: () => ({ current: { showModal() { opened++; } } }), useEffect: callback => effects.push(callback),
  } : local(name) });
  exported.WorkDialog({ title: '보관 기록', open: false, onClose() {}, children: '보존할 내용' });
  assert.equal(effects[0](), undefined); assert.equal(opened, 0);
});
