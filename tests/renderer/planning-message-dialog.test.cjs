const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, mkdirSync, readFileSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const { createRequire } = require('node:module');
const { runInNewContext } = require('node:vm');
const { renderToStaticMarkup } = require('react-dom/server');
const root = resolve(__dirname, '../..'), temp = join(root, '.tmp');
mkdirSync(temp, { recursive: true });
const output = mkdtempSync(join(temp, 'message-dialog-'));
process.on('exit', () => { assert.equal(dirname(output), temp); rmSync(output, { recursive: true, force: true }); });
const packagePath = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
  'desktop/renderer/src/PlanningMessageDialog.tsx'], { cwd: root, stdio: 'inherit' });
const modulePath = join(output, 'PlanningMessageDialog.js');
function nodes(tree) { return !tree || typeof tree !== 'object' ? [] : Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)]; }
const message = { scope: 'project/group', key: 'message', text: '한글\r\n```ts\nconst value = "<원문>";\n```\n오류 로그\n', meta: '나 · 시각' };
function harness(compact, writeText = async () => {}) {
  const slots = [], effects = [], scheduled = [], copies = [];
  let cursor = 0, active, closed = 0;
  class Element { isConnected = true; getClientRects() { return [1]; } focus() { active = this; } }
  const origin = new Element(); active = origin;
  const attributes = new Set();
  const sidebar = { isConnected: true, open: true, modal: compact,
    setAttribute: name => attributes.add(name), removeAttribute: name => attributes.delete(name),
    matches: () => sidebar.modal, close() { this.open = false; this.modal = false; },
    show() { this.open = true; this.modal = false; }, showModal() { this.open = true; this.modal = true; } };
  const dialog = { open: false, showModal() { assert.equal(sidebar.modal, false); this.open = true; }, close() { this.open = false; } };
  const hooks = { useRef(initial) { const index = cursor++; return slots[index] ||= { current: initial }; },
    useState(initial) { const index = cursor++; if (!(index in slots)) slots[index] = initial; return [slots[index], value => { slots[index] = value; }]; },
    useLayoutEffect(callback, deps) { const index = cursor++, previous = effects[index];
      if (!previous || deps.some((value, i) => !Object.is(value, previous.deps[i]))) {
        effects[index] = { deps, cleanup: previous?.cleanup }; scheduled.push(() => { effects[index].cleanup?.(); effects[index].cleanup = callback(); });
      } },
  };
  const exports = {}, localRequire = createRequire(modulePath);
  runInNewContext(readFileSync(modulePath, 'utf8'), { exports, HTMLElement: Element,
    document: { get activeElement() { return active; }, getElementById: () => sidebar, body: {} },
    window: { matchMedia: () => ({ matches: compact }) }, navigator: { clipboard: { writeText: text => { copies.push(text); return writeText(text); } } },
    require: id => id === 'react' ? hooks : id === 'react-dom' ? { createPortal: node => node } : localRequire(id) });
  return { copies, sidebar, dialog, attributes, origin, active: () => active, closed: () => closed,
    render() { cursor = 0; const tree = exports.PlanningMessageDialog({ message, onClose: () => closed++ }); tree.props.ref.current = dialog;
      for (const effect of scheduled.splice(0)) effect(); return tree; },
    unmount() { for (const effect of effects) effect?.cleanup?.(); } };
}
const tick = async () => { await Promise.resolve(); await Promise.resolve(); };
test('full content renders Markdown and swaps compact chat for one modal, then restores focus', () => {
  for (const compact of [false, true]) {
    const fixture = harness(compact), tree = fixture.render();
    const markup = renderToStaticMarkup(nodes(tree).find(node => node.props?.className === 'planning-message-dialog__body'));
    assert.match(markup, /<p>한글<\/p>/);
    assert.match(markup, /<code class="language-ts">const value = &quot;&lt;원문&gt;&quot;;\n<\/code>/);
    assert.match(markup, /<p>오류 로그<\/p>/);
    assert.doesNotMatch(markup, /```/);
    assert.equal(fixture.dialog.open, true); assert.equal(fixture.sidebar.modal, false);
    assert.equal(fixture.attributes.has('data-message-detail-open'), true); assert.deepEqual(fixture.copies, []);
    let prevented = false; tree.props.onCancel({ preventDefault: () => prevented = true });
    assert.equal(prevented, true); assert.equal(fixture.closed(), 1); fixture.unmount();
    assert.equal(fixture.dialog.open, false); assert.equal(fixture.sidebar.open, true);
    assert.equal(fixture.sidebar.modal, compact); assert.equal(fixture.active(), fixture.origin);
    assert.equal(fixture.attributes.size, 0);
  }
});
test('popup copy preserves raw text and failures are visible; late replies after closing are ignored', async () => {
  for (const failure of [false, true]) {
    const fixture = harness(true, async () => { if (failure) throw new Error('clipboard denied'); });
    let tree = fixture.render(); nodes(tree).find(node => node.type === 'button' && node.props.children === '전체 내용 복사').props.onClick(); await tick();
    assert.deepEqual(fixture.copies, [message.text]); tree = fixture.render();
    assert.ok(nodes(tree).some(node => node.props.role === (failure ? 'alert' : 'status'))); fixture.unmount();
  }
  let resolve; const fixture = harness(true, () => new Promise(done => resolve = done));
  const tree = fixture.render(); nodes(tree).find(node => node.type === 'button' && node.props.children === '전체 내용 복사').props.onClick();
  fixture.unmount(); resolve(); await tick(); assert.equal(fixture.dialog.open, false);
});
