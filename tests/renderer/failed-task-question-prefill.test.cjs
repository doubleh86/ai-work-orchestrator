const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');
const { renderToStaticMarkup } = require('react-dom/server');
const root = resolve(__dirname, '../..'), tempRoot = join(root, '.tmp');
mkdirSync(tempRoot, { recursive: true });
const output = mkdtempSync(join(tempRoot, 'failed-question-'));
process.on('exit', () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); });
const packagePath = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig', '--strict',
  '--target', 'ES2022', '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
  'desktop/renderer/src/App.tsx', 'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });
const { FailedTaskQuestionDrafts, failedTaskQuestionKey } = require(join(output, 'renderer/src/failedTaskQuestionDrafts.js'));
const { DirectionChangeDrafts } = require(join(output, 'renderer/src/directionChangeDrafts.js'));
const { taskRepairMessage, taskRepairQuestion } = require(join(output, 'renderer/src/TaskRepairPanel.js'));
const run = { id: 'group', stage: 'failed', plan_revision: 1, failed_step: 'agent_execution' };
const task = (id = 'a', extra = {}) => ({ id, title: `작업 ${id}`, status: 'failed', error: 'test failed', attempt_count: 1,
  last_attempt_id: 'attempt-1', acceptance_criteria: ['test expected behavior'], ...extra });
const context = (id = 'a') => ({ task_id: id, title: `작업 ${id}`, error: 'test failed', response: `worker response ${id}`,
  acceptance_criteria: ['test expected behavior'], fingerprint: 'failure', instruction_current: true, instruction: { text: 'keep original contract' } });
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const settle = () => new Promise(setImmediate);

test('prefill keeps user prose and replaces only one intact app-owned block without repetition', () => {
  const drafts = new FailedTaskQuestionDrafts();
  let value = drafts.prepare('p', 'g', 'a', '내 질문', '실패 자료 A');
  assert.equal(value, '내 질문\n\n실패 자료 A');
  assert.equal(drafts.prepare('p', 'g', 'a', value, '실패 자료 A'), value);
  value += '\n사용자 추가 설명';
  value = drafts.prepare('p', 'g', 'b', value, '실패 자료 B');
  assert.equal(value, '내 질문\n\n실패 자료 B\n사용자 추가 설명');
  assert.equal(drafts.prepare('p', 'g', 'a', value, '실패 자료 A'), '내 질문\n\n실패 자료 A\n사용자 추가 설명');
});

test('editing or removing the app block protects user changes through retries and Task switches', () => {
  const drafts = new FailedTaskQuestionDrafts();
  const first = drafts.prepare('p', 'g', 'a', '', '오류 A와 원문');
  const edited = first.replace('원문', '내가 수정한 내용');
  assert.equal(drafts.prepare('p', 'g', 'a', edited, '오류 A와 새 원문'), edited);
  const switched = drafts.prepare('p', 'g', 'b', edited, '오류 B와 원문');
  assert.equal(switched, `${edited}\n\n오류 B와 원문`);
  const restored = drafts.prepare('p', 'g', 'a', switched, '오류 A와 새 원문');
  assert.equal(restored.trimEnd(), edited);
  assert.equal(drafts.prepare('p', 'g', 'a', restored, '오류 A와 새 원문'), restored);
  assert.equal(drafts.prepare('p', 'g', 'a', '', '새 원문'), '새 원문', 'a fresh explicit empty input can be prepared again');
});

test('duplicate pasted blocks are never rewritten and draft ownership stays scoped to project and group', () => {
  const drafts = new FailedTaskQuestionDrafts();
  drafts.prepare('p', 'g', 'a', '', '원문 A');
  const duplicate = '원문 A\n원문 A';
  assert.equal(drafts.prepare('p', 'g', 'a', duplicate, '새 원문'), duplicate);
  assert.equal(drafts.prepare('other', 'g', 'a', '다른 초안', '원문 A'), '다른 초안\n\n원문 A');
  assert.equal(drafts.prepare('p', 'other-group', 'a', '다른 그룹', '원문 A'), '다른 그룹\n\n원문 A');
});

test('clearing or sending releases the old question while preserving diagnostics and a different selected task', () => {
  const drafts = new FailedTaskQuestionDrafts();
  drafts.prepare('p', 'g', 'a', '', '질문 A', '진단 A');
  drafts.release('p', 'g');
  assert.equal(drafts.prepare('p', 'g', 'a', '새로 쓴 내용', '질문 A', drafts.diagnostic('p', 'g', 'a')), '새로 쓴 내용\n\n질문 A');
  assert.equal(drafts.diagnostic('p', 'g', 'a'), '진단 A');
  drafts.release('p', 'g', 'a');
  assert.equal(drafts.prepare('p', 'g', 'a', '다음 질문', '질문 A'), '다음 질문\n\n질문 A');
  const next = drafts.prepare('p', 'g', 'b', '입력\n\n질문 A', '질문 B');
  drafts.release('p', 'g', 'a');
  assert.equal(drafts.prepare('p', 'g', 'b', next, '새 질문 B'), '입력\n\n새 질문 B');
});

