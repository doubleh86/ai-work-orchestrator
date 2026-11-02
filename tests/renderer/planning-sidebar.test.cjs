const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, mkdirSync, readFileSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const { createRequire } = require('node:module');
const { runInNewContext } = require('node:vm');

const root = resolve(__dirname, '../..');
const temp = join(root, '.tmp');
mkdirSync(temp, { recursive: true });
const output = mkdtempSync(join(temp, 'planning-sidebar-'));
process.on('exit', () => { assert.equal(dirname(output), temp); rmSync(output, { recursive: true, force: true }); });
const packagePath = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
  'desktop/renderer/src/PlanningSidebar.tsx'], { cwd: root, stdio: 'inherit' });
const modulePath = join(output, 'PlanningSidebar.js');
function find(tree, predicate) {
  if (!tree || typeof tree !== 'object') return undefined;
  if (Array.isArray(tree)) return tree.map((node) => find(node, predicate)).find(Boolean);
  return predicate(tree) ? tree : find(tree.props?.children, predicate);
}
function harness(compact = false) {
  const slots = [], effects = [], scheduled = [];
  let cursor = 0, mediaListener, activeElement;
  class Element {
    isConnected = true;
    focus() { activeElement = this; }
    closest() { return null; }
  }
  const composer = new Element(), launcher = new Element(), origin = new Element();
  const dialog = { open: false, mode: '', closeCount: 0, attributes: new Set(), hasAttribute(name) { return this.attributes.has(name); },
    contains(node) { return node === composer; },
    matches(selector) { assert.equal(selector, ':modal'); return this.mode === 'modal' && this.open; },
    show() { this.open = true; this.mode = 'nonmodal'; },
    showModal() { this.open = true; this.mode = 'modal'; },
    close() { this.open = false; this.closeCount++; },
    querySelector() { return composer; } };
  const media = { matches: compact, addEventListener(_, callback) { mediaListener = callback; },
    removeEventListener(_, callback) { assert.equal(callback, mediaListener); mediaListener = undefined; } };
  const hooks = {
    useState(initial) { const index = cursor++; if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial;
      return [slots[index], (value) => { slots[index] = typeof value === 'function' ? value(slots[index]) : value; }]; },
    useRef(initial) { const index = cursor++; return slots[index] ||= { current: initial }; },
    useEffect(callback, deps) { const index = cursor++; const previous = effects[index];
      if (!previous || deps.some((value, i) => !Object.is(value, previous.deps[i]))) {
        effects[index] = { deps, cleanup: previous?.cleanup };
        scheduled.push(() => { effects[index].cleanup?.(); effects[index].cleanup = callback(); });
      } },
  };
  const exports = {}, localRequire = createRequire(modulePath);
  runInNewContext(readFileSync(modulePath, 'utf8'), { exports, require: (name) => name === 'react' ? hooks : localRequire(name),
    window: { matchMedia: () => media }, document: { querySelector(){ return launcher; }, get activeElement() { return activeElement; } }, HTMLElement: Element });
  const target = {};
  const onTarget = (node) => { assert.equal(node, target); };
  let props = { context: '프로젝트 A', onTarget, openRequest: 0 }, tree;
  function render(update = {}) {
    props = { ...props, ...update }; cursor = 0; tree = exports.PlanningSidebar(props);
    find(tree, (node) => node.type === 'dialog').props.ref.current = dialog;
    const launcherNode = find(tree, (node) => node.props.className?.includes('planning-chat-launcher'));
    if (launcherNode) launcherNode.props.ref.current = launcher;
    find(tree, (node) => node.props.className === 'planning-sidebar__content').props.ref(target);
    while (scheduled.length) scheduled.shift()();
    return tree;
  }
  return { render, dialog, composer, launcher, origin, target,
    focusOrigin() { origin.focus(); }, active: () => activeElement,
    resize(value) { media.matches = value; mediaListener(); return render(); },
    unmount() { effects.forEach((effect) => effect?.cleanup?.()); assert.equal(mediaListener, undefined); } };
}

