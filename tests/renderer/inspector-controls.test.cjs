const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');
const { renderToStaticMarkup } = require('react-dom/server');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(root, '.tmp');
mkdirSync(tempRoot, { recursive: true });
const output = resolve(mkdtempSync(join(tempRoot, 'inspector-controls-')));
const cleanup = () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); };
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  execFileSync(process.execPath, [resolve(dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig',
    '--strict', '--target', 'ES2022', '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/InspectorControls.tsx', 'desktop/renderer/src/ExecutionMonitor.tsx'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

function find(element, predicate) {
  if (!element || typeof element !== 'object') return undefined;
  if (predicate(element)) return element;
  const children = element.props?.children;
  for (const child of Array.isArray(children) ? children.flat() : [children]) {
    const found = find(child, predicate);
    if (found) return found;
  }
}

function harness(file, name) {
  const path = join(output, file);
  const localRequire = createRequire(path);
  const slots = [];
  let cursor = 0;
  let pending = [];
  const effect = (action, deps) => {
    const index = cursor++;
    if (!slots[index] || deps.some((value, position) => value !== slots[index][position])) {
      slots[index] = deps;
      pending.push(action);
    }
  };
  const hooks = {
    useEffect: effect, useLayoutEffect: effect, useMemo: (calculate) => calculate(),
    useRef(initial) { const index = cursor++; return slots[index] ||= { current: initial }; },
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial;
      return [slots[index], (value) => { slots[index] = typeof value === 'function' ? value(slots[index]) : value; }];
    },
  };
  const exports = {};
  runInNewContext(readFileSync(path, 'utf8'), {
    exports, window: { requestAnimationFrame: (action) => action() },
    require: (dependency) => dependency === 'react' ? hooks : localRequire(dependency),
  });
  return {
    render(props) { cursor = 0; pending = []; return exports[name](props); },
    commit() { pending.forEach((action) => action()); },
  };
}

test('collapse and reopen controls are named native buttons linked to their panel', () => {
  const { InspectorToggle } = require(join(output, 'InspectorControls.js'));
  let open = true;
  const button = (state) => find(InspectorToggle({ open: state, panelId: 'side-inspector', onToggle: () => { open = !open; } }),
    (element) => element.type === 'button');
  const close = button(open);
  assert.equal(close.props.type, 'button');
  assert.equal(close.props['aria-label'], '상세 패널 접기');
  assert.equal(close.props['aria-expanded'], true);
  assert.equal(close.props['aria-controls'], 'side-inspector');
  assert.equal(close.props.onKeyDown, undefined, 'Enter and Space keep native button semantics');
  close.props.onClick();
  const reopen = button(open);
  assert.equal(reopen.props.id, 'inspector-open');
  assert.equal(reopen.props['aria-expanded'], false);
  assert.match(renderToStaticMarkup(InspectorToggle({ open, panelId: 'side-inspector', onToggle: () => {} })), /상세 패널 열기/);
  reopen.props.onClick();
  assert.equal(open, true);
});

test('each Task and tab restores its reading position after collapse, remount, and polling', () => {
  const memory = { current: {} };
  const props = { id: 'panel', labelledBy: 'tab', contextKey: 'project/group/task/log', visible: true, compact: false, memory };
  const fixture = harness('InspectorControls.js', 'InspectorContent');
  let tree = fixture.render(props);
  const node = { scrollTop: 0, scrollLeft: 0 };
  tree.props.ref.current = node;
  fixture.commit();
  node.scrollTop = 320; node.scrollLeft = 14;
  tree.props.onScroll({ currentTarget: node });
  tree = fixture.render({ ...props, visible: false });
  fixture.commit();
  tree.props.onScroll({ currentTarget: { scrollTop: 0, scrollLeft: 0 } });
  assert.equal(memory.current[props.contextKey].top, 320, 'hidden layout cannot erase the position');
  tree = fixture.render({ ...props, contextKey: 'project/group/task/events', visible: true });
  fixture.commit();
  assert.equal(node.scrollTop, 0);
  tree.props.onScroll({ currentTarget: { scrollTop: 85, scrollLeft: 0 } });
  tree = fixture.render(props);
  fixture.commit();
  assert.equal(node.scrollTop, 320);
  assert.equal(node.scrollLeft, 14);
  node.scrollTop = 321;
  fixture.render(props); fixture.commit();
  assert.equal(node.scrollTop, 321, 'unrelated rerender does not reposition the reader');
  const reopened = harness('InspectorControls.js', 'InspectorContent');
  tree = reopened.render(props);
  tree.props.ref.current = node;
  node.scrollTop = 0;
  reopened.commit();
  assert.equal(node.scrollTop, 320);
});

const task = { id: 'task', title: 'log task', status: 'failed', action_results: [], review_status: 'not_required',
  provider_id: 'codex', worktree: '', progress_phase: '', progress_detail: '' };
const run = { id: 'group', summary: 'group', execution_control: { situation: 'resumable' }, workspace_mode: 'shared' };
const logState = { value: 'alpha\nbeta failure\ngamma', loading: false, error: '', refresh() {} };
const logProps = (view, onViewChange, visible = true) => ({ run, task, state: logState, progressText: '', view, onViewChange, visible });
const viewport = (tree) => find(tree, (element) => element.type === 'pre');

test('log search, wrapping, manual reading position, and follow choice survive a new Inspector', () => {
  let view = { query: '', wrap: true, follow: true, top: 0, left: 0 };
  const change = (updated) => { view = updated; };
  const fixture = harness('ExecutionMonitor.js', 'ExecutionLogViewer');
  let tree = fixture.render(logProps(view, change));
  find(tree, (element) => element.type === 'input' && element.props.type === 'search')
    .props.onChange({ target: { value: 'failure' } });
  assert.equal(view.follow, false);
  tree = fixture.render(logProps(view, change));
  find(tree, (element) => element.type === 'input' && element.props.type === 'checkbox' && element.props.checked === true)
    .props.onChange({ target: { checked: false } });
  tree = fixture.render(logProps(view, change));
  viewport(tree).props.onScroll({ currentTarget: { scrollTop: 160, scrollLeft: 25, scrollHeight: 1000, clientHeight: 100 } });
  const reopened = harness('ExecutionMonitor.js', 'ExecutionLogViewer');
  tree = reopened.render(logProps(view, change));
  const node = { scrollTop: 0, scrollLeft: 0, scrollHeight: 1000 };
  viewport(tree).props.ref.current = node;
  reopened.commit();
  assert.equal(find(tree, (element) => element.type === 'input' && element.props.type === 'search').props.value, 'failure');
  assert.equal(viewport(tree).props['data-wrap'], false);
  assert.equal(node.scrollTop, 160);
  assert.equal(node.scrollLeft, 25);
  assert.equal(view.follow, false);
});

test('hidden Inspector cannot reset saved log position while new output arrives', () => {
  const view = { query: '', wrap: true, follow: false, top: 160, left: 0 };
  let changes = 0;
  const fixture = harness('ExecutionMonitor.js', 'ExecutionLogViewer');
  const tree = fixture.render(logProps(view, () => { changes++; }, false));
  const node = { scrollTop: 0, scrollLeft: 0, scrollHeight: 1000 };
  viewport(tree).props.ref.current = node;
  fixture.commit();
  viewport(tree).props.onScroll({ currentTarget: node });
  assert.equal(changes, 0);
  assert.equal(node.scrollTop, 0);
  fixture.render(logProps(view, () => { changes++; }, true));
  fixture.commit();
  assert.equal(node.scrollTop, 160);
});
