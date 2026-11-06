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
const output = mkdtempSync(join(tempRoot, 'tech-stack-entry-'));
const cleanup = () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); };
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  execFileSync(process.execPath, [resolve(dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig',
    '--strict', '--target', 'ES2022', '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/App.tsx', 'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);
const appPath = join(output, 'renderer/src/App.js');
const source = readFileSync(appPath, 'utf8');
const localRequire = createRequire(appPath);
const components = {};
runInNewContext(`${source}\nexports.ProjectSettingsDialog = ProjectSettingsDialog; exports.PlanningWorkbench = PlanningWorkbench;`, {
  exports: components,
  require: (name) => name === 'react' ? {
    ...localRequire(name), useRef: (current) => ({ current }), useState: (value) => [value, () => {}], useEffect() {}, useLayoutEffect() {},
  } : localRequire(name),
});
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
function text(tree) {
  if (typeof tree === 'string' || typeof tree === 'number') return String(tree);
  if (Array.isArray(tree)) return tree.map(text).join('');
  return tree ? text(tree.props?.children) : '';
}

test('project settings expose technology planning before environment settings without submitting a save', () => {
  let opened = 0, saved = 0;
  const tree = components.ProjectSettingsDialog({ project: { name: 'Empty project' }, runId: '', taskId: '',
    onOpenTechStack: () => opened++, onSaved: async () => saved++, onClose() {} });
  const sections = nodes(tree).filter((item) => item.type === 'section');
  assert.equal(sections[0].props['aria-labelledby'], 'project-tech-stack-title');
  assert.match(text(sections[0]), /계획 수정/);
  assert.match(text(sections[0]), /기획 자료.*선택 사항/);
  const button = nodes(sections[0]).find((item) => item.type === 'button');
  assert.equal(button.props.type, 'button');
  assert.equal(button.props.disabled, false);
  button.props.onClick();
  assert.equal(opened, 1);
  assert.equal(saved, 0);
});

async function navigation(changes = {}, hasDecision = true) {
  const frames = [], calls = [], headingCalls = [], queries = [];
  const heading = { scrollIntoView: () => headingCalls.push('scroll'), focus: () => headingCalls.push('focus') };
  const context = {
    react_1: { useCallback: (callback) => callback },
    PlanningMessageDisclosure_1: { scrollPlanningContentIntoView: () => headingCalls.push('scroll') },
    planningStart_1: localRequire('./planningStart.js'),
    techStackEntryPendingRef: { current: false }, selectedContextRef: { current: { projectName: 'empty' } },
    replaceRun: (name, run) => calls.push(['replace', name, run.id]), setSelectedRunId: (id) => calls.push(['select', id]),
    setNotice: () => {}, setError: (error) => calls.push(['error', error]), errorMessage: String,
    selectedProjectName: 'empty', selectedRunProjectName: 'empty', selectedRunId: 'group',
    selectedRun: { id: 'group', repository_intent: 'new_project' }, startProjectWork: (name) => calls.push(['new', name]),
    setProjectSettingsOpen: (open) => calls.push(['settings', open]), setHomeView: (view) => calls.push(['home', view]),
    setWorkbenchView: (view) => calls.push(['view', view]), setSideInspectorOpen: (open) => calls.push(['inspector', open]),
    window: { requestAnimationFrame: (callback) => frames.push(callback), orchestrator: { request: async () => [] } },
    document: { getElementById: (id) => { queries.push(id); return id === 'tech-stack-decision-title' && !hasDecision ? null : heading; } },
    ...changes,
  };
  const callback = source.match(/^    const openTechStackPlanning = [\s\S]*?(?=^    (?:const|let|return) )/m);
  assert.ok(callback);
  runInNewContext(`${callback[0]}\nthis.open = openTechStackPlanning;`, context);
  await context.open();
  frames.forEach((callback) => callback());
  return { calls, headingCalls, queries };
}

test('technology entry resumes the current greenfield group and focuses its decision without creating a new group', async () => {
  const result = await navigation();
  assert.deepEqual(result.calls, [['settings', false], ['home', 'work'], ['view', 'planning'], ['inspector', false]]);
  assert.deepEqual(result.queries, ['tech-stack-decision-title']);
  assert.deepEqual(result.headingCalls, ['scroll', 'focus']);
});

test('technology entry focuses planning when the existing group has no candidates yet', async () => {
  const result = await navigation({}, false);
  assert.deepEqual(result.queries, ['tech-stack-decision-title', 'planning-workbench-title']);
  assert.deepEqual(result.headingCalls, ['scroll', 'focus']);
});

test('missing, ordinary, or stale groups use the selected project new-work entry when no pending plan exists', async () => {
  for (const changes of [
    { selectedRun: undefined, selectedRunId: '' }, { selectedRun: { id: 'group', repository_intent: 'existing_structure' } },
    { selectedRunProjectName: 'other' }, { selectedRunId: 'different' },
  ]) {
    const result = await navigation(changes);
    assert.deepEqual(result.calls, [['settings', false], ['new', 'empty']]);
    assert.equal(result.queries.length, 0);
  }
  assert.equal((await navigation({ selectedProjectName: '' })).calls.length, 0);
});

test('technology entry finds a saved group even when no group is currently selected', async () => {
  const existing = { id: 'saved', stage: 'needs_clarification', repository_intent: 'new_project', greenfield_phase: 'questions_required', tasks: [] };
  const result = await navigation({ selectedRun: undefined, selectedRunId: '', window: {
    requestAnimationFrame() {}, orchestrator: { request: async (method) => method === 'runs.list'
      ? [{ id: 'saved', stage: 'needs_clarification', task_count: 0, created_at: '2026-10-08' }] : existing },
  } });
  assert.deepEqual(result.calls, [['settings', false], ['replace', 'empty', 'saved'], ['select', 'saved'],
    ['home', 'work'], ['view', 'planning'], ['inspector', false]]);
});

function planningStartHarness(request) {
  const calls = [], errors = [];
  const ignore = () => {};
  const context = {
    react_1: { useCallback: (callback) => callback }, planningStart_1: localRequire('./planningStart.js'),
    planningRequestDrafts_1: localRequire('./planningRequestDrafts.js'),
    planningStartPendingRef: { current: false }, selectedContextRef: { current: { projectName: 'empty' } },
    planningPreparationsRef: { current: new Set() }, selectedChatDraftRef: { current: { projectName:'empty',id:'' } },
    setChatDraftSelection(projectName,id=''){context.selectedChatDraftRef.current={projectName,id};},
    selectedProjectName: 'empty', projectCapabilities: { repository_maturity: { kind: 'docs_only' } },
    planningPath: '', planningMode: 'directed', planningRequest: 'same request', repositoryIntent: 'new_project',
    planningReasoning: '', planningEffortMode: 'balanced', planningProfileManual: false, selectedPlanningProfile: undefined,
    planningRequestDrafts: { current: new (localRequire('./planningRequestDrafts.js').PlanningRequestDrafts)() }, archiveScopeRef: { current: 'active' },
    replaceRun: (name, run) => calls.push(['replace', name, run.id]), setSelectedRunId: ignore, setWorkbenchView: ignore,
    setError: (error) => { if (error) errors.push(error); }, errorMessage: String,
    setBusyAction: ignore, setNotice: ignore, setPlanningStartElapsed: ignore, setPlanningPreparationMessage: ignore, setPlanningIndex: ignore, setPlanningStartErrors: ignore,
    loadProjects: async () => {}, loadRuns: async () => {},
    window: { setInterval: () => 1, clearInterval: ignore, orchestrator: { request: async (method, params) => {
      calls.push([method]); return request(method, params);
    } } },
  };
  const callback = source.match(/^    const startPlanning = [\s\S]*?(?=^    (?:const|let|return) )/m);
  assert.ok(callback);
  runInNewContext(`${callback[0]}\nthis.start = startPlanning;`, context);
  return { context, calls, errors, start: () => context.start() };
}

test('two starts before React rerenders prepare only one group', async () => {
  let release;
  const listing = new Promise((resolve) => { release = resolve; });
  const fixture = planningStartHarness(async (method) => method === 'runs.list' ? listing : { id: 'prepared', planning_messages: [] });
  const first = fixture.start();
  await fixture.start();
  assert.equal(fixture.calls.filter(([method]) => method === 'runs.list').length, 1);
  release([]);
  await first;
  assert.equal(fixture.calls.filter(([method]) => method === 'runs.preparePlanning').length, 1);
  assert.equal(fixture.calls.filter(([method]) => method === 'runs.runPlanning').length, 1);
  assert.equal(fixture.context.planningStartPendingRef.current, false);
  assert.deepEqual(fixture.errors, []);
});

test('separate chat drafts in one project prepare different runs and a late first result cannot replace the second chat', async () => {
  let releasePrepare,finishA,finishB,readyA,readyB;
  const prepareA=new Promise(resolve=>{releasePrepare=resolve;});
  const aiA=new Promise(resolve=>{finishA=resolve;}),aiB=new Promise(resolve=>{finishB=resolve;});
  const startedA=new Promise(resolve=>{readyA=resolve;}),startedB=new Promise(resolve=>{readyB=resolve;});
  let count=0;
  const fixture=planningStartHarness(async(method,params)=>{
    if(method==='runs.preparePlanning')return ++count===1?prepareA:{id:'run-b'};
    if(method==='runs.runPlanning'){if(params.runId==='run-a'){readyA();return aiA;}readyB();return aiB;}
    if(method==='runs.get')return{id:params.runId};
    assert.fail(`unexpected shared reuse: ${method}`);
  });
  const ctx=fixture.context,store=ctx.planningRequestDrafts.current,selections=[],replacements=[],listings=[];
  ctx.selectedContextRef.current={projectName:'empty',runId:''};
  ctx.setSelectedRunId=id=>selections.push(id);ctx.replaceRun=(project,run,select)=>replacements.push([run.id,select]);
  ctx.loadRuns=async options=>listings.push({...options});
  store.createChat('empty','draft-a');store.update('empty',{request:'A 요청'},'draft-a');
  ctx.selectedChatDraftRef.current={projectName:'empty',id:'draft-a'};
  const first=fixture.start();
  store.createChat('empty','draft-b');store.update('empty',{request:'B 요청',profileKey:'model-b'},'draft-b');
  ctx.selectedChatDraftRef.current={projectName:'empty',id:'draft-b'};
  releasePrepare({id:'run-a'});await startedA;
  assert.deepEqual(selections,[]);assert.equal(store.load('empty','','','draft-b').request,'B 요청');
  assert.equal(ctx.planningPreparationsRef.current.has('empty'),false);
  ctx.planningRequest='B 요청';const second=fixture.start();await startedB;
  assert.deepEqual(selections,['run-b']);assert.equal(count,2);
  finishA({id:'run-a'});await first;
  assert.deepEqual(selections,['run-b']);assert.equal(listings[0].selectFirst,false);
  assert.equal(replacements.filter(([id])=>id==='run-a').every(([,select])=>!select),true);
  finishB({id:'run-b'});await second;
  assert.equal(listings.at(-1).selectFirst,true);assert.equal(store.chatSnapshot().length,0);
});

test('a late preparation failure keeps its original chat draft and never writes an error into another draft', async () => {
  let rejectPrepare;
  const pending=new Promise((resolve,reject)=>{rejectPrepare=reject;});
  const fixture=planningStartHarness(async method=>method==='runs.preparePlanning'?pending:assert.fail(method));
  const ctx=fixture.context,store=ctx.planningRequestDrafts.current,errors={};
  ctx.selectedContextRef.current={projectName:'empty',runId:''};ctx.setPlanningStartErrors=update=>Object.assign(errors,update(errors));
  store.createChat('empty','a');store.update('empty',{request:'보존할 A'},'a');
  ctx.selectedChatDraftRef.current={projectName:'empty',id:'a'};const first=fixture.start();
  store.createChat('empty','b');ctx.selectedChatDraftRef.current={projectName:'empty',id:'b'};
  rejectPrepare(Error('prepare failed'));await first;
  assert.equal(store.load('empty','','','a').request,'보존할 A');assert.equal(store.chatSnapshot().length,2);
  assert.match(errors[JSON.stringify(['empty','a'])],/prepare failed/);assert.equal(errors[JSON.stringify(['empty','b'])],undefined);
  assert.equal(fixture.errors.length,0);assert.equal(ctx.planningPreparationsRef.current.size,0);
});

test('retry after a lost preparation response recovers the saved group instead of creating another', async () => {
  let saved = false;
  const fixture = planningStartHarness(async (method) => {
    if (method === 'runs.list') return saved ? [{ id: 'saved', created_at: '2026-10-08', task_count: 0, stage: 'needs_clarification' }] : [];
    if (method === 'runs.preparePlanning') { saved = true; throw new Error('response lost'); }
    if (method === 'runs.get') return { id: 'saved', stage: 'needs_clarification', repository_intent: 'new_project', tasks: [],
      greenfield_phase: 'questions_required', planning_mode: 'directed', planning_request: 'same request', spec_path: '' };
    assert.fail(`unexpected request ${method}`);
  });
  await fixture.start();
  await fixture.start();
  assert.equal(fixture.calls.filter(([method]) => method === 'runs.preparePlanning').length, 1);
  assert.ok(fixture.calls.some(([action, , id]) => action === 'replace' && id === 'saved'));
  assert.match(fixture.errors[0], /response lost/);
  assert.equal(fixture.context.planningStartPendingRef.current, false);
});

test('a saved preparation without candidates continues Planning on its existing group', async () => {
  const fixture = planningStartHarness(async (method) => {
    if (method === 'runs.list') return [{ id: 'prepared', created_at: '2026-10-08', task_count: 0, stage: 'reviewed' }];
    if (method === 'runs.get') return { id: 'prepared', stage: 'reviewed', repository_intent: 'new_project', tasks: [],
      greenfield_phase: 'stack_decision_required', planning_mode: 'directed', planning_request: 'same request', spec_path: '' };
    if (method === 'runs.runPlanning') return { id: 'prepared' };
    assert.fail(`unexpected request ${method}`);
  });
  await fixture.start();
  assert.equal(fixture.calls.filter(([method]) => method === 'runs.preparePlanning').length, 0);
  assert.equal(fixture.calls.filter(([method]) => method === 'runs.runPlanning').length, 1);
  assert.deepEqual(fixture.errors, []);
});

test('prepared-group continuation ignores a second click while its request is pending', async () => {
  let finish;
  const pending = new Promise((resolve) => { finish = resolve; });
  const fixture = planningStartHarness(async () => pending);
  fixture.context.selectedRun = { id: 'prepared', stage: 'reviewed' };
  fixture.context.loadRunDetail = async () => {};
  const callback = source.match(/^    const runPreparedRevisionPlanning = [\s\S]*?(?=^    (?:const|let|return) )/m);
  assert.ok(callback);
  runInNewContext(`${callback[0]}\nthis.continuePlanning = runPreparedRevisionPlanning;`, fixture.context);
  const first = fixture.context.continuePlanning();
  await fixture.context.continuePlanning();
  assert.equal(fixture.calls.filter(([method]) => method === 'runs.runPlanning').length, 1);
  finish({ id: 'prepared' });
  await first;
  assert.equal(fixture.context.planningStartPendingRef.current, false);
  assert.deepEqual(fixture.errors, []);
});

test('lookup failure is visible and does not create a replacement group', async () => {
  const fixture = planningStartHarness(async () => { throw new Error('lookup unavailable'); });
  await fixture.start();
  assert.equal(fixture.calls.filter(([method]) => method === 'runs.preparePlanning').length, 0);
  assert.match(fixture.errors[0], /lookup unavailable/);
  assert.equal(fixture.context.planningStartPendingRef.current, false);
});

test('late preparation failure preserves its project error without overwriting another project or draft', async () => {
  let reject;
  const pending = new Promise((_, fail) => { reject = fail; });
  const fixture = planningStartHarness(async (method) => method === 'runs.list' ? [] : pending);
  let errorsByProject = {};
  fixture.context.setPlanningStartErrors = update => { errorsByProject = update(errorsByProject); };
  let draftUpdates = 0;
  fixture.context.planningRequestDrafts.current.update = () => draftUpdates++;
  const selections = [];
  fixture.context.setSelectedRunId = id => selections.push(id);
  const first = fixture.start();
  for (let i=0;i<5 && !fixture.calls.some(([method])=>method==='runs.preparePlanning');i++) await Promise.resolve();
  fixture.context.selectedContextRef.current = {projectName:'other',runId:'other-group'};
  reject(new Error('original project source failure'));
  await first;
  assert.deepEqual(fixture.errors, []);
  assert.match(errorsByProject.empty, /original project source failure/);
  assert.equal(errorsByProject.other, undefined);
  assert.equal(draftUpdates,0);
  assert.deepEqual(selections,[]);
});

test('a prepared group is exposed before its AI response and late success cannot redirect a new selection', async () => {
  let finish, started;
  const starting = new Promise(resolve=>{started=resolve;});
  const pending = new Promise(resolve=>{finish=resolve;});
  const fixture = planningStartHarness(async (method) => {
    if(method==='runs.list') return [];
    if(method==='runs.runPlanning') {started();return pending;}
    return {id:'prepared'};
  });
  const selections=[];
  fixture.context.setSelectedRunId = id=>selections.push(id);
  const first=fixture.start();
  await starting;
  assert.deepEqual(selections,['prepared']);
  assert.equal(fixture.context.planningPreparationsRef.current.has('empty'),false,'the AI turn no longer holds the new-chat preparation slot');
  fixture.context.selectedContextRef.current={projectName:'other',runId:'different'};
  finish({id:'prepared'}); await first;
  assert.deepEqual(selections,['prepared']);
  assert.equal(fixture.context.planningStartPendingRef.current,false);
});


function questionWorkbench(changes = {}, runChanges = {}) {
  const calls = [];
  const run = { id: 'question-group', summary: '빈 프로젝트', stage: 'needs_clarification', repository_intent: 'new_project',
    greenfield_phase: 'questions_required', tasks: [], events: [], planning_messages: [], planning_follow_up_requests: [],
    planning_questions: ['어떤 운영체제인가요?'],
    tech_stack_decisions: [{ decision_id: 'decision', revision: 3, status: 'questions_required', options: [], selected_option_id: '' }],
    ...runChanges };
  const props = { project: { name: 'empty' }, run, path: '', mode: 'directed', request: '',
    profiles: [{ agent_id: 'codex', model: 'test', provider_id: 'codex' }], providerStatuses: [{ id: 'codex', available: true }],
    selectedProfileKey: 'codex\u001ftest', reasoningOptions: [], reasoning: '', effortMode: 'balanced', profileManual: false,
    message: '작성 중인 답변', messageViews: {}, indexElapsed: 0, planningElapsed: 0, preparationMessage: '', busyAction: '',
    onMessageChange: () => calls.push('change'), onSend: () => calls.push('send'), onApply: () => calls.push('apply'),
    onConfirmTechStack: () => calls.push('confirm'), onAnswerTechnology: (answer) => calls.push(['answer', answer]), ...changes };
  const tree = components.PlanningWorkbench(props);
  const panel = nodes(tree).find((node) => node.type?.name === 'GreenfieldFlowPanel');
  const input = nodes(tree).find((node) => node.type === 'textarea' && node.props.value === props.message);
  input.props.ref.current = { scrollIntoView: () => calls.push('scroll'), focus: () => calls.push('focus') };
  return { tree, panel, input, calls };
}

test('guided question card receives the saved question and existing answer without sending on render', () => {
  const current = questionWorkbench();
  assert.deepEqual(Array.from(current.panel.props.run.planning_questions), ['어떤 운영체제인가요?']);
  assert.equal(current.panel.props.available, true);
  assert.equal(current.panel.props.answer, '작성 중인 답변');
  assert.deepEqual(current.calls, []);
  current.panel.props.onAnswer('작성 중인 답변');
  assert.deepEqual(current.calls, [['answer', '작성 중인 답변']]);
});

test('guided flow receives the backend confirmation decision without reinterpreting questions', () => {
  assert.equal(questionWorkbench({}, { tech_stack_confirmation_allowed: true }).panel.props.run.tech_stack_confirmation_allowed, true);
  assert.equal(questionWorkbench().panel.props.run.tech_stack_confirmation_allowed, undefined);
});

test('a prepared initial group exposes a continuation action without requiring a revision source', () => {
  let continued = 0;
  const current = questionWorkbench({ onRunPreparedRevision: () => continued++ }, { stage: 'reviewed', tech_stack_decisions: [] });
  const section = nodes(current.tree).find((node) => node.props?.className === 'revision-planning-ready');
  assert.match(text(section), /기획 이어 시작/);
  nodes(section).find((node) => node.type === 'button').props.onClick();
  assert.equal(continued, 1);
});

test('question recovery preserves busy, remote Planning, unavailable model and read-only stage guards', () => {
  for (const [props, run] of [
    [{ busyAction: 'runs.sendPlanningMessage' }, {}], [{}, { active_step: 'planning' }],
    [{ profiles: [] }, { planning_provider_id: 'claude' }], [{}, { stage: 'verified' }],
  ]) {
    const current = questionWorkbench(props, run);
    assert.deepEqual(current.calls, []);
    assert.ok(current.panel.props.busy || current.panel.props.active || !current.panel.props.available);
  }
});


test('guided actions block a second click and keep another group draft when the response arrives late', async () => {
  let finish;
  const pending = new Promise((resolve) => { finish = resolve; });
  const calls = [], notices = [];
  let message = '작성 중인 답변';
  const ignore = () => {};
  const context = {
    react_1: { useCallback: (fn) => fn }, planDirty: false, selectedProjectName: 'empty', selectedRun: { id: 'same' },
    greenfieldActionPendingRef: { current: false }, selectedContextRef: { current: { projectName: 'empty', runId: 'same' } },
    planningMessage: message, selectedPlanningProfile: undefined, planningReasoning: '', planningProfileManual: false,
    planningRequestDrafts_1: localRequire('./planningRequestDrafts.js'),
    greenfieldFlow_1: { greenfieldRetry: () => undefined },
    greenfieldActions_1: { requestGreenfieldPlan: async (request, answer) => { calls.push(answer); return pending; } },
    runExecutionControl_1: { runContextMatches: (a, b, c, d) => a === c && b === d },
    replaceRun: ignore, setBusyAction: ignore, setError: ignore, setNotice: (value) => notices.push(value), setPlanningStartElapsed: ignore,
    setPlanningMessage: (value) => { message = typeof value === 'function' ? value(message) : value; },
    requestRunAction: ignore, crypto: { randomUUID: () => 'one-request' },
    window: { setInterval: () => 1, clearInterval: ignore, orchestrator: { request: ignore } },
  };
  const callback = source.match(/^    const runGreenfieldAction = [\s\S]*?(?=^    (?:const|let|return) )/m);
  assert.ok(callback);
  runInNewContext(`${callback[0]}\nthis.run = runGreenfieldAction;`, context);
  const first = context.run('answer', message);
  await context.run('answer', message);
  assert.equal(calls.length, 1);
  context.selectedContextRef.current = { projectName: 'other', runId: 'other' };
  message = '다른 그룹 초안';
  finish({ id: 'same', planning_apply_requests: [{ status: 'succeeded' }] });
  await first;
  assert.equal(message, '다른 그룹 초안');
  assert.deepEqual(notices, ['']);
  assert.equal(context.greenfieldActionPendingRef.current, false);

  let finishPlan, finishPoll, tick;
  const planResult = new Promise((resolve) => { finishPlan = resolve; });
  const pollResult = new Promise((resolve) => { finishPoll = resolve; });
  const published = [];
  context.selectedContextRef.current = { projectName: 'empty', runId: 'same' };
  context.replaceRun = (_, value) => published.push(value.status);
  context.window.setInterval = (callback) => { tick = callback; return 2; };
  context.window.orchestrator.request = () => pollResult;
  context.greenfieldActions_1.requestGreenfieldPlan = async (request) => {
    const result = await planResult;
    request.onUpdate(result);
    return result;
  };
  const next = context.run('answer', 'same answer');
  tick();
  finishPlan({ id: 'same', status: 'finished', planning_apply_requests: [{ status: 'succeeded' }] });
  await next;
  finishPoll({ id: 'same', status: 'older applying state' });
  await pollResult;
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(published, ['finished'], 'a late status response cannot replace the final operation result');
});


test('technology decisions hide generic apply while feature planning keeps its editing action', () => {
  const initial = questionWorkbench();
  assert.ok(!nodes(initial.tree).some((node) => node.type === 'button' && /기능 계획 갱신|답변으로 후보 갱신/.test(text(node))));
  const features = questionWorkbench({}, { stage: 'planned', greenfield_phase: 'feature_plan_ready', bootstrap_spec: {},
    planning_conversation_revision: 2, planning_applied_conversation_revision: 1 });
  const apply = nodes(features.tree).find((node) => node.type === 'button' && text(node) === '기능 계획 갱신');
  assert.ok(apply); assert.equal(apply.props.disabled, false);
  apply.props.onClick();
  assert.deepEqual(features.calls, ['apply']);
});