test('failure identity tracks attempts and saved contract but excludes polling timestamps', () => {
  const key = failedTaskQuestionKey('p', run, task());
  assert.equal(failedTaskQuestionKey('p', { ...run, updated_at: 'poll' }, task()), key);
  for (const changes of [{ last_attempt_id: 'new' }, { status: 'completed' }, { attempt_count: 2 }, { error: 'new error' }]) {
    assert.notEqual(failedTaskQuestionKey('p', run, task('a', changes)), key);
  }
  assert.notEqual(failedTaskQuestionKey('other', run, task()), key);
  assert.notEqual(failedTaskQuestionKey('p', { ...run, id: 'other' }, task()), key);
});

function panelHost(api) {
  const slots = [], pending = []; let cursor = 0, tree;
  const react = {
    useState(initial) { const index = cursor++; if (!(index in slots)) slots[index] = initial;
      return [slots[index], value => { slots[index] = typeof value === 'function' ? value(slots[index]) : value; }]; },
    useRef(initial) { const index = cursor++; return slots[index] ||= { current: initial }; },
    useEffect(effect, deps) { const index = cursor++, previous = slots[index];
      if (previous && deps.every((value, i) => Object.is(value, previous.deps[i]))) return;
      pending.push(() => { previous?.cleanup?.(); slots[index] = { deps, cleanup: effect() }; }); },
  };
  const panelPath = join(output, 'renderer/src/TaskRepairPanel.js'), localRequire = createRequire(panelPath), exported = {};
  runInNewContext(readFileSync(panelPath, 'utf8'), { exports: exported, window: { orchestrator: api },
    require: name => name === 'react' ? react : localRequire(name) });
  return { render(props) { cursor = 0; tree = exported.TaskRepairPanel(props); return tree; },
    flush() { while (pending.length) pending.shift()(); },
    dispose() { slots.forEach(slot => slot?.cleanup?.()); },
    markup() { return renderToStaticMarkup(tree); } };
}
const props = (onPrepared, changes = {}) => ({ projectName: 'p', run, task: task(), draftRevision: 3, onPrepared, ...changes });
function elements(tree, predicate, result = []) {
  if (!tree || typeof tree !== 'object') return result;
  if (Array.isArray(tree)) { tree.forEach(child => elements(child, predicate, result)); return result; }
  if (predicate(tree)) result.push(tree); elements(tree.props?.children, predicate, result); return result;
}

test('automatic preparation waits for both read-only sources and captures the starting draft revision', async () => {
  const c = deferred(), l = deferred(), prepared = [], calls = [];
  const h = panelHost({ request(method, params) { calls.push([method, params]); return method === 'tasks.log' ? l.promise : c.promise; } });
  h.render(props((...args) => prepared.push(args))); h.flush(); c.resolve(context()); await settle();
  assert.deepEqual(prepared, []);
  h.render(props((...args) => prepared.push(args), { draftRevision: 8 })); h.flush();
  l.resolve('original log'); await settle();
  assert.deepEqual(prepared, [[taskRepairQuestion(context()), 3, taskRepairMessage(context(), 'original log', 'keep original contract')]]);
  assert.deepEqual(calls.map(call => call[0]), ['tasks.retryContext', 'tasks.log']);
  h.render(props(() => assert.fail('polling cannot prepare again'), { draftRevision: 9, run: { ...run, updated_at: 'new poll' } })); h.flush();
  assert.equal(calls.length, 2); h.dispose();
});

test('late evidence cannot prepare another Task, project, group, failure attempt or resolved state', async () => {
  for (const change of [{ task: task('b') }, { projectName: 'other' }, { run: { ...run, id: 'other-group' } },
    { task: task('a', { last_attempt_id: 'next-attempt' }) }, { task: task('a', { status: 'completed' }) }]) {
    const c = deferred(), l = deferred(), prepared = [];
    const h = panelHost({ request: method => method === 'tasks.log' ? l.promise : c.promise });
    h.render(props((...args) => prepared.push(args))); h.flush();
    h.render(props((...args) => prepared.push(args), change));
    c.resolve(context()); l.resolve('late log'); await settle();
    assert.deepEqual(prepared, [], 'render identity guards even before the effect cleanup'); h.dispose();
  }
});

