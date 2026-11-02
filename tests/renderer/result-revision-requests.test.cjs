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
const output = resolve(mkdtempSync(join(tempRoot, 'result-request-')));
const cleanup = () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); };
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  execFileSync(process.execPath, [resolve(dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig',
    '--strict', '--target', 'ES2022', '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck',
    '--rootDir', 'desktop', '--outDir', output, 'desktop/renderer/src/ResultReview.tsx',
    'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);
const modulePath = join(output, 'renderer/src/ResultReview.js');
const { ResultRevisionRequests, resultRevisionRequestKey: key } = require(join(output, 'renderer/src/resultRevisionRequests.js'));

const draft = (extra = {}) => ({ requestId: '', text: '수정 요청', proposalId: '', reply: '', ...extra });
const task = (id) => ({ id, title: id, status: 'failed', description: '', acceptance_criteria: [], action_results: [], result_history: [] });
const run = (extra = {}) => ({ id: 'group', summary: '결과', stage: 'failed', failed_step: 'agent_execution',
  tasks: [task('a'), task('b')], verification_attempts: [], group_result_history: [], ...extra });
const proposal = (extra = {}) => ({ proposal_id: 'proposal', text: '수정 요청', focus_task_id: 'a', status: 'ready',
  fingerprint: 'result', summary: '수정 제안', reason: '실패 근거', task_ids: ['a'], paths: ['a.ts'],
  question: '', next_action: 'retry_task', error: '', created_at: '2026-10-01T01:00:00Z', stale: false, ...extra });
const links = (extra = {}) => ({ requests: [], proposals: [], children: [], origin: null, ...extra });
const receipt = (params, extra = {}) => ({ request_id: params.requestId, proposal_id: params.proposalId,
  text: params.text, task_ids: params.taskIds, paths: params.paths, target_run_id: params.runId,
  handling: 'same_task_retry', created_at: '2026-10-01T01:00:00Z', ...extra });
function store() { let index = 0; return new ResultRevisionRequests(() => `request-${++index}`); }
function api() {
  const calls = [];
  return { calls, request(method, params) {
    return new Promise((resolve, reject) => calls.push({ method, params, resolve, reject }));
  } };
}
function find(tree, predicate) {
  if (!tree || typeof tree !== 'object') return undefined;
  if (Array.isArray(tree)) {
    for (const child of tree) { const found = find(child, predicate); if (found) return found; }
    return undefined;
  }
  return predicate(tree) ? tree : find(tree.props?.children, predicate);
}
function text(tree) {
  if (typeof tree === 'string') return tree;
  if (Array.isArray(tree)) return tree.map(text).join('');
  return text(tree?.props?.children || '');
}
const button = (tree, label) => find(tree, (item) => item.type === 'button' && text(item) === label);
const input = (tree, rows = 3) => find(tree, (item) => item.type === 'textarea' && item.props.rows === rows);
const generate = (tree) => find(tree, (item) => item.type === 'button' && /대화로 수정안|수정안 작성 중/.test(text(item)));
const operations = (rpc, method) => rpc.calls.filter((item) => item.method === method);
const tick = async () => { for (let i = 0; i < 5; i++) await Promise.resolve(); };

// These hook/RPC lifecycle tests do not run Electron or call an external AI.
function harness(rpc, requests = store(), drafts = new Map(), extra = {}) {
  const slots = [];
  const effects = [];
  const scheduled = [];
  let cursor = 0;
  let writes = 0;
  const navigation = [];
  let props = { projectName: 'project', run: run(), focusTaskId: 'a', requests,
    onNavigate: (...args) => navigation.push(args), onOpenTask: (...args) => navigation.push(args), onOpenOperations() {}, ...extra };
  function effect(callback, deps) {
    const index = cursor++;
    const previous = effects[index];
    if (!previous || deps.some((value, i) => !Object.is(value, previous.deps[i]))) {
      effects[index] = { deps, cleanup: previous?.cleanup };
      scheduled.push(() => { effects[index].cleanup?.(); effects[index].cleanup = callback(); });
    }
  }
  const hooks = {
    useRef(initial) { const index = cursor++; return slots[index] ||= { current: initial }; },
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial;
      return [slots[index], (value) => { writes++; slots[index] = typeof value === 'function' ? value(slots[index]) : value; }];
    },
    useEffect: effect,
    useSyncExternalStore(subscribe, snapshot) { effect(() => subscribe(() => {}), [subscribe]); return snapshot(); },
  };
  const exports = {};
  const localRequire = createRequire(modulePath);
  runInNewContext(readFileSync(modulePath, 'utf8'), { exports, window: { orchestrator: rpc },
    require: (name) => name === 'react' ? hooks : localRequire(name) });
  const currentKey = () => key(props.projectName, props.run.id, props.run.tasks.some((item) => item.id === props.focusTaskId) ? props.focusTaskId : '');
  return {
    drafts, requests, navigation,
    render(patch = {}) {
      props = { ...props, ...patch };
      const target = currentKey();
      cursor = 0;
      const tree = exports.ResultReview({ ...props, draft: drafts.get(target), onDraftChange(update) {
        const current = drafts.get(target);
        const next = typeof update === 'function' ? update(current) : update;
        if (next && next !== current) drafts.set(target, next);
      } });
      for (const callback of scheduled.splice(0)) callback();
      return tree;
    },
    setDraft(value) { drafts.set(currentKey(), value); },
    getDraft: () => drafts.get(currentKey()),
    unmount() { for (const item of effects) item?.cleanup?.(); },
    writeCount: () => writes,
  };
}
function fixture(rpc = api(), requests = store(), drafts = new Map([[key('project', 'group', 'a'), draft()]]), extra = {}) {
  requests.setEditorOpen(key(extra.projectName || 'project', extra.run?.id || 'group', extra.focusTaskId ?? 'a'), true);
  return { rpc, view: harness(rpc, requests, drafts, extra) };
}
async function load(fixture, data = links()) {
  fixture.view.render();
  operations(fixture.rpc, 'runs.resultRevisions').at(-1).resolve(data);
  await tick();
  return fixture.view.render();
}

test('unused result requests stay closed while drafts, pending work and failures remain visible', async () => {
  const f=fixture(api(),store(),new Map());
  const request=tree=>find(tree,item=>item.props?.className==='result-review__request');
  const details=tree=>find(tree,item=>item.props?.className==='result-review__details');
  const loaded=await load(f);
  assert.equal(request(loaded).props.open,false);
  assert.equal(details(loaded).props.open,false);
  assert.equal(operations(f.rpc,'runs.proposeResultRevision').length,0);
  assert.equal(operations(f.rpc,'runs.createResultRevision').length,0);
  f.view.setDraft(draft());
  assert.equal(request(f.view.render()).props.open,true);
  assert.equal(details(f.view.render()).props.open,true,'a draft cannot be hidden by the outer disclosure');
  generate(f.view.render()).props.onClick();
  assert.equal(request(f.view.render()).props.open,true);
  operations(f.rpc,'runs.proposeResultRevision')[0].reject(new Error('제안 생성 실패 원문'));
  await tick();
  const tree=f.view.render();
  assert.equal(request(tree).props.open,true);
  assert.equal(details(tree).props.open,true);
  assert.match(renderToStaticMarkup(tree),/제안 생성 실패 원문/);
  assert.equal(f.view.getDraft().text,'수정 요청');
  assert.equal(operations(f.rpc,'runs.createResultRevision').length,0);
  f.view.unmount();
});

test('Task, group, and project drafts preserve request and reply independently without automatic generation', async () => {
  const f = fixture();
  await load(f);
  f.view.setDraft(draft({ reply: 'A 답변' }));
  await load({ ...f, view: f.view }, links());
  f.view.render({ focusTaskId: 'b' });
  f.view.requests.setEditorOpen(key('project', 'group', 'b'), true);
  await load(f);
  assert.equal(input(f.view.render()), undefined, 'feedback uses the existing Planning conversation');
  f.view.setDraft(draft({ text: 'B 요청' }));
  f.view.render({ focusTaskId: '' });
  f.view.requests.setEditorOpen(key('project', 'group'), true);
  await load(f);
  assert.equal(f.view.getDraft(), undefined);
  f.view.render({ projectName: 'other', focusTaskId: 'a' });
  f.view.requests.setEditorOpen(key('other', 'group', 'a'), true);
  await load(f);
  assert.equal(f.view.getDraft(), undefined);
  f.view.render({ projectName: 'project', focusTaskId: 'a' });
  await load(f);
  assert.equal(f.view.getDraft().reply, 'A 답변');
  assert.equal(f.view.getDraft().text, '수정 요청');
  f.view.render({ focusTaskId: 'b' });
  await load(f);
  assert.equal(f.view.getDraft().text, 'B 요청');
  assert.equal(operations(f.rpc, 'runs.proposeResultRevision').length, 0);
  assert.equal(operations(f.rpc, 'runs.createResultRevision').length, 0);
  f.view.unmount();
});

test('rapid generate clicks and screen reentry share pending work and preserve its completed proposal', async () => {
  const f = fixture();
  await load(f);
  const action = generate(f.view.render());
  action.props.onClick(); action.props.onClick();
  assert.equal(operations(f.rpc, 'runs.proposeResultRevision').length, 1);
  f.view.unmount();
  const writes = f.view.writeCount();
  const returned = harness(f.rpc, f.view.requests, f.view.drafts);
  await load({ rpc: f.rpc, view: returned });
  assert.equal(generate(returned.render()).props.disabled, true);
  generate(returned.render()).props.onClick();
  const call = operations(f.rpc, 'runs.proposeResultRevision')[0];
  call.resolve(proposal({ proposal_id: call.params.proposalId }));
  await tick();
  assert.equal(f.view.writeCount(), writes, 'late response must not set state on an unmounted component');
  assert.equal(returned.getDraft().proposalId, call.params.proposalId);
  assert.match(renderToStaticMarkup(returned.render()), /AI 수정 제안/);
  assert.equal(operations(f.rpc, 'runs.proposeResultRevision').length, 1);
  assert.equal(operations(f.rpc, 'runs.createResultRevision').length, 0);
  returned.unmount();
});

test('saved Planning discussion supplies result feedback without a second input form or automatic save', async () => {
  let discussions = 0;
  const f = fixture(api(), store(), new Map(), { discussionText: '나: 버튼을 크게 해줘', onDiscuss: () => discussions++ });
  await load(f);
  const tree = f.view.render();
  assert.equal(input(tree), undefined);
  button(tree, '채팅에서 이어가기').props.onClick();
  assert.equal(discussions, 1); assert.equal(operations(f.rpc, 'runs.proposeResultRevision').length, 0);
  generate(tree).props.onClick();
  const call = operations(f.rpc, 'runs.proposeResultRevision')[0];
  assert.equal(call.params.text, '나: 버튼을 크게 해줘');
  call.resolve(proposal({ text: call.params.text, proposal_id: call.params.proposalId }));
  await tick();
  assert.equal(f.view.getDraft().text, call.params.text);
  assert.equal(operations(f.rpc, 'runs.createResultRevision').length, 0);
  f.view.unmount();
});

test('cached proposal with a different ID is accepted when original text and Task match', async () => {
  const f = fixture();
  await load(f);
  generate(f.view.render()).props.onClick();
  const call = operations(f.rpc, 'runs.proposeResultRevision')[0];
  call.resolve(proposal({ proposal_id: 'cached-proposal' }));
  await tick();
  assert.notEqual(call.params.proposalId, f.view.getDraft().proposalId);
  assert.equal(f.view.getDraft().proposalId, 'cached-proposal');
  assert.match(renderToStaticMarkup(f.view.render()), /AI 수정 제안/);
  f.view.unmount();
});

test('late generation never replaces an edited draft or another Task input', async () => {
  const f = fixture();
  await load(f);
  generate(f.view.render()).props.onClick();
  const first = operations(f.rpc, 'runs.proposeResultRevision')[0];
  f.view.setDraft(draft({ text: '새 입력' }));
  f.view.render({ focusTaskId: 'b' });
  f.view.setDraft(draft({ text: 'B 입력' }));
  first.resolve(proposal({ proposal_id: first.params.proposalId }));
  await tick();
  assert.equal(f.view.getDraft().text, 'B 입력');
  assert.equal(f.view.drafts.get(key('project', 'group', 'a')).text, '새 입력');
  assert.equal(operations(f.rpc, 'runs.createResultRevision').length, 0);
  f.view.unmount();
});

test('wrong Task, text, empty ID, and incomplete proposal are visible failures without changing the draft', async () => {
  for (const overrides of [{ focus_task_id: 'b' }, { text: '다른 요청' }, { proposal_id: '' }, { status: 'generating' }]) {
    const f = fixture();
    await load(f);
    const original = f.view.getDraft();
    generate(f.view.render()).props.onClick();
    operations(f.rpc, 'runs.proposeResultRevision')[0].resolve(proposal(overrides));
    await tick();
    assert.equal(f.view.getDraft(), original);
    assert.match(renderToStaticMarkup(f.view.render()), /완료 기록이 요청과 일치하지 않습니다/);
    assert.equal(operations(f.rpc, 'runs.createResultRevision').length, 0);
    f.view.unmount();
  }
});

test('failed AI clarification keeps the original question reply and leaves the result readable', async () => {
  const f = fixture();
  await load(f, links({ proposals: [proposal({ status: 'needs_clarification', question: '어느 부분인가요?' })] }));
  f.view.setDraft({ ...f.view.getDraft(), reply: '  창 크기 부분입니다  ' });
  generate(f.view.render()).props.onClick();
  const call = operations(f.rpc, 'runs.proposeResultRevision')[0];
  assert.match(call.params.text, /확인 질문: 어느 부분인가요/);
  assert.match(call.params.text, /사용자 답변·수정: 창 크기 부분입니다/);
  call.resolve(proposal({ proposal_id: call.params.proposalId, text: call.params.text.trim(), status: 'failed', error: 'AI 오류' }));
  await tick();
  assert.equal(f.view.getDraft().reply, '  창 크기 부분입니다  ');
  const markup = renderToStaticMarkup(f.view.render());
  assert.match(markup, /AI 수정 제안 실패 · AI 오류/);
  assert.match(markup, /변경 파일/);
  assert.match(markup, /미검증/);
  assert.doesNotMatch(markup, /수정안 저장됨/);
  f.view.unmount();
});

test('save clicks share one request and a successful receipt survives failed relationship refresh', async () => {
  const f = fixture();
  await load(f, links({ proposals: [proposal()] }));
  const save = button(f.view.render(), '수정안 확인·저장');
  save.props.onClick(); save.props.onClick();
  assert.equal(operations(f.rpc, 'runs.createResultRevision').length, 1);
  const call = operations(f.rpc, 'runs.createResultRevision')[0];
  call.resolve(receipt(call.params));
  await tick();
  f.view.render();
  operations(f.rpc, 'runs.resultRevisions').at(-1).reject(new Error('조회 연결 끊김'));
  await tick();
  const markup = renderToStaticMarkup(f.view.render());
  assert.match(markup, /수정안 저장됨/);
  assert.match(markup, /후속 요청 관계를 확인하지 못했습니다/);
  assert.doesNotMatch(markup, /초안을 저장하지 못했습니다/);
  assert.equal(f.view.navigation.length, 0, 'saving does not run or navigate automatically');
  f.view.unmount();
});

test('uncertain save survives navigation and retries with the same request ID', async () => {
  const f = fixture();
  await load(f, links({ proposals: [proposal()] }));
  button(f.view.render(), '수정안 확인·저장').props.onClick();
  const first = operations(f.rpc, 'runs.createResultRevision')[0];
  f.view.unmount();
  first.reject(new Error('응답 유실'));
  await tick();
  const returned = harness(f.rpc, f.view.requests, f.view.drafts);
  await load({ rpc: f.rpc, view: returned }, links({ proposals: [proposal()] }));
  assert.equal(returned.getDraft().requestId, first.params.requestId);
  assert.match(renderToStaticMarkup(returned.render()), /응답 유실/);
  button(returned.render(), '수정안 확인·저장').props.onClick();
  const second = operations(f.rpc, 'runs.createResultRevision')[1];
  assert.equal(second.params.requestId, first.params.requestId);
  second.resolve(receipt(second.params));
  await tick();
  assert.match(renderToStaticMarkup(returned.render()), /수정안 저장됨/);
  returned.unmount();
});

test('a delayed empty relationship list cannot contradict a confirmed save', async () => {
  const f = fixture();
  await load(f, links({ proposals: [proposal()] }));
  button(f.view.render(), '수정안 확인·저장').props.onClick();
  const call = operations(f.rpc, 'runs.createResultRevision')[0];
  call.resolve(receipt(call.params));
  await tick();
  await load(f);
  const markup = renderToStaticMarkup(f.view.render());
  assert.match(markup, /수정안 저장됨/);
  assert.doesNotMatch(markup, /연결된 후속 요청 없음/);
  assert.equal(find(f.view.render(),item=>item.props?.className==='result-review__related'),undefined,
    'the currently shown receipt does not create an empty related-work disclosure');
  button(f.view.render(), '새 수정 요청').props.onClick();
  assert.match(renderToStaticMarkup(f.view.render()), /같은 Task 재시도 지시/);
  assert.equal(operations(f.rpc, 'runs.createResultRevision').length, 1);
  f.view.unmount();
});

test('late save confirms only its original project and remains available when reopened', async () => {
  const f = fixture();
  await load(f, links({ proposals: [proposal()] }));
  button(f.view.render(), '수정안 확인·저장').props.onClick();
  const call = operations(f.rpc, 'runs.createResultRevision')[0];
  f.view.render({ projectName: 'other' });
  f.view.setDraft(draft({ text: '다른 프로젝트 입력' }));
  call.resolve(receipt(call.params));
  await tick();
  assert.equal(f.view.getDraft().text, '다른 프로젝트 입력');
  assert.equal(f.view.requests.read(key('other', 'group', 'a')).saved, undefined);
  f.view.unmount();
  const returned = harness(f.rpc, f.view.requests, f.view.drafts);
  returned.render();
  operations(f.rpc, 'runs.resultRevisions').at(-1).reject(new Error('목록 조회 실패'));
  await tick();
  assert.match(renderToStaticMarkup(returned.render()), /수정안 저장됨/);
  assert.equal(returned.navigation.length, 0);
  returned.unmount();
});

test('mismatched save ID, proposal, text, targets, paths, or destination never becomes saved', async () => {
  for (const overrides of [{ request_id: 'wrong' }, { proposal_id: 'wrong' }, { text: 'wrong' },
    { task_ids: ['b'] }, { paths: ['b.ts'] }, { target_run_id: '' }]) {
    const f = fixture();
    await load(f, links({ proposals: [proposal()] }));
    button(f.view.render(), '수정안 확인·저장').props.onClick();
    const call = operations(f.rpc, 'runs.createResultRevision')[0];
    call.resolve(receipt(call.params, overrides));
    await tick();
    const markup = renderToStaticMarkup(f.view.render());
    assert.match(markup, /저장 기록이 확인한 제안과 일치하지 않습니다/);
    assert.doesNotMatch(markup, /수정안 저장됨/);
    assert.equal(f.view.getDraft().requestId, call.params.requestId);
    f.view.unmount();
  }
});

test('fresh server stale evidence overrides remembered proposals even if the next refresh fails', async () => {
  const f = fixture();
  const scope = key('project', 'group', 'a');
  const pending = f.view.requests.begin(scope, 'generate');
  f.view.requests.complete(scope, pending, { proposal: proposal() });
  await load(f, links({ proposals: [proposal({ stale: true })] }));
  assert.equal(button(f.view.render(), '수정안 확인·저장'), undefined);
  assert.match(renderToStaticMarkup(f.view.render()), /원본 결과가 바뀌었습니다/);
  const next = f.view.requests.begin(scope, 'generate');
  f.view.requests.complete(scope, next, { proposal: proposal() });
  f.view.render();
  operations(f.rpc, 'runs.resultRevisions').at(-1).reject(new Error('재조회 실패'));
  await tick();
  assert.equal(button(f.view.render(), '수정안 확인·저장'), undefined);
  assert.equal(operations(f.rpc, 'runs.createResultRevision').length, 0);
  f.view.unmount();
});

test('restoring server proposals never replaces new text typed during the read', async () => {
  const f = fixture(api(), store(), new Map());
  f.view.render();
  f.view.setDraft(draft({ text: '새 입력' }));
  operations(f.rpc, 'runs.resultRevisions').at(-1).resolve(links({ proposals: [proposal()] }));
  await tick();
  assert.equal(f.view.getDraft().text, '새 입력');
  assert.equal(operations(f.rpc, 'runs.proposeResultRevision').length, 0);
  f.view.unmount();
});

test('stale handlers and late query errors cannot submit or change state after scope change or unmount', async () => {
  const f = fixture();
  await load(f, links({ proposals: [proposal()] }));
  const oldGenerate = generate(f.view.render());
  const oldSave = button(f.view.render(), '수정안 확인·저장');
  f.view.render({ focusTaskId: 'b' });
  const read = operations(f.rpc, 'runs.resultRevisions').at(-1);
  oldGenerate.props.onClick(); oldSave.props.onClick();
  assert.equal(operations(f.rpc, 'runs.proposeResultRevision').length, 0);
  assert.equal(operations(f.rpc, 'runs.createResultRevision').length, 0);
  f.view.unmount();
  const writes = f.view.writeCount();
  read.reject(new Error('늦은 조회 실패'));
  await tick();
  assert.equal(f.view.writeCount(), writes);
  oldGenerate.props.onClick(); oldSave.props.onClick();
  assert.equal(operations(f.rpc, 'runs.createResultRevision').length, 0);
});

test('requests exclude simultaneous actions per target and ignore older completion tokens', () => {
  const requests = store();
  const scope = key('project', 'group', 'a');
  const original = requests.begin(scope, 'generate');
  assert.equal(requests.begin(scope, 'save'), undefined);
  assert.ok(requests.begin(key('project', 'group', 'b'), 'save'));
  requests.fail(scope, original, '생성 실패');
  const next = requests.begin(scope, 'save');
  requests.complete(scope, original, { proposal: proposal() });
  requests.fail(scope, original, '늦은 실패');
  assert.equal(requests.read(scope).pending, next);
  assert.equal(requests.read(scope).error, '');
});
