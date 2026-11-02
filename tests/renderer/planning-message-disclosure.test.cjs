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
const output = resolve(mkdtempSync(join(tempRoot, 'planning-message-')));
const cleanup = () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); };
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  execFileSync(process.execPath, [resolve(dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig',
    '--strict', '--target', 'ES2022', '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/PlanningMessageDisclosure.tsx'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);
const modulePath = join(output, 'PlanningMessageDisclosure.js');
const { planningMessageKey, planningMessageOverflows } = require(modulePath);

function find(tree, predicate) {
  if (!tree || typeof tree !== 'object') return undefined;
  if (Array.isArray(tree)) {
    for (const child of tree) { const result = find(child, predicate); if (result) return result; }
    return undefined;
  }
  return predicate(tree) ? tree : find(tree.props?.children, predicate);
}
const body = (tree) => find(tree, (item) => item.props?.className === 'planning-message-disclosure__body');
const toggle = (tree) => find(tree, (item) => item.type === 'button' && item.props['aria-expanded'] !== undefined);
const copyButton = (tree) => find(tree, (item) => item.type === 'button' && item.props['aria-label'] === '전체 내용 복사');

// These layout metrics exercise the component contract; they are not Electron rendering verification.
function harness(writeText = async () => {}) {
  const slots = [];
  const effects = [];
  const scheduled = [];
  const listeners = new Map();
  const fontListeners = new Map();
  const observers = [];
  const copied = [];
  const focus = [];
  const viewMoves = [];
  let cursor = 0;
  let writes = 0;
  let id = 0;
  let paneScrollTop = 100;
  const pane = { clientTop: 0, clientHeight: 400, scrollHeight: 2000, parentElement: null,
    matches: () => true, getBoundingClientRect: () => ({ top: 0 }),
    get scrollTop() { return paneScrollTop; },
    set scrollTop(value) { paneScrollTop = value; viewMoves.push({ target: 'pane', action: 'scroll', value }); },
  };
  const metrics = { clientWidth: 400, scrollHeight: 160, lineHeight: '20px',
    parentElement: pane, getBoundingClientRect: () => ({ top: 150, bottom: 310, height: 160 }),
    focus(options) { viewMoves.push({ target: 'body', action: 'focus', ...options }); },
    scrollIntoView(options) { viewMoves.push({ target: 'body', action: 'scroll', ...options }); },
  };
  const document = { activeElement: null, fonts: {
    ready: Promise.resolve(),
    addEventListener(name, listener) { fontListeners.set(name, listener); },
    removeEventListener(name, listener) { if (fontListeners.get(name) === listener) fontListeners.delete(name); },
  } };
  const hooks = {
    useId() { const index = cursor++; return slots[index] ||= `message-body-${++id}`; },
    useRef(initial) { const index = cursor++; return slots[index] ||= { current: initial }; },
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial;
      return [slots[index], (value) => { writes++; slots[index] = typeof value === 'function' ? value(slots[index]) : value; }];
    },
    useLayoutEffect(effect, deps) {
      const index = cursor++;
      const previous = effects[index];
      if (!previous || deps.some((value, i) => !Object.is(value, previous.deps[i]))) {
        effects[index] = { deps, cleanup: previous?.cleanup };
        scheduled.push(() => { effects[index].cleanup?.(); effects[index].cleanup = effect(); });
      }
    },
  };
  const exports = {};
  const localRequire = createRequire(modulePath);
  runInNewContext(readFileSync(modulePath, 'utf8'), {
    exports, document,
    window: {
      getComputedStyle: (element) => ({ lineHeight: metrics.lineHeight, overflowY: element.overflowY || 'auto' }),
      addEventListener(name, listener) { listeners.set(name, listener); },
      removeEventListener(name, listener) { if (listeners.get(name) === listener) listeners.delete(name); },
    },
    navigator: { clipboard: { writeText: (text) => { copied.push(text); return writeText(text); } } },
    ResizeObserver: class {
      constructor(callback) { this.callback = callback; observers.push(this); }
      observe() {}
      disconnect() { this.disconnected = true; }
    },
    require: (name) => name === 'react' ? hooks : localRequire(name),
  });
  return {
    metrics, copied, focus, viewMoves, document, scrollContent: exports.scrollPlanningContentIntoView,
    render(props) {
      cursor = 0;
      const tree = exports.PlanningMessageDisclosure(props);
      body(tree).props.ref.current = metrics;
      if (toggle(tree)) toggle(tree).props.ref.current = { name: 'toggle',
        parentElement: pane, getBoundingClientRect: () => ({ top: 490, bottom: 520, height: 30 }),
        focus(options) { viewMoves.push({ target: 'toggle', action: 'focus', ...options }); },
        scrollIntoView(options) { viewMoves.push({ target: 'toggle', action: 'scroll', ...options }); },
      };
      copyButton(tree).props.ref.current = { focus: (options) => focus.push(options) };
      for (const effect of scheduled.splice(0)) effect();
      return tree;
    },
    resize() { for (const observer of observers) if (!observer.disconnected) observer.callback(); },
    fontLoaded() { fontListeners.get('loadingdone')?.(); },
    windowResized() { listeners.get('resize')?.(); },
    unmount() { for (const effect of effects) effect?.cleanup?.(); },
    writeCount: () => writes,
  };
}
const props = (extra = {}) => ({ text: 'Task 오류\n완료 조건\nAI 응답\n' + JSON.stringify({ log: 'long '.repeat(300) }),
  expanded: false, onExpandedChange() {}, ...extra });
const tick = async () => { await Promise.resolve(); await Promise.resolve(); };

test('primary chat shows full answers by default with copy only, including after refresh and resize', async () => {
  const fixture = harness(); let dialogOpened = false;
  const input = props({ inline: true, onExpandedChange: () => { dialogOpened = true; } });
  fixture.metrics.scrollHeight = 600;
  fixture.render(input); let tree = fixture.render(input);
  assert.equal(body(tree).props['data-expanded'], true); assert.equal(toggle(tree), undefined);
  copyButton(tree).props.onClick(); await tick();
  assert.deepEqual(fixture.copied, [input.text]);
  fixture.metrics.clientWidth = 250; fixture.resize(); fixture.windowResized(); fixture.fontLoaded();
  tree = fixture.render({ ...input, text: input.text + '\n마지막 답변까지 표시' });
  assert.equal(body(tree).props['data-expanded'], true); assert.equal(toggle(tree), undefined);
  const markup = renderToStaticMarkup(tree);
  assert.match(markup, /마지막 답변까지 표시/);
  assert.doesNotMatch(markup, /더 보기|접기|전체 보기/);
  assert.equal(dialogOpened, false); fixture.unmount();
});

test('full chat answers expose keyboard scrolling in code and tables immediately', () => {
  const fixture = harness();
  fixture.metrics.scrollHeight = 600;
  const input = props({ inline: true, text: '```text\n본문\n```\n\n| 상태 |\n| --- |\n| 완료 |' });
  fixture.render(input); let tree = fixture.render(input);
  assert.match(renderToStaticMarkup(body(tree)), /<pre tabindex="0"/);
  assert.match(renderToStaticMarkup(body(tree)), /aria-label="표" tabindex="0"/);
  assert.equal(toggle(tree), undefined);
  fixture.unmount();
});

test('three-line layout uses measured line height with rounding and unknown measurements stay unknown', () => {
  assert.equal(planningMessageOverflows(60, 20), false);
  assert.equal(planningMessageOverflows(60.8, 20), false);
  assert.equal(planningMessageOverflows(100, 20), true);
  assert.equal(planningMessageOverflows(125, 25), true);
  assert.equal(planningMessageOverflows(150, 30), true);
  for (const values of [[100, 0], [100, NaN], [Infinity, 20], [-1, 20]]) {
    assert.equal(planningMessageOverflows(...values), null);
  }
});

test('long messages keep all text in the body and expose native disclosure linked to the body', () => {
  const fixture = harness();
  let expanded = false;
  const input = props({ onExpandedChange: (value) => { expanded = value; } });
  fixture.render(input);
  let tree = fixture.render(input);
  assert.match(renderToStaticMarkup(body(tree)), /Task 오류\n완료 조건\nAI 응답/);
  assert.equal(body(tree).props['data-expanded'], false);
  assert.equal(toggle(tree).props.type, 'button');
  assert.equal(toggle(tree).props['aria-expanded'], false);
  assert.equal(toggle(tree).props['aria-controls'], 'planning-message-dialog'); assert.equal(toggle(tree).props['aria-haspopup'], 'dialog');
  assert.equal(toggle(tree).props.onKeyDown, undefined, 'native Enter and Space behavior is preserved');
  const markup = renderToStaticMarkup(tree);
  assert.ok(markup.indexOf('planning-message-disclosure__body') < markup.indexOf('planning-message-disclosure__actions'));
  assert.equal(toggle(tree).props.children, '전체 보기');
  assert.equal(copyButton(tree).props.children, '복사');
  assert.doesNotMatch(markup, /첫 4줄 표시|나머지 내용 생략/);
  toggle(tree).props.onClick();
  assert.equal(expanded, true);
  tree = fixture.render({ ...input, expanded });
  assert.match(renderToStaticMarkup(body(tree)), /Task 오류\n완료 조건\nAI 응답/);
  assert.equal(toggle(tree).props.children, '전체 보기');
  assert.equal(toggle(tree).props['aria-expanded'], false);
  toggle(tree).props.onClick();
  assert.equal(expanded, true, 'the action requests a popup; it does not collapse or expand the bubble');
  fixture.unmount();
});

test('opening full content never moves or expands the message list itself', () => {
  const fixture = harness(); let opened = 0;
  const input = props({onExpandedChange: () => opened++});
  fixture.render(input); toggle(fixture.render(input)).props.onClick();
  fixture.render({...input, expanded: true}); fixture.windowResized(); fixture.fontLoaded(); fixture.render(input);
  assert.equal(opened, 1); assert.deepEqual(fixture.viewMoves, []);
  assert.equal(body(fixture.render(input)).props['data-expanded'], false);
  fixture.unmount();
});

test('planning scroll remains inside the nearest scrollable pane and never moves hidden outer ancestors', () => {
  const fixture = harness();
  const shell = { scrollTop: 19, parentElement: null, matches: () => false };
  const outer = { scrollTop: 32, clientTop: 0, clientHeight: 500, scrollHeight: 3000, parentElement: shell,
    getBoundingClientRect: () => ({ top: 30 }), matches: (selector) => selector.includes('.task-workbench__body') };
  const inner = { scrollTop: 40, clientTop: 1, clientHeight: 240, scrollHeight: 1600, parentElement: outer,
    getBoundingClientRect: () => ({ top: 50 }), matches: (selector) => selector.includes('.planning-messages') };
  const target = { parentElement: inner, getBoundingClientRect: () => ({ top: 151, bottom: 931, height: 780 }),
    scrollIntoView() { assert.fail('scrollIntoView would move the whole app'); } };
  fixture.scrollContent(target, 'start');
  assert.equal(inner.scrollTop, 140);
  assert.equal(outer.scrollTop, 32);
  assert.equal(shell.scrollTop, 19);
  inner.overflowY = 'visible';
  fixture.scrollContent(target, 'start');
  assert.equal(outer.scrollTop, 153);
  assert.equal(shell.scrollTop, 19);
  outer.overflowY = 'hidden';
  fixture.scrollContent(target, 'start');
  assert.equal(outer.scrollTop, 153);
  assert.equal(shell.scrollTop, 19);
  fixture.unmount();
});

test('emphasis and inline code are readable while copying retains original formatting and line breaks', async () => {
  const fixture = harness();
  const input = props({ text: '현재 실패는 **키 만료 재검증 테스트**입니다.\r\n`KeyExpiry`를 다시 확인합니다.' });
  fixture.render(input);
  const tree = fixture.render(input);
  const markup = renderToStaticMarkup(body(tree));
  assert.match(markup, /<strong>키 만료 재검증 테스트<\/strong>/);
  assert.match(markup, /<code>KeyExpiry<\/code>/);
  assert.match(markup, /\n/);
  assert.doesNotMatch(markup, /\*\*|`/);
  copyButton(tree).props.onClick(); await tick();
  assert.deepEqual(fixture.copied, [input.text]);
  fixture.unmount();
});

test('message display escapes HTML and formats fences while preserving code and unfinished content', () => {
  const fixture = harness();
  const input = props({ text: '<script>alert("test")</script>\n**주의**\n```json\n{"value":"**raw**"}\n```\n\\**literal**\n**미완성' });
  fixture.render(input);
  const markup = renderToStaticMarkup(body(fixture.render(input)));
  assert.match(markup, /&lt;script&gt;/);
  assert.doesNotMatch(markup, /<script>/);
  assert.match(markup, /<strong>주의<\/strong>/);
  assert.match(markup, /<code class="language-json">.*\*\*raw\*\*.*\n<\/code>/);
  assert.doesNotMatch(markup, /```|<strong>raw<\/strong>|<strong>literal<\/strong>/);
  assert.match(markup, /\*\*미완성/);
  fixture.unmount();
});

test('standard nested emphasis, multi-backtick code and tilde fences render in messages', () => {
  const fixture = harness();
  const input = props({ text: '***혼합 강조***\n``여러 구분자``\n~~~text\n**코드 원문**\n~~~\n**정상 강조**' });
  fixture.render(input);
  const markup = renderToStaticMarkup(body(fixture.render(input)));
  assert.match(markup, /<em><strong>혼합 강조<\/strong><\/em>/);
  assert.match(markup, /<code>여러 구분자<\/code>/);
  assert.match(markup, /<code class="language-text">\*\*코드 원문\*\*\n<\/code>/);
  assert.doesNotMatch(markup, /~~~|<strong>코드 원문<\/strong>/);
  assert.match(markup, /<strong>정상 강조<\/strong>/);
  fixture.unmount();
});

test('short messages and font or width changes keep the preview collapsed and remeasure the popup action', () => {
  const fixture = harness();
  const input = props();
  fixture.metrics.scrollHeight = 40;
  fixture.render(input);
  assert.equal(toggle(fixture.render(input)), undefined);
  fixture.metrics.clientWidth = 250;
  fixture.metrics.scrollHeight = 160;
  fixture.resize();
  assert.ok(toggle(fixture.render(input)));
  const expanded = { ...input, expanded: true };
  let tree = fixture.render(expanded);
  assert.equal(body(tree).props['data-expanded'], false);
  fixture.document.activeElement = toggle(tree).props.ref.current;
  fixture.metrics.clientWidth = 900;
  fixture.metrics.scrollHeight = 60;
  fixture.windowResized();
  tree = fixture.render(expanded);
  assert.equal(toggle(tree), undefined);
  assert.equal(body(tree).props['data-expanded'], false);
  assert.equal(fixture.focus.length, 1, 'focus moves to copy in the same message when the now-unnecessary toggle disappears');
  assert.equal(fixture.focus[0].preventScroll, true);
  for (const size of [25, 30]) {
    fixture.metrics.lineHeight = `${size}px`;
    fixture.metrics.scrollHeight = size * 5;
    fixture.fontLoaded();
    tree = fixture.render(expanded);
    assert.equal(toggle(tree).props['aria-expanded'], false);
  }
  fixture.metrics.clientWidth = 0;
  fixture.metrics.scrollHeight = 0;
  fixture.resize();
  assert.ok(toggle(fixture.render(expanded)), 'hidden layout does not invent a short-message result');
  fixture.unmount();
});

test('polling and remounting preserve scoped message identity without restoring inline expansion', () => {
  const memory = {};
  const message = { role: 'user', at: '2026-10-01T00:00:00Z', text: props().text };
  const key = planningMessageKey('project', 'group', message, 0);
  const context = (current) => ({ text: current.text, expanded: Boolean(memory[key]),
    onExpandedChange: (expanded) => { memory[key] = expanded; } });
  const fixture = harness();
  fixture.render(context(message));
  toggle(fixture.render(context(message))).props.onClick();
  assert.equal(memory[key], true);
  const refreshed = JSON.parse(JSON.stringify([message, { role: 'assistant', at: '2026-10-01T00:01:00Z', text: '새 답변' }]));
  assert.equal(planningMessageKey('project', 'group', refreshed[0], 0), key);
  assert.equal(body(fixture.render(context(refreshed[0]))).props['data-expanded'], false);
  fixture.unmount();
  const reopened = harness();
  const tree = reopened.render(context(message));
  assert.equal(body(tree).props['data-expanded'], false);
  for (const otherKey of [planningMessageKey('other', 'group', message, 0), planningMessageKey('project', 'other', message, 0),
    planningMessageKey('project', 'group', message, 1), planningMessageKey('project', 'group', { ...message, role: 'assistant' }, 0)]) {
    assert.equal(memory[otherKey], undefined);
  }
  assert.notEqual(planningMessageKey('a', 'b/c', message, 0), planningMessageKey('a/b', 'c', message, 0));
  assert.equal(refreshed[0].text, message.text);
  reopened.unmount();
});

test('a short display of automatic context retains full view, original copy and stable focus after resize', async () => {
  const fixture = harness();
  fixture.metrics.scrollHeight = 20;
  const input = props({ text: '대상과 상태\n설명 원문\n\n사용자 질문:\n질문', displayText: '질문' });
  let tree = fixture.render(input);
  assert.ok(toggle(tree));
  fixture.document.activeElement = toggle(tree).props.ref.current;
  fixture.resize(); tree = fixture.render(input);
  assert.ok(toggle(tree)); assert.equal(fixture.focus.length, 0);
  await copyButton(tree).props.onClick();
  assert.deepEqual(fixture.copied, [input.text]);
});

test('copy always uses complete original text and repeated clicks share one pending request', async () => {
  let finish;
  const pending = new Promise((resolve) => { finish = resolve; });
  const fixture = harness(() => pending);
  const input = props({ displayText: '기존 한국어 표시 안내' });
  fixture.render(input);
  const tree = fixture.render(input);
  copyButton(tree).props.onClick();
  copyButton(tree).props.onClick();
  assert.deepEqual(fixture.copied, [input.text]);
  assert.equal(copyButton(fixture.render(input)).props.disabled, true);
  finish(); await tick();
  assert.match(renderToStaticMarkup(fixture.render(input)), /복사됨/);
  assert.equal(input.text.includes('long '), true);
  assert.match(renderToStaticMarkup(body(fixture.render(input))), /<p>기존 한국어 표시 안내<\/p>/);
  fixture.unmount();
});

test('clipboard denial is visible, does not claim success, and can be retried', async () => {
  let fail = true;
  const fixture = harness(async () => { if (fail) throw new Error('clipboard denied'); });
  const input = props();
  fixture.render(input);
  copyButton(fixture.render(input)).props.onClick(); await tick();
  let tree = fixture.render(input);
  assert.match(renderToStaticMarkup(tree), /clipboard denied/);
  assert.doesNotMatch(renderToStaticMarkup(tree), /복사됨/);
  assert.ok(find(tree, (item) => item.props?.role === 'alert'));
  fail = false;
  copyButton(tree).props.onClick(); await tick();
  tree = fixture.render(input);
  assert.match(renderToStaticMarkup(tree), /복사됨/);
  assert.equal(find(tree, (item) => item.props?.role === 'alert'), undefined);
  fixture.unmount();
});

test('late clipboard completion and measurement callbacks cannot update an unmounted message', async () => {
  let finish;
  const pending = new Promise((resolve) => { finish = resolve; });
  const fixture = harness(() => pending);
  const input = props();
  fixture.render(input);
  copyButton(fixture.render(input)).props.onClick();
  fixture.unmount();
  const writes = fixture.writeCount();
  finish(); await tick();
  fixture.resize(); fixture.fontLoaded(); fixture.windowResized();
  assert.equal(fixture.writeCount(), writes);
});

test('a changed stored text clears old copy receipt and ignores the previous pending result', async () => {
  let finish;
  const pending = new Promise((resolve) => { finish = resolve; });
  const fixture = harness(() => pending);
  const initial = props();
  fixture.render(initial);
  copyButton(fixture.render(initial)).props.onClick();
  const changed = { ...initial, text: 'changed\r\ntext', expanded: true };
  fixture.render(changed);
  finish(); await tick();
  const tree = fixture.render(changed);
  assert.doesNotMatch(renderToStaticMarkup(tree), /복사됨/);
  assert.equal(copyButton(tree).props.disabled, false);
  assert.equal(body(tree).props['data-expanded'], false);
  assert.match(renderToStaticMarkup(body(tree)), /<p>changed\r?\ntext<\/p>/);
  fixture.unmount();
});