test('context failure stays visible and read-only retry can recover without an attachment step', async () => {
  const prepared = [], calls = []; let failed = true;
  const h = panelHost({ request: async method => { calls.push(method);
    if (method === 'tasks.log') return 'log'; if (failed) throw new Error('context disconnected'); return context(); } });
  const p = props((...args) => prepared.push(args)); h.render(p); h.flush(); await settle();
  let tree = h.render(p); assert.deepEqual(prepared, []);
  assert.match(h.markup(), /실패 자료를 준비하지 못했습니다|context disconnected/);
  assert.doesNotMatch(h.markup(), /작업 상태 확인 중|실패 기록을 대화에 첨부/);
  failed = false;
  elements(tree, n => n.type === 'button' && n.props.children === '실패 자료 다시 조회')[0].props.onClick(); await settle();
  h.render(p); assert.equal(prepared.length, 1); assert.deepEqual(calls, ['tasks.retryContext', 'tasks.log', 'tasks.retryContext', 'tasks.log']);
  h.dispose();
});

test('log failure prepares explicit partial evidence, then replaces it with the real log on retry', async () => {
  const original = new FailedTaskQuestionDrafts(); let draft = '', failed = true;
  const h = panelHost({ request: async method => { if (method === 'tasks.retryContext') return context();
    if (failed) throw new Error('log disconnected'); return 'recovered exact log'; } });
  const p = props((message, revision, diagnostic) => { draft = original.prepare('p', 'group', 'a', draft, message, diagnostic); });
  h.render(p); h.flush(); await settle(); const tree = h.render(p);
  assert.doesNotMatch(draft, /log disconnected|worker response a|관련 로그/);
  assert.match(original.diagnostic('p', 'group', 'a'), /실행 기록 조회 실패: Error: log disconnected/);
  assert.match(original.diagnostic('p', 'group', 'a'), /worker response a/);
  assert.match(h.markup(), /로그 조회 실패|실행 기록을 조회하지 못했습니다/);
  failed = false;
  elements(tree, n => n.type === 'button' && n.props.children === '실패 자료 다시 조회')[0].props.onClick(); await settle();
  assert.match(original.diagnostic('p', 'group', 'a'), /recovered exact log/);
  assert.doesNotMatch(original.diagnostic('p', 'group', 'a'), /log disconnected/);
  assert.equal((draft.match(/이 작업의 문제/g) || []).length, 1); h.dispose();
});

test('wrong-task context and unmounted question never prepare text; stale instructions are excluded', async () => {
  const prepared = []; let wrong = true;
  const h = panelHost({ request: async method => method === 'tasks.log' ? '' : wrong ? context('b')
    : { ...context(), instruction_current: false } });
  const p = props((message, revision, diagnostic) => prepared.push(diagnostic)); h.render(p); h.flush(); await settle(); let tree = h.render(p);
  assert.deepEqual(prepared, []); assert.match(h.markup(), /현재 질문 대상과 다릅니다/);
  wrong = false; elements(tree, n => n.type === 'button')[0].props.onClick(); await settle();
  assert.equal(prepared.length, 1); assert.doesNotMatch(prepared[0], /keep original contract/); h.dispose();
  const late = deferred(), closed = panelHost({ request: () => late.promise });
  closed.render(p); closed.flush(); closed.dispose(); late.resolve(context()); await settle();
  assert.equal(prepared.length, 1);
});

function appPreparation(bindings) {
  const source = readFileSync(join(output, 'renderer/src/App.js'), 'utf8');
  const marker = 'onPrepared: (_message, _revision, diagnostic) => {';
  const begin = source.indexOf(marker); assert.ok(begin >= 0);
  const start = begin + marker.indexOf('(_message'); let end = source.indexOf('{', start), depth = 1;
  while (depth) { end++; if (source[end] === '{') depth++; else if (source[end] === '}') depth--; }
  const exported = {};
  runInNewContext(`exports.prepare=${source.slice(start, end + 1)}`, { exports: exported, ...bindings });
  return exported.prepare;
}

test('late failure diagnostics never insert or alter a composer draft', () => {
  for (const state of ['empty', 'prose', 'cleared', 'submitted', 'switched', 'cleared-target']) {
    const store = new DirectionChangeDrafts(() => 'request'), templates = new FailedTaskQuestionDrafts();
    const target = { current: 'source' };
    if (state !== 'empty') store.edit('p', 'group', '작성 중인 질문');
    const revision = store.read('p', 'group').editRevision;
    const prepare = appPreparation({ directionChangeDrafts: store, failedQuestionDrafts: { current: templates },
      failedQuestionTargetRef: target, failedQuestionKey: 'source', selectedProjectName: 'p', selectedRun: run,
      repairTarget: { projectName: 'p', runId: run.id } });
    if (state === 'cleared' || state === 'submitted') store.edit('p', 'group', '');
    if (state === 'switched') target.current = 'other';
    if (state === 'cleared-target') target.current = '';
    prepare('실패 자료', revision, '정확한 원문 진단');
    assert.equal(store.read('p', 'group').text, ['empty', 'cleared', 'submitted'].includes(state) ? '' : '작성 중인 질문');
    assert.equal(store.read('other', 'group').text, '');
    assert.equal(templates.diagnostic('p', 'group', 'source'), ['switched', 'cleared-target'].includes(state) ? '' : '정확한 원문 진단');
  }
});