test('primary chat stays nonmodal across resize, context changes and Escape without reopening', () => {
  const h = harness(true); let tree = h.render({ primary: true });
  assert.equal(h.dialog.mode, 'nonmodal'); assert.equal(h.dialog.open, true);
  assert.equal(find(tree, node => node.props.className?.includes('planning-chat-launcher')), undefined);
  const closes = h.dialog.closeCount;
  tree = h.render({ context: 'other conversation', openRequest: 1 });
  assert.equal(h.active(), h.composer);
  find(tree, node => node.type === 'dialog').props.onCancel({ preventDefault() {} });
  h.resize(false); h.resize(true);
  assert.equal(h.dialog.closeCount, closes); assert.equal(h.dialog.open, true);
  tree = h.render({ inactive: true });
  assert.equal(find(tree, node => node.type === 'dialog').props.inert, true);
  h.unmount();
});

test('wide sidebar keeps its portal target across context changes and focuses the shared composer on request', () => {
  const h = harness(); h.render();
  assert.equal(h.dialog.mode, 'nonmodal'); assert.equal(h.dialog.open, true);
  const closeCount = h.dialog.closeCount;
  h.render({ context: '프로젝트 B' });
  assert.equal(h.dialog.closeCount, closeCount, 'context changes must not close or remount the chat target');
  h.render({ openRequest: 1 });
  assert.equal(h.active(), h.composer);
  h.unmount(); assert.equal(h.dialog.open, false);
});

test('compact chat uses a native modal and Escape returns focus without destroying the target', () => {
  const h = harness(true); let tree = h.render();
  assert.equal(h.dialog.open, false);
  h.focusOrigin(); h.render({ openRequest: 1 }); tree = h.render();
  assert.equal(h.dialog.open, true); assert.equal(h.dialog.mode, 'modal');
  let prevented = false;
  find(tree, (node) => node.type === 'dialog').props.onCancel({ preventDefault() { prevented = true; } });
  h.render(); assert.equal(prevented, true); assert.equal(h.dialog.open, false); assert.equal(h.active(), h.origin);
  tree = h.render(); find(tree, (node) => node.props.className?.includes('planning-chat-launcher')).props.onClick();
  tree = h.render(); assert.equal(h.dialog.open, true);
  find(tree, (node) => node.props['aria-label'] === 'Planning AI 닫기').props.onClick();
  h.render(); assert.equal(h.active(), h.launcher);
  h.unmount();
});

test('resizing between persistent sidebar and compact dialog closes modal mode and keeps one chat target', () => {
  const h = harness(); h.render();
  let tree = h.resize(true); assert.equal(h.dialog.open, false);
  find(tree, (node) => node.props.className?.includes('planning-chat-launcher')).props.onClick(); h.render();
  assert.equal(h.dialog.mode, 'modal');
  h.resize(false); h.render(); assert.equal(h.dialog.open, true); assert.equal(h.dialog.mode, 'nonmodal');
  h.resize(true); assert.equal(h.dialog.open, false, 'returning to compact must not reopen an old modal');
  h.unmount();
});

test('resizing while a planning preview is open cannot open a second chat modal', () => {
  const h = harness(true); h.render();
  h.focusOrigin(); h.render({ openRequest: 1 }); h.render();
  assert.equal(h.dialog.mode, 'modal');
  h.dialog.attributes.add('data-planning-preview-open'); h.dialog.close();
  h.resize(false); assert.equal(h.dialog.open, false);
  h.resize(true); assert.equal(h.dialog.open, false);
  h.dialog.attributes.delete('data-planning-preview-open');
  h.unmount();
});


test('primary details overlay moves focus out of inert chat and restores it on return', () => {
  const h = harness(true); h.render({primary:true, openRequest:1});
  assert.equal(h.active(), h.composer);
  let tree = h.render({inactive:true});
  assert.equal(find(tree, node => node.type === 'dialog').props.inert,true);
  assert.equal(h.active(),h.launcher);
  tree = h.resize(false);
  assert.equal(find(tree, node => node.type === 'dialog').props.inert,false);
  assert.equal(h.active(),h.composer);
  h.unmount();
});
