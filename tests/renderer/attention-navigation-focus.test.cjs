const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(root, '.tmp');
mkdirSync(tempRoot, { recursive: true });
const output = resolve(mkdtempSync(join(tempRoot, 'attention-focus-')));
const cleanup = () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); };
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  execFileSync(process.execPath, [resolve(dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig',
    '--strict', '--target', 'ES2022', '--module', 'commonjs', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/useAttentionNavigationFocus.ts'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);
const modulePath = join(output, 'useAttentionNavigationFocus.js');
const { attentionFocusMatches, attentionFocusTarget } = require(modulePath);
const request = (extra = {}) => ({ projectName: 'first', runId: 'same', view: 'tasks', taskId: '', kind: 'verification',
  waitingSourceKey: 'verification:receipt', ...extra });
const context = (extra = {}) => ({ projectName: 'first', runId: 'same', view: 'tasks', taskId: '',
  waitingSourceKey: 'verification:receipt', inspectorTitleId: 'side-inspector-title', ...extra });

function surface() {
  const nodes = new Map();
  const calls = [];
  let modal = false;
  const document = { getElementById: (id) => nodes.get(id) || null, querySelector: () => modal ? {} : null };
  const element = { dataset: { attentionProject: 'first', attentionRun: 'same' }, ownerDocument: document,
    querySelector: (selector) => nodes.get(selector) || null, contains: (node) => [...nodes.values()].includes(node) };
  const add = (selector, extra = {}) => {
    const node = { dataset: {}, getClientRects: () => [1],
      focus: (options) => calls.push({ selector, action: 'focus', options }),
      scrollIntoView: (options) => calls.push({ selector, action: 'scroll', options }), ...extra };
    nodes.set(selector, node);
    return node;
  };
  add('[data-attention-waiting]', { dataset: { attentionWaiting: 'verification:receipt' } });
  add('[data-attention-action]');
  add('tasks-workbench-title');
  add('operations-workbench-title');
  add('planning-workbench-title');
  add('side-inspector-title');
  add('task-inspector-title');
  return { element, nodes, calls, add, setModal: (value) => { modal = value; } };
}

// DOM metrics and React scheduling are controlled fixtures, not a real app screen test.
function harness(ui = surface()) {
  const slots = [];
  const effects = [];
  const pendingEffects = [];
  const frames = new Map();
  const cancelledFrames = [];
  let cursor = 0;
  let sequence = 0;
  const hooks = {
    useRef(initial) { const index = cursor++; return slots[index] ||= { current: initial }; },
    useEffect(effect, deps) {
      const index = cursor++;
      const old = effects[index];
      if (!old || deps.some((value, i) => !Object.is(value, old.deps[i]))) {
        effects[index] = { deps, cleanup: old?.cleanup, setup: effect };
        pendingEffects.push(() => { effects[index].cleanup?.(); effects[index].cleanup = effect(); });
      }
    },
  };
  const exports = {};
  const localRequire = createRequire(modulePath);
  runInNewContext(readFileSync(modulePath, 'utf8'), { exports,
    require: (name) => name === 'react' ? hooks : localRequire(name),
    window: {
      requestAnimationFrame: (callback) => { const id = ++sequence; frames.set(id, callback); return id; },
      cancelAnimationFrame: (id) => { if (frames.has(id)) cancelledFrames.push(frames.get(id)); frames.delete(id); },
    },
  });
  const rootRef = { current: ui.element };
  return {
    ui,
    render: (pending, current) => {
      cursor = 0;
      exports.useAttentionNavigationFocus(pending, current, rootRef);
      for (const effect of pendingEffects.splice(0)) effect();
    },
    frame: () => { const batch = [...frames.values()]; frames.clear(); for (const callback of batch) callback(); },
    staleFrames: () => { for (const callback of cancelledFrames.splice(0)) callback(); },
    replayEffects: () => { for (const effect of effects) if (effect) { effect.cleanup?.(); effect.cleanup = effect.setup(); } },
    unmount: () => { for (const effect of effects) effect?.cleanup?.(); },
  };
}

test('navigation rejects a different project with the same Run ID and a changed Task or tab', () => {
  const ui = surface();
  for (const changed of [context({ projectName: 'second' }), context({ runId: 'other' }), context({ view: 'operations' }),
    context({ taskId: 'other' })]) {
    assert.equal(attentionFocusMatches(request({ taskId: 'chosen' }), changed), false);
    assert.equal(attentionFocusTarget(ui.element, request({ taskId: 'chosen' }), changed), undefined);
  }
  ui.element.dataset.attentionProject = 'second';
  assert.equal(attentionFocusTarget(ui.element, request(), context()), undefined);
});

test('current waiting question takes priority and changed or postponed sources fall back to the current heading', () => {
  const ui = surface();
  assert.equal(attentionFocusTarget(ui.element, request(), context()), ui.nodes.get('[data-attention-waiting]'));
  for (const source of ['later-question', '']) {
    assert.equal(attentionFocusTarget(ui.element, request(), context({ waitingSourceKey: source })), ui.nodes.get('tasks-workbench-title'));
  }
  ui.nodes.get('[data-attention-waiting]').dataset.attentionWaiting = 'old-question';
  ui.nodes.delete('[data-attention-action]');
  assert.equal(attentionFocusTarget(ui.element, request(), context()), ui.nodes.get('tasks-workbench-title'));
});

test('planning questions, visible task detail and current actions each have a reachable fallback', () => {
  const ui = surface();
  const question = ui.add('[data-attention-question]');
  const planning = request({ view: 'planning', kind: 'planning_questions', waitingSourceKey: '' });
  assert.equal(attentionFocusTarget(ui.element, planning, context({ view: 'planning' })), question);
  question.getClientRects = () => [];
  assert.equal(attentionFocusTarget(ui.element, planning, context({ view: 'planning' })), ui.nodes.get('planning-workbench-title'));
  const task = request({ taskId: 'chosen', waitingSourceKey: '' });
  assert.equal(attentionFocusTarget(ui.element, task, context({ taskId: 'chosen' })), ui.nodes.get('side-inspector-title'));
  assert.equal(attentionFocusTarget(ui.element, task, context({ taskId: 'chosen', inspectorTitleId: 'task-inspector-title' })), ui.nodes.get('task-inspector-title'));
  const operation = request({ view: 'operations', waitingSourceKey: '' });
  assert.equal(attentionFocusTarget(ui.element, operation, context({ view: 'operations' })), ui.nodes.get('[data-attention-action]'));
  ui.nodes.get('[data-attention-action]').getClientRects = () => [];
  assert.equal(attentionFocusTarget(ui.element, operation, context({ view: 'operations' })), ui.nodes.get('operations-workbench-title'));
});

test('fresh explicit navigation focuses and scrolls once; polling and resize cannot repeat it', () => {
  const h = harness();
  const pending = request();
  h.render(undefined, context());
  h.frame();
  assert.equal(h.ui.calls.length, 0);
  h.render(pending, context());
  assert.equal(h.ui.calls.length, 0);
  h.frame();
  assert.deepEqual(h.ui.calls.map((call) => call.action), ['focus', 'scroll']);
  assert.equal(h.ui.calls[0].options.preventScroll, true);
  assert.equal(h.ui.calls[1].options.behavior, 'instant');
  assert.equal(h.ui.calls[1].options.block, 'nearest');
  for (let i = 0; i < 4; i++) { h.render(pending, context()); h.frame(); }
  h.render(pending, context({ inspectorTitleId: 'task-inspector-title' }));
  h.frame();
  assert.equal(h.ui.calls.length, 2);
  h.render(request(), context()); // A second explicit click is a new navigation.
  h.frame();
  assert.equal(h.ui.calls.length, 4);
});

test('a navigation abandoned before the frame cannot steal focus after returning to the same group', () => {
  const h = harness();
  const pending = request();
  h.render(pending, context());
  h.render(pending, context({ projectName: 'second' }));
  h.staleFrames();
  h.frame();
  h.render(pending, context());
  h.frame();
  assert.equal(h.ui.calls.length, 0);
});

test('read failure or a newer explicit navigation cancels the previous scheduled focus', () => {
  const h = harness();
  h.render(request(), context());
  h.render(undefined, context({ runId: '' }));
  h.staleFrames();
  h.frame();
  assert.equal(h.ui.calls.length, 0);
  h.render(request({ waitingSourceKey: '', view: 'operations' }), context({ view: 'operations' }));
  h.frame();
  assert.equal(h.ui.calls[0].selector, '[data-attention-action]');
});

test('an open modal consumes the navigation and cannot trigger delayed focus when it closes', () => {
  const h = harness();
  const pending = request();
  h.ui.setModal(true);
  h.render(pending, context());
  h.frame();
  h.ui.setModal(false);
  h.render(pending, context());
  h.frame();
  assert.equal(h.ui.calls.length, 0);
});

test('changed waiting source before the frame uses current heading once and hidden targets are skipped', () => {
  const h = harness();
  const pending = request();
  h.render(pending, context());
  h.render(pending, context({ waitingSourceKey: 'new-question' }));
  h.staleFrames();
  h.frame();
  assert.equal(h.ui.calls.length, 2);
  assert.equal(h.ui.calls[0].selector, 'tasks-workbench-title');
  const hidden = harness();
  for (const node of hidden.ui.nodes.values()) node.getClientRects = () => [];
  hidden.render(request(), context());
  hidden.frame();
  assert.equal(hidden.ui.calls.length, 0);
});

test('unmount cancels a frame, and effect replay leaves the explicit request usable once', () => {
  const h = harness();
  const pending = request();
  h.render(pending, context());
  h.unmount();
  h.frame();
  assert.equal(h.ui.calls.length, 0);
  h.replayEffects();
  h.frame();
  assert.equal(h.ui.calls.length, 2);
});
