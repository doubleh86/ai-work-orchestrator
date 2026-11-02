const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');

const root = resolve(__dirname, '../..');
const tempRoot = join(root, '.tmp');
mkdirSync(tempRoot, { recursive: true });
const output = mkdtempSync(join(tempRoot, 'project-tools-menu-'));
const cleanup = () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); };
try {
  const ts = require.resolve('typescript/package.json', { paths: [root] });
  execFileSync(process.execPath, [resolve(dirname(ts), require(ts).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/ProjectToolsMenu.tsx'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);
const modulePath = join(output, 'ProjectToolsMenu.js');

function elements(tree, predicate, found = []) {
  if (!tree || typeof tree !== 'object') return found;
  if (Array.isArray(tree)) { for (const child of tree) elements(child, predicate, found); return found; }
  if (predicate(tree)) found.push(tree);
  elements(tree.props?.children, predicate, found);
  return found;
}
const button = (tree, label) => elements(tree, (item) => item.type === 'button'
  && [item.props.children].flat().filter((child) => typeof child === 'string').join('').trim() === label)[0];
const removeButton = (tree) => elements(tree, (item) => item.type === 'button'
  && text(item).includes('프로젝트 삭제'))[0];
function text(tree) {
  if (typeof tree === 'string') return tree;
  if (Array.isArray(tree)) return tree.map(text).join('');
  return tree ? text(tree.props?.children) : '';
}

// This DOM event/ref double checks dismissal and focus contracts, not Electron rendering.
function harness() {
  const slots = [];
  const effects = [];
  const pendingEffects = [];
  const listeners = new Map();
  const focused = [];
  let cursor = 0;
  class TestNode {
    constructor(name, parent = null) { this.name = name; this.parent = parent; }
    contains(target) { for (let node = target; node; node = node.parent) if (node === this) return true; return false; }
    focus(options) { focused.push({ name: this.name, ...options }); }
  }
  const menu = new TestNode('menu'); menu.open = false;
  const trigger = new TestNode('trigger', menu);
  const inside = new TestNode('button-child', menu);
  const outside = new TestNode('outside');
  const hooks = {
    useId() { const index = cursor++; return slots[index] ||= `project-tools-${index}`; },
    useRef(initial) { const index = cursor++; return slots[index] ||= { current: initial }; },
    useEffect(effect, deps) {
      const index = cursor++;
      const previous = effects[index];
      if (!previous || deps.some((value, i) => !Object.is(value, previous.deps[i]))) {
        effects[index] = { deps, cleanup: previous?.cleanup };
        pendingEffects.push(() => { effects[index].cleanup?.(); effects[index].cleanup = effect(); });
      }
    },
  };
  const exports = {};
  const localRequire = createRequire(modulePath);
  runInNewContext(readFileSync(modulePath, 'utf8'), {
    exports, Node: TestNode,
    document: {
      addEventListener(name, listener, capture = false) {
        const key = `${name}:${capture}`;
        if (!listeners.has(key)) listeners.set(key, new Set());
        listeners.get(key).add(listener);
      },
      removeEventListener(name, listener, capture = false) { listeners.get(`${name}:${capture}`)?.delete(listener); },
    },
    require: (id) => id === 'react' ? hooks : localRequire(id),
  });
  const dispatch = (key, event) => { for (const listener of listeners.get(key) || []) listener(event); };
  return {
    menu, trigger, inside, outside, focused, listeners,
    render(props = {}) {
      cursor = 0;
      const tree = exports.ProjectToolsMenu({ projectName: 'Example', settingsDisabled: false, removeDisabled: false,
        onAddProject() {}, onOpenAuth() {}, onOpenSettings() {}, onRemoveProject() {}, ...props });
      tree.props.ref.current = menu;
      elements(tree, (item) => item.type === 'summary')[0].props.ref.current = trigger;
      for (const effect of pendingEffects.splice(0)) effect();
      return tree;
    },
    pointer(target) {
      dispatch('pointerdown:true', { target, preventDefault: () => assert.fail('outside clicks keep their default action') });
    },
    key(changes = {}) {
      const event = { key: 'Escape', defaultPrevented: false, isComposing: false, prevented: 0, stopped: 0,
        preventDefault() { this.prevented++; }, stopPropagation() { this.stopped++; }, ...changes };
      dispatch('keydown:false', event); return event;
    },
    blur(tree, relatedTarget) { tree.props.onBlur({ currentTarget: menu, relatedTarget }); },
    unmount() { for (const effect of effects) effect?.cleanup?.(); },
  };
}

test('native disclosure starts closed and keeps summary keyboard and toggle behavior', () => {
  const fixture = harness(); const tree = fixture.render();
  assert.equal(tree.type, 'details'); assert.equal(tree.props.open, undefined);
  const summary = elements(tree, (item) => item.type === 'summary')[0];
  assert.equal(summary.props.children, '프로젝트 관리');
  assert.equal(summary.props.onClick, undefined); assert.equal(summary.props.onKeyDown, undefined);
  assert.equal(summary.props['aria-controls'], elements(tree, (item) => item.type === 'div')[0].props.id);
  assert.equal(elements(tree, (item) => item.type === 'button').length, 4);
  fixture.unmount();
});

test('inside pointers keep the menu open; outside pointers close without taking focus or running actions', () => {
  const fixture = harness(); const calls = [];
  fixture.render({ onAddProject: () => calls.push('project'), onOpenAuth: () => calls.push('auth') });
  fixture.menu.open = true;
  for (const node of [fixture.menu, fixture.trigger, fixture.inside]) {
    fixture.pointer(node); assert.equal(fixture.menu.open, true);
  }
  fixture.pointer(fixture.outside); assert.equal(fixture.menu.open, false);
  assert.deepEqual(fixture.focused, []); assert.deepEqual(calls, []);
  fixture.unmount();
});

test('compact task menu keeps group navigation inside the existing dismissible menu', () => {
  const calls=[];
  const fixture=harness();
  const tree=fixture.render({compact:true,projectOnly:true,onOpenGroups:()=>calls.push('groups')});
  assert.equal(elements(tree,item=>item.type==='summary')[0].props['aria-label'],'작업 메뉴');
  const group=elements(tree,item=>item.type==='button').find(item=>text(item)==='작업 그룹 전환');
  fixture.menu.open=true;group.props.onClick();
  assert.deepEqual(calls,['groups']);assert.equal(fixture.menu.open,false);
  fixture.unmount();
});

test('Escape dismisses only an open menu, returns trigger focus and consumes the handled key', () => {
  const fixture = harness(); fixture.render();
  const closed = fixture.key(); assert.equal(closed.prevented, 0); assert.equal(closed.stopped, 0);
  assert.deepEqual(fixture.focused, []);
  fixture.menu.open = true;
  const event = fixture.key(); assert.equal(fixture.menu.open, false);
  assert.equal(event.prevented, 1); assert.equal(event.stopped, 1);
  assert.deepEqual(fixture.focused, [{ name: 'trigger', preventScroll: true }]);
  fixture.unmount();
});

test('handled Escape, IME and other keys keep their existing behavior', () => {
  const fixture = harness(); fixture.render();
  for (const input of [{ defaultPrevented: true }, { isComposing: true }, { key: 'Enter' }, { key: 'Tab' }]) {
    fixture.menu.open = true;
    const event = fixture.key(input);
    assert.equal(fixture.menu.open, true); assert.equal(event.prevented, 0); assert.equal(event.stopped, 0);
  }
  assert.deepEqual(fixture.focused, []); fixture.unmount();
});

test('focus can move between menu controls, and leaving the menu closes without stealing the new focus', () => {
  const fixture = harness(); const tree = fixture.render(); fixture.menu.open = true;
  for (const node of [fixture.trigger, fixture.inside]) {
    fixture.blur(tree, node); assert.equal(fixture.menu.open, true);
  }
  fixture.blur(tree, fixture.outside); assert.equal(fixture.menu.open, false);
  fixture.menu.open = true; fixture.blur(tree, null); assert.equal(fixture.menu.open, false);
  assert.deepEqual(fixture.focused, []); fixture.unmount();
});

test('each action closes before invoking exactly its existing callback', () => {
  const fixture = harness(); const calls = [];
  const action = (name) => () => { assert.equal(fixture.menu.open, false); calls.push(name); };
  const tree = fixture.render({ onAddProject: action('project'), onOpenAuth: action('auth'), onOpenSettings: action('settings') });
  for (const label of ['프로젝트', 'AI 연결', '설정']) {
    fixture.menu.open = true; button(tree, label).props.onClick();
    assert.equal(fixture.menu.open, false);
  }
  assert.deepEqual(calls, ['project', 'auth', 'settings']); assert.deepEqual(fixture.focused, []);
  fixture.unmount();
});

test('disabled settings remain guarded while rerenders keep the open menu and use the newest callbacks', () => {
  const fixture = harness(); const calls = [];
  fixture.render({ onOpenAuth: () => calls.push('old auth') }); fixture.menu.open = true;
  const tree = fixture.render({ settingsDisabled: true, onOpenAuth: () => calls.push('new auth'), onOpenSettings: () => calls.push('settings') });
  assert.equal(fixture.menu.open, true);
  assert.equal(button(tree, '설정').props.disabled, true);
  button(tree, '설정').props.onClick(); assert.equal(fixture.menu.open, true); assert.deepEqual(calls, []);
  button(tree, 'AI 연결').props.onClick(); assert.deepEqual(calls, ['new auth']);
  assert.equal(fixture.listeners.get('pointerdown:true').size, 1); assert.equal(fixture.listeners.get('keydown:false').size, 1);
  fixture.unmount();
  for (const listeners of fixture.listeners.values()) assert.equal(listeners.size, 0);
});

test('project removal identifies its target and closes the menu before opening the existing confirmation', () => {
  const fixture = harness(); const calls = [];
  const tree = fixture.render({ projectName: 'Selected project', onRemoveProject: () => {
    assert.equal(fixture.menu.open, false); calls.push('remove');
  } });
  const remove = removeButton(tree);
  assert.match(text(remove), /프로젝트 삭제/);
  assert.match(text(remove), /Selected project · 등록만 해제/);
  assert.equal(remove.props.disabled, false);
  assert.deepEqual(calls, []);
  fixture.menu.open = true;
  remove.props.onClick();
  assert.deepEqual(calls, ['remove']);
  fixture.unmount();
});

test('project removal is guarded without a selection or while busy and uses the latest target callback', () => {
  const fixture = harness(); const calls = [];
  for (const props of [{ projectName: '' }, { removeDisabled: true }]) {
    const tree = fixture.render({ ...props, onRemoveProject: () => calls.push('blocked') });
    fixture.menu.open = true;
    assert.equal(removeButton(tree).props.disabled, true);
    removeButton(tree).props.onClick();
    assert.equal(fixture.menu.open, true); assert.deepEqual(calls, []);
  }
  const tree = fixture.render({ projectName: 'New selection', onRemoveProject: () => calls.push('new selection') });
  assert.match(text(removeButton(tree)), /New selection/);
  removeButton(tree).props.onClick();
  assert.deepEqual(calls, ['new selection']);
  fixture.unmount();
});


test('project-specific management retains original-change and unregister routes without global actions', () => {
  const fixture = harness(); const calls = [];
  const tree = fixture.render({projectOnly: true, projectName: 'idle', removeDisabled: true,
    removeReason: '이 프로젝트 요청 처리 중', onMainChanges: () => calls.push('main')});
  assert.ok(button(tree, '프로젝트 환경')); assert.ok(button(tree, '원본 변경·동기화'));
  assert.equal(button(tree, 'AI 연결'), undefined); assert.equal(button(tree, '프로젝트'), undefined);
  assert.equal(removeButton(tree).props.title, '이 프로젝트 요청 처리 중'); assert.match(text(tree), /이 프로젝트 요청 처리 중/);
  fixture.menu.open = true; button(tree, '원본 변경·동기화').props.onClick();
  assert.deepEqual(calls, ['main']); assert.equal(fixture.menu.open, false); fixture.unmount();
});
