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
const output = mkdtempSync(join(tempRoot, 'preview-entry-'));
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
function chatContext(context) {
  return Object.assign(context, { busyAction: '', executionAction: '', nextExecutionProfileDirty: false,
    runExecutionControl_1: localRequire('./runExecutionControl.js'), chatTaskRecovery_1: localRequire('./chatTaskRecovery.js'), chatExecutionControl_1: localRequire('./chatExecutionControl.js') });
}
const components = {};
runInNewContext(`${source}\nexports.PlanningWorkbench = PlanningWorkbench; exports.WorkDetailsNavigation = WorkDetailsNavigation;`, {
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
function workbench(runChanges = {}, changes = {}) {
  const calls = [];
  const run = { id: 'group', summary: '실패 작업 수정', stage: 'failed', failed_step: 'agent_execution',
    repository_intent: 'existing_structure', tasks: [], events: [], planning_questions: [],
    planning_messages: [{ role: 'assistant', text: '기존 조건을 유지하고 실패한 테스트를 수정합니다.', at: '2026-10-08T00:00:00Z' }],
    planning_follow_up_requests: [], planning_conversation_revision: 2, planning_applied_conversation_revision: 2,
    ...runChanges };
  const props = { project: { name: 'project' }, run, path: '', mode: 'directed', request: '',
    profiles: [{ agent_id: 'codex', model: 'test', provider_id: 'codex' }], providerStatuses: [{ id: 'codex', available: true }],
    selectedProfileKey: 'codex\u001ftest', reasoningOptions: [], reasoning: '', effortMode: 'balanced', profileManual: false,
    message: 'Task 에 반영해줘', messageViews: {}, indexElapsed: 0, planningElapsed: 0, preparationMessage: '', busyAction: '',
    onMessageChange: () => calls.push('change'), onSend: () => calls.push('send'), onApply: () => calls.push('preview'), ...changes };
  const tree = components.PlanningWorkbench(props);
  const preview = nodes(tree).find((node) => node.type === 'button'
    && ['작업에 반영', '반영 완료', '반영 상태 확인', '다시 반영'].includes(text(node)));
  return { tree, preview, calls, props };
}

test('chat first restores a configured Claude selection and archived conversations allow messages', () => {
  const changes = { chatFirst: true, profiles: [{ provider_id: 'claude', agent_id: 'claude', model: 'sonnet' }],
    selectedProfileKey: 'claude\u001fsonnet', providerStatuses: [{ id: 'claude', available: true }] };
  const result = workbench({ planning_provider_id: 'claude', planning_agent_id: 'claude', planning_model: 'sonnet',
    planning_applied_conversation_revision: 0 }, changes);
  assert.equal(result.preview, undefined);
  assert.equal(nodes(result.tree).filter(node => node.props?.className === 'provider-selection-warning').length, 0);
  const archived = workbench({ archive: { status: 'archived' } }, changes);
  const input = nodes(archived.tree).find(node => node.type === 'textarea');
  assert.equal(input.props.disabled, false); assert.match(input.props.placeholder, /다음 작업을 논의/);
  const models=nodes(archived.tree).find(node=>node.props?.className==='chat-model-controls');
  assert.equal(nodes(models).find(node=>node.type==='select').props.disabled,false);
  assert.equal(archived.preview, undefined);
});

test('chat-first ordinary replies have no apply shortcuts and result actions remain in work details', () => {
  for (const stage of ['planned', 'executing', 'failed', 'ready_to_merge', 'verified', 'work_branch_pushed', 'merged', 'pushed', 'deployed']) {
    const current = workbench({stage, planning_applied_conversation_revision:0}, {chatFirst:true});
    assert.equal(current.preview, undefined, stage);
    assert.equal(nodes(current.tree).some(node=>node.type==='button' && text(node)==='수정안 확인'),false,stage);
    assert.deepEqual(current.calls,[]);
  }
  const current = workbench({stage:'planned',repository_intent:'new_project',greenfield_phase:'feature_plan_ready',
    bootstrap_spec:{},planning_applied_conversation_revision:0}, {chatFirst:true});
  assert.ok(nodes(current.tree).some(node=>node.type==='button'&&text(node)==='기능 계획 갱신'),
    'the explicit new-project planning step remains available');
});

test('work navigation stays ordered while result details use a single page', () => {
  const cases = [
    undefined,
    {stage:'executing',tasks:[{status:'running'}]},
    {stage:'planned',tasks:[{status:'pending'}]},
    {stage:'failed',tasks:[{status:'failed'},{status:'completed'}]},
    {stage:'pushed',tasks:[{status:'merged'}]},
    {stage:'pushed',tasks:[],archive:{}},
  ];
  for(const run of cases) for(const view of ['tasks','operations','results','planning']) {
    const opened=[];
    const before=JSON.stringify(run);
    const tree=components.WorkDetailsNavigation({view,run,onChange:value=>opened.push(value)});
    if(view==='results') {
      const buttons=nodes(tree).filter(node=>node.type==='button');
      assert.deepEqual(buttons.map(text),['작업으로 돌아가기']);
      assert.equal(buttons[0].props.disabled,!run);
      assert.deepEqual(opened,[],'result navigation never starts work');
      if(!buttons[0].props.disabled)buttons[0].props.onClick();
      assert.deepEqual(opened,run?['tasks']:[],'returns to the same run task view');
      assert.equal(JSON.stringify(run),before,'returning must not change saved results');
      continue;
    }
    if(['tasks','operations'].includes(view) && run?.stage==='planned' && !run.archive) {
      assert.equal(tree,null);
      assert.deepEqual(opened,[]);
      assert.equal(JSON.stringify(run),before);
      continue;
    }
    const buttons=nodes(tree).filter(node=>node.type==='button');
    const canPrepare=!run || run.stage==='planned';
    assert.deepEqual(buttons.map(text),['작업','변경 기록',...(canPrepare ? ['실행 전 설정'] : [])]);
    assert.equal(tree.props['aria-label'],'작업 상세 보기');
    assert.equal(buttons[0].props['aria-current'],['tasks','operations'].includes(view)?'page':undefined);
    assert.equal(buttons[1].props['aria-current'],view==='results'?'page':undefined);
    if(canPrepare)assert.equal(buttons[2].props['aria-current'],view==='planning'?'page':undefined);
    assert.deepEqual(opened,[], 'navigation rendering never starts work');
    buttons.filter(button=>!button.props.disabled).forEach(button=>button.props.onClick());
    assert.deepEqual(opened,buttons.flatMap((button,index)=>button.props.disabled?[]:[['tasks','results','planning'][index]]));
    assert.equal(JSON.stringify(run),before,'navigation must not change the saved run');
  }
});

test('change records stay discoverable before completion and become available when recorded results arrive', () => {
  for(const [run,disabled] of [[undefined,true],[{stage:'executing',tasks:[{status:'running'}]},true],
    [{stage:'executing',tasks:[{status:'completed'}]},false],
    [{stage:'pushed',tasks:[],group_result_history:[{verification_attempt_id:'recorded'}]},false]]) {
    const tree=components.WorkDetailsNavigation({view:'tasks',run,onChange:()=>assert.fail('rendering cannot execute requests')});
    const record=nodes(tree).find(node=>node.type==='button'&&text(node)==='변경 기록');
    assert.equal(record.props.disabled,disabled);
    assert.equal(record.props.title,disabled?'완료된 작업의 변경 기록이 여기에 표시됩니다.':undefined);
  }
});

test('the chat composer owns one model/settings control and an accessible send action without changing draft semantics', () => {
  const selected=[],settings=[];
  const current=workbench({}, {chatFirst:true,message:'지금 입력한 질문',onProfileChange:value=>selected.push(value),
    onOpenPlanningSettings:()=>settings.push(true)});
  const composer=nodes(current.tree).find(node=>node.props.className==='chat-composer');
  const models=nodes(composer).filter(node=>node.props.className==='chat-model-controls');
  assert.equal(models.length,1);
  const popup=nodes(models[0]).find(node=>node.type==='details'&&node.props.className==='chat-model-settings');
  assert.equal(popup.props['data-dismiss-on-outside'],true);
  assert.equal(nodes(popup).filter(node=>node.type==='button'&&node.props['data-dismiss-menu-action']).length,2);
  assert.equal(nodes(current.tree).filter(node=>node.props.className==='chat-model-controls').length,1);
  const send=nodes(composer).find(node=>node.props.className?.includes('chat-composer__send'));
  assert.equal(text(send),'전송');assert.equal(nodes(send).find(node=>node.type==='span').props.className,'sr-only');
  assert.match(send.props.title,/Ctrl\/Cmd\+Enter/);assert.equal(send.props.disabled,false);
  nodes(models[0]).find(node=>node.type==='select').props.onChange({target:{value:'another-profile'}});
  nodes(models[0]).find(node=>node.type==='button'&&text(node)==='기획 설정 보기').props.onClick();
  assert.deepEqual(selected,['another-profile']);assert.deepEqual(settings,[true]);assert.deepEqual(current.calls,[]);
  const input=nodes(composer).find(node=>node.type==='textarea');assert.equal(input.props.value,'지금 입력한 질문');
  input.props.onKeyDown({key:'Enter',ctrlKey:true,preventDefault(){}});assert.deepEqual(current.calls,['send']);
  const busy=workbench({}, {chatFirst:true,busyAction:'runs.sendPlanningMessage'});
  const pending=nodes(busy.tree).find(node=>node.props.className?.includes('chat-composer__send'));
  assert.equal(text(pending),'전송 중');assert.equal(pending.props.disabled,true);
  pending.props.onClick();assert.deepEqual(busy.calls,[]);
});

test('a new chat uses the same composer controls and still starts through planning readiness', () => {
  const started=[];
  const {props}=workbench({}, {chatFirst:true});
  const tree=components.PlanningWorkbench({...props,run:undefined,request:'로그인 오류 수정',
    capabilities:{repository_maturity:{kind:'existing_code',evidence:[],ignored_roots:[],detected_application_roots:[],
      diagnostics:[],inspected_file_count:0,truncated:false}},onStart:()=>started.push(true)});
  const composer=nodes(tree).find(node=>node.props.className==='chat-composer chat-composer--new');
  assert.ok(composer);assert.equal(nodes(tree).filter(node=>node.props.className==='chat-model-controls').length,1);
  const start=nodes(composer).find(node=>node.props.className?.includes('chat-composer__send'));
  assert.equal(text(start),'계획 만들기');assert.equal(start.props.disabled,false);
  assert.deepEqual(started,[]);start.props.onClick();assert.deepEqual(started,[true]);
});

test('disconnected chat selection requires reselection and cannot send through another available AI', () => {
  for (const profiles of [[], [{ agent_id: 'codex', model: 'test', provider_id: 'codex' }]]) {
    const current = workbench({}, { chatFirst: true, profiles, selectedProfileKey: 'claude\u001fsonnet' });
    const input = nodes(current.tree).find(node => node.type === 'textarea');
    const send = nodes(current.tree).find(node => node.type === 'button' && text(node) === '전송');
    assert.equal(input.props.disabled, true);
    assert.equal(send.props.disabled, true);
    send.props.onClick();
    input.props.onKeyDown({ key: 'Enter', ctrlKey: true, preventDefault() {} });
    assert.deepEqual(current.calls, []);
    assert.match(text(current.tree), /모델을 다시 선택해 주세요/);
    const models = nodes(current.tree).find(node => node.props?.className === 'chat-model-controls');
    assert.ok(!nodes(models).some(node => node.type === 'option' && text(node).includes('Claude')));
    if (!profiles.length) assert.match(text(models), /연결된 AI 없음/);
  }
});

test('latest AI answer opens preview status and keeps unsent input without duplicate composer actions', () => {
  for (const status of [undefined, 'queued', 'applying', 'failed', 'succeeded']) {
    const current = workbench({ planning_conversation_revision: 3, planning_apply_requests: status ? [{ status }] : [] });
    assert.ok(current.preview);
    const assistant = nodes(current.tree).find((node) => node.type === 'article' && node.props.className === 'chat-message chat-message--assistant');
    assert.ok(nodes(assistant).includes(current.preview));
    const composer = nodes(current.tree).find((node) => node.props?.className === 'chat-composer');
    assert.ok(!nodes(composer).includes(current.preview));
    assert.ok(!nodes(current.tree).some((node) => node.type === 'button' && text(node) === '변경 미리보기'));
    assert.equal(current.preview.props.disabled, false, status);
    current.preview.props.onClick();
    assert.deepEqual(current.calls, ['preview']);
    assert.equal(nodes(current.tree).find((node) => node.type === 'textarea' && node.props.value === current.props.message)
      .props.value, 'Task 에 반영해줘', 'opening the saved conversation preview preserves unsent input');
  }
});

test('AI response in progress, local requests and unsupported stages keep previous answers blocked', () => {
  assert.equal(workbench({ active_step: 'planning' }).preview.props.disabled, true);
  assert.equal(workbench({}, { busyAction: 'runs.sendPlanningMessage' }).preview.props.disabled, true);
  assert.equal(workbench({ stage: 'received' }).preview.props.disabled, true);
  const result = workbench({ stage: 'merged' });
  const resultAction = nodes(result.tree).find((node) => node.type === 'button' && text(node) === '수정안 확인');
  assert.equal(resultAction.props.disabled, false, 'saved results direct changes to result review');
  assert.equal(workbench({ planning_provider_id: 'claude' }).preview.props.disabled, true);
  const applying = workbench({ active_step: 'planning', planning_apply_requests: [{ status: 'applying', conversation_revision: 2 }] });
  assert.equal(text(applying.preview), '반영 상태 확인');
  assert.equal(applying.preview.props.disabled, false, 'saved apply activity still permits read-only status inspection');
  applying.preview.props.onClick();
  assert.deepEqual(applying.calls, ['preview']);
});

test('completed conversation stays disabled after reload and a new answer enables its own action', () => {
  const applied = workbench({ planning_conversation_revision: 2,
    planning_apply_requests: [{ status: 'succeeded', conversation_revision: 2 }] });
  assert.equal(text(applied.preview), '반영 완료');
  assert.equal(applied.preview.props.disabled, true);
  applied.preview.props.onClick();
  assert.deepEqual(applied.calls, []);
  const messages = [...applied.props.run.planning_messages,
    { role: 'user', text: '이어서 수정해줘', at: 'later-user' },
    { role: 'assistant', text: '새 변경입니다.', at: 'later-assistant' }];
  const next = workbench({ planning_conversation_revision: 4, planning_messages: messages,
    planning_apply_requests: [{ status: 'succeeded', conversation_revision: 2 }] });
  const actions = nodes(next.tree).filter((node) => node.props?.className === 'chat-message__actions');
  assert.equal(actions.length, 1);
  assert.equal(text(next.preview), '작업에 반영');
  assert.equal(next.preview.props.disabled, false);
  next.preview.props.onClick();
  assert.deepEqual(next.calls, ['preview']);
});

test('active execution blocks new answer apply and failed retries while pending request status stays readable', () => {
  const activity = [
    ...['running', 'reviewing', 'revising'].map(status => ({ tasks: [{ id: 'active', status, action_results: [] }] })),
    { tasks: [{ id: 'verify', status: 'pending', active_action: 'verify', action_results: [] }] },
    { active_step: 'agent_execution' }, { active_step: 'verify' },
    { execution_control: { situation: 'running' } }, { execution_control: { situation: 'preparing' } },
  ];
  for (const changes of activity) {
    for (const status of [undefined, 'failed']) {
      const current = workbench({ stage: 'executing', planning_conversation_revision: 3, ...changes,
        planning_apply_requests: status ? [{ status }] : [] });
      assert.equal(current.preview.props.disabled, true);
      assert.match(current.preview.props.title, /현재 작업이 끝나면/);
      current.preview.props.onClick(); assert.deepEqual(current.calls, []);
    }
    for (const status of ['queued', 'applying']) {
      const pending = workbench({ stage: 'executing', planning_conversation_revision: 3, ...changes,
        planning_apply_requests: [{ status }] });
      assert.equal(text(pending.preview), '반영 상태 확인');assert.equal(pending.preview.props.disabled, false);
      pending.preview.props.onClick();assert.deepEqual(pending.calls, ['preview']);
    }
  }
  const completed = workbench({ stage: 'planned', planning_conversation_revision: 3,
    tasks: [{ id: 'done', status: 'completed', action_results: [] }], execution_control: { situation: 'ready' } });
  assert.equal(completed.preview.props.disabled, false);
});

test('the shared existing-project apply callback also blocks execution without opening preview or making requests', async () => {
  const callback = source.match(/^    const applyPlanningConversation = [\s\S]*?(?=^    const runGreenfieldAction =)/m);
  assert.ok(callback);
  const calls = [];
  const context = { react_1: { useCallback: fn => fn }, planningPreviewRequest_1: localRequire('./planningPreviewRequest.js'),
    selectedProjectName: 'project', selectedRun: { id: 'group', repository_intent: 'existing_structure', active_step: 'agent_execution', tasks: [] },
    planDirty: false, replaceRun() {}, sendPlanningMessage: () => assert.fail('existing execution cannot create initial Tasks'), setNotice: text => calls.push(['notice', text]),
    setPlanningPreviewTarget: target => calls.push(['preview', target.runId]),
    window: { orchestrator: { request: () => assert.fail('entry cannot request work') } } };
  context.beginTaskPlanning = () => () => {};
  runInNewContext(`${callback[0]}\nthis.apply = applyPlanningConversation;`, context);
  await context.apply();assert.equal(calls.length, 1);assert.match(calls[0][1], /작업 실행 중/);
  calls.length = 0;context.selectedRun.planning_apply_requests = [{ status: 'queued' }];
  await context.apply();assert.deepEqual(calls, [['preview', 'group']]);
  calls.length = 0;context.selectedRun.planning_apply_requests = [];context.selectedRun.active_step = null;
  await context.apply();assert.deepEqual(calls, [['preview', 'group']]);
});

test('initial Task creation uses the existing chat pipeline once and retains unsaved plan edits', async () => {
  const callback=source.match(/^    const applyPlanningConversation = [\s\S]*?(?=^    const runGreenfieldAction =)/m);
  const sent=[],errors=[];
  const context={react_1:{useCallback:fn=>fn},planningPreviewRequest_1:localRequire('./planningPreviewRequest.js'),
    selectedProjectName:'project',selectedRun:{id:'group',stage:'needs_clarification',repository_intent:'existing_structure',tasks:[]},
    planDirty:false,beginTaskPlanning(){},replaceRun(){},sendPlanningMessage:async text=>sent.push(text),setError:text=>errors.push(text),
    setPlanningPreviewTarget:()=>assert.fail('first Tasks do not edit an existing plan preview')};
  runInNewContext(`${callback[0]}\nthis.apply=applyPlanningConversation;`,context);
  await context.apply();assert.deepEqual(sent,['논의한 내용으로 Task 만들어줘']);
  context.planDirty=true;await context.apply();assert.equal(sent.length,1);assert.match(errors.at(-1),/미저장 계획/);
});

test('waiting for a new answer blocks old answer and failed or queued applies are never called complete', () => {
  const waiting = workbench({ planning_messages: [
    { role: 'assistant', text: '이전 답변', at: 'a' }, { role: 'user', text: '새 질문', at: 'b' },
  ] });
  assert.equal(waiting.preview.props.disabled, true);
  waiting.preview.props.onClick();
  assert.deepEqual(waiting.calls, []);
  for (const status of ['failed', 'queued', 'applying']) {
    const current = workbench({ planning_conversation_revision: 2, planning_apply_requests: [{ status, conversation_revision: 2 }] });
    assert.notEqual(text(current.preview), '반영 완료');
    assert.equal(current.preview.props.disabled, false);
  }
  const none = workbench({ planning_messages: [] });
  assert.equal(none.preview, undefined);
});

test('new project apply keeps its revision, pending operation and unsaved plan checks', () => {
  for (const [runChanges, changes] of [
    [{}, {}], [{ planning_conversation_revision: 3, planning_apply_requests: [{ status: 'queued' }] }, {}],
    [{ planning_conversation_revision: 3, active_step: 'planning' }, {}],
    [{ planning_conversation_revision: 3 }, { planDirty: true }],
  ]) {
    const current = workbench({ stage: 'planned', repository_intent: 'new_project', greenfield_phase: 'feature_plan_ready',
      bootstrap_spec: {}, ...runChanges }, changes);
    const apply = nodes(current.tree).find((node) => node.type === 'button'
      && /^(?:기능 계획 갱신|반영 예약|작업에 반영 중…)$/.test(text(node)));
    assert.ok(apply);
    assert.equal(apply.props.disabled, true);
    assert.deepEqual(current.calls, []);
  }
});

test('sending the reported Task apply command opens the same preview without chat RPC or pending messages', async () => {
  const calls = [];
  const context = {
    react_1: { useCallback: (callback) => callback },
    planningPreviewRequest_1: localRequire('./planningPreviewRequest.js'),
    selectedProjectName: 'project', selectedRun: { id: 'group', repository_intent: 'existing_structure', tasks: [{ id: 'failed-task', status: 'failed' }] },
    TaskStatusOverview_1: localRequire('./TaskStatusOverview.js'), taskDrafts: [], planDirty: false,
    planningMessage: 'Task 에 반영해줘', planningReasoning: '', planningProfileManual: false,
    directionChangeDrafts: undefined,
    recoverStaleRunLock() {}, replaceRun() {}, selectedPlanningProfile: undefined,
    setPlanningPreviewTarget: (target) => calls.push(['preview', target.projectName, target.runId, target.taskId]),
    setPlanningMessage: (value) => calls.push(['input', value]), setError() {}, setNotice() {},
    window: { orchestrator: { request: () => { throw new Error('chat RPC must not start'); } } },
    setPendingPlanningMessage: () => { throw new Error('pending chat must not start'); },
  };
  const callback = source.match(/^    const sendPlanningMessage = [\s\S]*?(?=^    const applyPlanningConversation =)/m);
  assert.ok(callback);
  context.beginTaskPlanning = () => () => {};
  runInNewContext(`${callback[0]}\nthis.send = sendPlanningMessage;`, chatContext(context));
  await context.send();
  assert.deepEqual(calls, [['preview', 'project', 'group', undefined], ['input', '']]);
  calls.length = 0;
  await context.send('Task 에 반영해줘', 'failed-task');
  assert.deepEqual(calls, [['preview', 'project', 'group', 'failed-task']], 'task context and other composer drafts are preserved');
  calls.length = 0;
  context.selectedRun.active_step = 'agent_execution';
  let blockedNotice = '';
  context.setNotice = value => { blockedNotice = value; };
  await context.send();assert.deepEqual(calls, [], 'a blocked shortcut preserves the input and makes no requests');
  assert.match(blockedNotice, /작업 실행 중/);
  context.selectedRun.active_step = null;
  context.selectedRun.stage = 'merged';
  let notice = '';
  context.setNotice = (value) => { notice = value; };
  context.setWorkbenchView = (value) => calls.push(['view', value]);
  context.setWorkDetailsOpen = (value) => calls.push(['details', value]);
  await context.send('반영');
  assert.deepEqual(calls, [['view', 'results'], ['details', true]], 'completed results reopen review even when the result tab was already selected');
  assert.match(notice, /변경 기록에서 대화로 수정안/);
});

test('failed and executing groups keep discussion available with active execution metadata', () => {
  for (const stage of ['failed', 'executing', 'ready_to_merge']) {
    const current = workbench({ stage, active_step: 'agent_execution', execution_control: { situation: 'running', action: 'none' } },
      { message: '실패한 이유를 설명해 주세요.' });
    const send = nodes(current.tree).find((node) => node.type === 'button' && text(node) === '전송');
    assert.equal(send.props.disabled, false, stage);
    send.props.onClick(); assert.deepEqual(current.calls, ['send']);
  }
  const locked = workbench({}, { message: '실패 원인을 설명해 주세요.', busyAction: 'runs.sendPlanningMessage' });
  const send = nodes(locked.tree).find((node) => node.type === 'button' && text(node) === '전송 중');
  assert.equal(send.props.disabled, true, 'a live chat still prevents duplicate submission');
});

test('late chat failure restores only the original group draft without overwriting newer text or resending', async () => {
  const { DirectionChangeDrafts } = localRequire('./directionChangeDrafts.js');
  const callback = source.match(/^    const sendPlanningMessage = [\s\S]*?(?=^    const applyPlanningConversation =)/m);
  assert.ok(callback);
  for (const [newerText, destinationText, destinationProject] of [
    ['', '', 'other-project'], ['', '', 'project'],
    ['새로 작성 중인 내용', '다른 그룹 초안', 'other-project'],
  ]) {
    const drafts = new DirectionChangeDrafts();
    drafts.edit('project', 'group', '실패 원인을 설명해 주세요.');
    drafts.edit(destinationProject, 'other-group', destinationText);
    const calls = []; const busy = []; let pending; let rejectSend; let error = '';
    const run = { id: 'group', stage: 'failed', repository_intent: 'existing_structure', planning_messages: [] };
    const context = {
      react_1: { useCallback: (fn) => fn },
      planningPreviewRequest_1: localRequire('./planningPreviewRequest.js'),
      planningRequestDrafts_1: localRequire('./planningRequestDrafts.js'),
      TaskStatusOverview_1: localRequire('./TaskStatusOverview.js'), taskDrafts: [], planDirty: false,
      selectedProjectName: 'project', selectedRun: run, selectedPlanningProfile: undefined,
      planningMessage: drafts.read('project', 'group').text, planningReasoning: '', planningProfileManual: false,
      directionChangeDrafts: drafts, selectedContextRef: { current: { projectName: 'project', runId: 'group' } },
      setPlanningMessage: (value) => drafts.edit('project', 'group', typeof value === 'function' ? value(drafts.read('project', 'group').text) : value),
      setRepairTarget() {}, setPendingPlanningMessage: (value) => { pending = typeof value === 'function' ? value(pending) : value; },
      setBusyAction: (value) => busy.push(value), setError: (value) => { error = value; },
      setNotice() {}, setPlanningStartElapsed() {}, setPlanningPreparationMessage() {}, replaceRun() {},
      errorMessage: (cause) => cause.message, recoverStaleRunLock: async () => 'not-stale',
      window: { setInterval: () => 1, clearInterval() {}, orchestrator: { request: (method) => {
        calls.push(method);
        if (method === 'runs.get') return Promise.resolve(run);
        assert.equal(method, 'runs.sendPlanningMessage');
        return new Promise((_, reject) => { rejectSend = reject; });
      } } },
    };
    context.beginTaskPlanning = () => () => {};
    runInNewContext(`${callback[0]}\nthis.send = sendPlanningMessage;`, chatContext(context));
    const sending = context.send();
    assert.equal(drafts.read('project', 'group').text, '');
    context.selectedContextRef.current = { projectName: destinationProject, runId: 'other-group' };
    if (newerText) drafts.edit('project', 'group', newerText);
    rejectSend(new Error('run group is already locked (operation=planning-chat, pid=123)'));
    await sending;
    assert.equal(drafts.read('project', 'group').text, newerText || '실패 원인을 설명해 주세요.');
    assert.equal(drafts.read(destinationProject, 'other-group').text, destinationText);
    assert.equal(pending.status, 'unconfirmed'); assert.equal(pending.runId, 'group');
    assert.equal(error, "", "a late failure belongs to the original conversation, not the selected destination"); assert.equal(busy.at(-1), '');
    assert.equal(calls.filter((method) => method === 'runs.sendPlanningMessage').length, 1);
    assert.ok(calls.every((method) => ['runs.get', 'runs.sendPlanningMessage'].includes(method)), 'no apply, resume or lock cleanup');
  }
});

test('archived apply-like chat sends a message and never opens an apply preview or repeats the historical apply notice', async () => {
  const callback = source.match(/^    const sendPlanningMessage = [\s\S]*?(?=^    const applyPlanningConversation =)/m);
  const run = { id:'archived', stage:'pushed', archive:{cleanup_status:'completed'}, repository_intent:'existing_structure',
    planning_messages:[], planning_apply_requests:[{status:'succeeded',added_tasks:2}] };
  const calls=[], errors=[], notices=[];
  const context = { react_1:{useCallback:fn=>fn}, selectedProjectName:'project', selectedRun:run,
    planningMessage:'지금까지 내용을 Task에 적용해줘', taskDrafts:[], selectedPlanningProfile:undefined,
    planningReasoning:'', planningProfileManual:false, selectedContextRef:{current:{projectName:'project',runId:run.id}},
    directionChangeDrafts:{read:()=>({text:'작성 중'}),edit(){}}, planDirty:false,
    planningRequestDrafts_1:localRequire('./planningRequestDrafts.js'),
    editedPlanningProfileContext:{current:''}, setPlanningProfileManual(){}, beginTaskPlanning:()=>()=>{},
    setRepairTarget(){}, setPlanningMessage(){}, setPendingPlanningMessage(){}, setBusyAction(){}, setError:v=>errors.push(v),
    setNotice:v=>notices.push(v), setPlanningStartElapsed(){}, setPlanningPreparationMessage(){}, replaceRun(){},
    errorMessage:e=>e.message, window:{setInterval:()=>1,clearInterval(){},orchestrator:{request:async(method,params)=>{
      calls.push(method); assert.ok(['runs.get','runs.sendPlanningMessage'].includes(method));
      if(method==='runs.sendPlanningMessage')return {...run,planning_messages:[{role:'user',text:params.message},{role:'assistant',text:'다음 작업을 논의합니다.'}]};
      return run;
    }}}, recoverStaleRunLock:async()=>assert.fail('no lock recovery'),
  };
  runInNewContext(`${callback[0]}\nthis.send = sendPlanningMessage;`,chatContext(context));
  await context.send();
  assert.deepEqual(errors,['']); assert.deepEqual(notices,['']);
  assert.equal(calls.filter(m=>m==='runs.sendPlanningMessage').length,1);
});

test('task questions send current task and draft context while failed sends restore plain input without duplicated context', async () => {
  const { DirectionChangeDrafts } = localRequire('./directionChangeDrafts.js');
  const failureDrafts = localRequire('./failedTaskQuestionDrafts.js');
  const callback = source.match(/^    const sendPlanningMessage = [\s\S]*?(?=^    const applyPlanningConversation =)/m);
  for (const [stage, status, unsaved, newTask] of [
    ['planned', 'pending', true, true], ['planned', 'pending', true, false], ['failed', 'failed', false, false],
    ['executing', 'running', false, false], ['executing', 'stopped', false, false], ['verified', 'completed', false, false],
  ]) {
    const saved = { id: 'chosen', title: '저장 제목', description: '저장된 설명', status, blocked_by: [], action_results: [] };
    const visible = { ...saved, title: unsaved ? '현재 편집 제목' : saved.title, description: unsaved ? '현재 작성한 설명' : saved.description };
    const run = { id: 'group', stage, repository_intent: 'existing_structure', tasks: newTask ? [] : [saved], planning_messages: [],
      execution_control: { situation: status === 'running' ? 'running' : 'resumable', action: status === 'stopped' ? 'resume' : 'none' } };
    const drafts = new DirectionChangeDrafts(); drafts.edit('project', 'group', '이 작업은 언제 진행하나요?');
    const diagnostics = new failureDrafts.FailedTaskQuestionDrafts();
    const diagnostic = '정확한 실패 로그\n\n사용자 질문:\n로그의 문자열';
    diagnostics.prepare('project', 'group', failureDrafts.failedTaskQuestionKey('project', run, saved), '', '짧은 요약', diagnostic);
    const calls = []; let pending; let sendCount = 0; let error = '';
    let repairTarget = { projectName: 'project', runId: 'group', taskId: 'chosen' };
    const context = {
      react_1: { useCallback: (fn) => fn }, TaskStatusOverview_1: localRequire('./TaskStatusOverview.js'),
      failedTaskQuestionDrafts_1: failureDrafts, failedQuestionDrafts: { current: diagnostics },
      planningPreviewRequest_1: localRequire('./planningPreviewRequest.js'), planningRequestDrafts_1: localRequire('./planningRequestDrafts.js'),
      selectedProjectName: 'project', selectedRun: run, taskDrafts: [visible], planDirty: unsaved,
      planningMessage: drafts.read('project', 'group').text, planningReasoning: '', planningProfileManual: false, selectedPlanningProfile: undefined,
      directionChangeDrafts: drafts, editedPlanningProfileContext: { current: '' }, selectedContextRef: { current: { projectName: 'project', runId: 'group' } },
      setPlanningMessage: (value) => drafts.edit('project', 'group', typeof value === 'function' ? value(drafts.read('project', 'group').text) : value),
      setRepairTarget: update => { repairTarget = update(repairTarget); },
      setPendingPlanningMessage: (value) => { pending = typeof value === 'function' ? value(pending) : value; },
      setError: (value) => { error = value; }, errorMessage: (cause) => cause.message,
      recoverStaleRunLock: async () => 'not-stale', replaceRun() {}, setBusyAction() {}, setNotice() {},
      setPlanningPreparationMessage() {}, setPlanningStartElapsed() {}, setPlanningProfileManual() {},
      window: { setInterval: () => 1, clearInterval() {}, orchestrator: { request: async (method, params) => {
        calls.push({ method, params });
        if (method === 'runs.get') return run;
        if (method === 'runs.getPlanningPreview') return null;
        assert.equal(method, 'runs.sendPlanningMessage');
        if (++sendCount === 1) throw new Error('run group is already locked (operation=planning-chat, pid=123)');
        return { ...run, planning_messages: [{ role: 'user', text: params.message }] };
      } } },
    };
    context.beginTaskPlanning = () => () => {};
    runInNewContext(`${callback[0]}\nthis.send = sendPlanningMessage;`, chatContext(context));
    await context.send(undefined, 'chosen');
    assert.match(error, /planning-chat/); assert.equal(pending.status, 'unconfirmed');
    assert.equal(repairTarget.taskId, 'chosen', 'failed sending retains the captured question target for retry');
    assert.equal(drafts.read('project', 'group').text, '이 작업은 언제 진행하나요?');
    context.planningMessage = drafts.read('project', 'group').text;
    await context.send(undefined, 'chosen');
    const sent = calls.filter((entry) => entry.method === 'runs.sendPlanningMessage');
    assert.equal(sent.length, 2); assert.equal(pending, undefined); assert.equal(drafts.read('project', 'group').text, '');
    assert.equal(repairTarget, undefined, 'successful sending releases the invisible target before the next ordinary message');
    for (const request of sent) {
      assert.equal(request.params.projectName, 'project'); assert.equal(request.params.runId, 'group');
      assert.equal(request.params.message.split('질문 대상 Task:').length - 1, 1);
      assert.match(request.params.message, new RegExp(`chosen · ${visible.title}`));
      assert.ok(request.params.message.includes(visible.description));
      assert.equal(request.params.message.includes('미저장 계획의 작업 초안'), unsaved);
      assert.ok(request.params.message.endsWith('사용자 질문:\n이 작업은 언제 진행하나요?'));
      assert.equal(request.params.message.includes('정확한 실패 로그'), status === 'failed');
      assert.equal(context.TaskStatusOverview_1.taskPlanningQuestionBody(request.params.message), '이 작업은 언제 진행하나요?');
      if (unsaved) assert.ok(!request.params.message.includes('저장 제목'));
    }
    const before = calls.length; drafts.edit('project', 'group', '그대로 남길 입력');
    await context.send('그대로 남길 입력', 'missing');
    assert.equal(calls.length, before); assert.equal(drafts.read('project', 'group').text, '그대로 남길 입력');
    assert.match(error, /질문할 작업을 찾지 못했습니다/);
    assert.ok(calls.every((entry) => ['runs.get', 'runs.sendPlanningMessage', 'runs.getPlanningPreview'].includes(entry.method)));
  }
});

test('task questions use only the composer without a separate target title, status or dismiss button', () => {
  const changed = [];
  const current = workbench({ stage: 'planned' }, { planDirty: true, message: '작성 중인 초안',
    taskQuestion: { id: 'new', title: '새 작업 초안', status: 'pending', blocked_by: [], action_results: [] },
    onMessageChange: (text) => changed.push(text) });
  assert.equal(nodes(current.tree).some((node) => node.props?.className === 'planning-task-question'), false);
  assert.equal(nodes(current.tree).some((node) => node.props?.['aria-label'] === '작업 질문 대상 해제'), false);
  assert.ok(text(current.tree).includes('초안 질문 가능 · 반영 전 편집 정리'));
  const input = nodes(current.tree).find((node) => node.type === 'textarea'); assert.equal(input.props.value, '작성 중인 초안');
  input.props.onChange({ target: { value: '' } }); assert.deepEqual(changed, ['']);
  const unnamedTask = { id: 'new', title: '', status: 'pending', blocked_by: [], action_results: [] };
  const unnamed = workbench({ stage: 'planned' }, { planDirty: true, taskQuestion: unnamedTask });
  assert.equal(nodes(unnamed.tree).some((node) => node.props?.className === 'planning-task-question'), false);
  assert.match(localRequire('./TaskStatusOverview.js').taskPlanningQuestionDraft(unnamedTask), /제목 없는 작업/);
  const question = localRequire('./TaskStatusOverview.js').taskPlanningQuestion(unnamedTask, { stage: 'planned' }, '새 작업도 질문합니다.', true);
  assert.match(question, /질문 대상 Task: new · 제목 없는 작업/);
  assert.equal(unnamedTask.title, '');
});

function applyReceipt(changes = {}) {
  return { request_id: 'apply-1', conversation_revision: 2, plan_revision: 1, status: 'succeeded',
    created_at: '2026-10-13T08:00:00Z', completed_at: '2026-10-13T08:01:00Z',
    added_tasks: 0, updated_tasks: 1, excluded_tasks: 0, unchanged_tasks: 8, error_code: '', error: '', ...changes };
}

test('current planning activity sits outside conversation bubbles with request-specific copy and confirmed retries', () => {
  for (const [busyAction, label] of [['runs.runPlanning', '계획 작성 중'],
    ['runs.sendPlanningMessage', '답변 작성 중'], ['runs.applyPlanningConversation', '계획 반영 중']]) {
    const current = workbench({ planning_provider_id: 'codex', events: [
      { message: 'planning agent attempt 1 started' }, { message: 'planning agent attempt 1 failed: invalid plan' },
      { message: 'planning agent attempt 2 started' },
    ] }, { busyAction, planningElapsed: 19 });
    const activity = nodes(current.tree).find((node) => node.props.className === 'planning-chat-activity');
    const messages = nodes(current.tree).find((node) => node.props.className === 'planning-messages');
    assert.ok(activity); assert.equal(nodes(messages).includes(activity), false);
    assert.equal(activity.props.role, 'status'); assert.match(text(activity), new RegExp(label));
    assert.match(text(activity), /다시 시도 1회째/);
    const details = nodes(activity).find((node) => node.type === 'details');
    assert.notEqual(details.props.open, true); assert.match(text(details), /Codex/);
    assert.equal(nodes(messages).some((node) => node.props.className?.includes('chat-message--progress')), false);
    assert.deepEqual(current.calls, [], 'reading activity never sends or applies a request');
  }
});

test('chat-first progress occupies the next AI reply position once and completion does not interrupt a pending reply', () => {
  const workActivity=localRequire('react').createElement('section',{'data-completion':true},'완료 안내');
  for(const extra of [{busyAction:'runs.sendPlanningMessage'}, {repairStartedAt:Date.now()-3000},
    {busyAction:'runs.runPlanning'}, {busyAction:'runs.applyPlanningConversation'}]){
    const current=workbench({}, {chatFirst:true,workActivity,...extra});
    const messages=nodes(current.tree).find(node=>node.props.className==='planning-messages');
    const activities=nodes(current.tree).filter(node=>node.props.className==='planning-chat-activity');
    assert.equal(activities.length,1); assert.ok(nodes(messages).includes(activities[0]));
    assert.equal(activities[0].props['data-inline'],true);
    assert.equal(nodes(current.tree).some(node=>node.props['data-completion']),false);
    assert.deepEqual(current.calls,[]);
  }
  const settled=workbench({}, {chatFirst:true,workActivity});
  assert.equal(nodes(settled.tree).some(node=>node.props['data-completion']),true);
  assert.equal(nodes(settled.tree).some(node=>node.props.className==='planning-chat-activity'),false);
});

test('chat execution progress remains visible while its command is awaiting acknowledgment', () => {
  const React=localRequire('react');
  for(const executionPhase of ['stopping','repairing','verifying']){
    const workActivity=React.createElement('section',{'data-execution-progress':executionPhase},'실행 처리 중');
    const current=workbench({}, {chatFirst:true,executionPhase,workActivity,
      pendingMessage:{text:'멈추고 복구 진행해줘',at:'2026-10-22T00:00:00Z',previousMessageCount:1,status:'sending'}});
    assert.equal(nodes(current.tree).filter(node=>node.props['data-execution-progress']===executionPhase).length,1);
    assert.equal(nodes(current.tree).filter(node=>node.props.className==='chat-message chat-message--user chat-message--pending').length,1);
    assert.deepEqual(current.calls,[]);
  }
});

test('recovery starts with one visible notice above the conversation before an AI reply or preview arrives', () => {
  const startedAt = Date.now() - 26000;
  for (const busyAction of ['', 'runs.sendPlanningMessage', 'runs.applyPlanningConversation']) {
    const current = workbench({ events: [{ at: new Date(startedAt - 60000).toISOString(),
      message: 'planning agent attempt 1 failed: previous request error' }] },
    { repairStartedAt: startedAt, busyAction });
    const items = nodes(current.tree);
    const activities = items.filter(node => node.props.className === 'planning-chat-activity');
    assert.equal(activities.length, 1);
    const activity = activities[0];
    const messages = items.find(node => node.props.className === 'planning-messages');
    assert.equal(activity.props.role, 'status'); assert.equal(activity.props['data-repair-active'], true);
    assert.ok(items.indexOf(activity) < items.indexOf(messages));
    assert.equal(nodes(messages).includes(activity), false);
    const summary = nodes(activity).find(node => node.props.className === 'planning-chat-activity__summary');
    assert.match(text(summary), /복구안 작업 중입니다/);
    assert.equal(nodes(summary).find(node=>node.type==='span').props.children, '26초 경과');
    assert.doesNotMatch(text(activity), /previous request error|문제가 생겼습니다|다시 시도/);
    assert.equal(current.preview.props.disabled, true);
    const send = items.find(node => node.type === 'button' && ['전송', '전송 중'].includes(text(node)));
    assert.equal(send.props.disabled, true); send.props.onClick(); assert.deepEqual(current.calls, []);
  }
});

test('opening failure discussion alone never claims that recovery has started, and completion removes the notice', () => {
  const taskQuestion = {id:'task', title:'실패 작업', status:'failed', blocked_by:[], action_results:[]};
  for (const task of [undefined, taskQuestion]) {
    const current = workbench({}, {taskQuestion:task});
    assert.equal(nodes(current.tree).some(node=>node.props['data-repair-active']), false);
    assert.doesNotMatch(text(current.tree), /복구안 작업 중입니다/);
    assert.deepEqual(current.calls, []);
  }
});

test('current recovery failure and provider backoff keep their real error or waiting notice', () => {
  const startedAt = Date.now()-5000;
  const failure = workbench({events:[{at:new Date().toISOString(),message:'planning agent attempt 1 failed: current error'}]},
    {repairStartedAt:startedAt});
  const activity = nodes(failure.tree).find(node=>node.props.className==='planning-chat-activity');
  assert.equal(activity.props.role,'alert'); assert.match(text(activity),/current error|문제가 생겼습니다/);
  const detail=JSON.stringify({retry_at:new Date(Date.now()+30000).toISOString(),retry_index:1,max_retries:4});
  const waiting=workbench({events:[{at:new Date().toISOString(),message:`codex sdk progress: provider_retry_wait | ${detail}`}]},
    {repairStartedAt:startedAt});
  const waitActivity=nodes(waiting.tree).find(node=>node.props.className==='planning-chat-activity');
  assert.match(text(waitActivity),/AI 서버 혼잡/); assert.deepEqual(waiting.calls,[]);
});

test('provider backoff is a visible waiting state and does not send another chat request', () => {
  const detail=JSON.stringify({retry_at:new Date(Date.now()+30000).toISOString(),retry_index:3,max_retries:4});
  const current=workbench({active_step:'planning',events:[{message:`codex sdk progress: provider_retry_wait | ${detail}`}]},
    {busyAction:'runs.sendPlanningMessage',planningElapsed:70});
  const activity=nodes(current.tree).find(node=>node.props.className==='planning-chat-activity');
  const summary=nodes(activity).find(node=>node.props.className==='planning-chat-activity__summary');
  assert.match(text(summary),/AI 서버 혼잡.*초 후 재시도 \(3\/4\)/);
  assert.doesNotMatch(text(activity),/답변 작성 중|retry_at|다시 시도 0회/);
  assert.deepEqual(current.calls,[]);
});

test('previous successful apply feedback does not follow a new request or unapplied conversation', () => {
  for (const [runChanges, changes] of [
    [{}, { busyAction: 'runs.sendPlanningMessage' }],
    [{}, { pendingMessage: { text: '새 질문', at: '2026-10-13T09:00:00Z', previousMessageCount: 1, status: 'unconfirmed' } }],
    [{ planning_conversation_revision: 3 }, {}],
    [{ planning_follow_up_requests: ['새 변경'] }, {}],
    [{ planning_apply_requests: [applyReceipt({ conversation_revision: 1 })] }, {}],
  ]) {
    const current = workbench({ planning_apply_requests: [applyReceipt()], ...runChanges },
      { message: '입력 중인 질문', ...changes });
    assert.equal(nodes(current.tree).some((node) => node.props.className === 'planning-follow-up'), false);
    assert.equal(nodes(current.tree).find((node) => node.type === 'textarea').props.value, '입력 중인 질문');
    assert.deepEqual(current.calls, []);
  }
});

test('current apply result summarizes only changes and retains full counts in a collapsed receipt', () => {
  for (const [receipt, expected] of [
    [applyReceipt(), '1개 수정'], [applyReceipt({ added_tasks: 2, excluded_tasks: 1 }), '2개 추가 · 1개 수정 · 1개 제외'],
    [applyReceipt({ updated_tasks: 0 }), '변경 없음'],
  ]) {
    const current = workbench({ planning_apply_requests: [receipt] });
    const feedback = nodes(current.tree).find((node) => node.props.className === 'planning-follow-up');
    assert.equal(feedback.props['data-status'], 'succeeded'); assert.equal(feedback.props.role, 'status');
    const summary = nodes(feedback).find((node) => node.props.className === 'planning-follow-up__summary');
    assert.match(text(summary), /계획 반영 완료/); assert.ok(text(summary).endsWith(expected));
    assert.doesNotMatch(text(summary), /추가 0|0개 추가|유지 8|8개 유지|작업 탭/);
    const details = nodes(feedback).find((node) => node.type === 'details');
    assert.notEqual(details.props.open, true); assert.match(text(details), /추가 .*수정 .*제외 .*유지 8개/);
    assert.equal(text(current.preview), '반영 완료');
    assert.equal(current.preview.props.disabled, true); current.preview.props.onClick();
    assert.deepEqual(current.calls, [], 'a saved successful receipt cannot repeat the applied conversation');
  }
});

test('apply failure stays visible while queued and applying feedback remain distinct from completion', () => {
  for (const status of ['failed', 'queued', 'applying']) {
    const current = workbench({ active_step: status === 'queued' ? 'agent_execution' : '',
      planning_apply_requests: [applyReceipt({ status, error: status === 'failed' ? '실제 반영 오류 원문' : '' })] });
    const feedback = nodes(current.tree).find((node) => node.props.className === 'planning-follow-up');
    assert.equal(feedback.props['data-status'], status); assert.doesNotMatch(text(feedback), /계획 반영 완료/);
    if (status === 'failed') {
      assert.equal(feedback.props.role, 'alert'); assert.match(text(feedback), /실제 반영 오류 원문/);
      assert.equal(nodes(feedback).some((node) => node.type === 'details'), false, 'failure is not hidden inside details');
    } else if (status === 'queued') assert.match(text(feedback), /계획 반영 대기.*현재 실행이 끝난 뒤/);
    else assert.match(text(feedback), /계획 반영 중.*업데이트/);
    assert.deepEqual(current.calls, []);
  }
});

test('failed planning activity exposes the error and never describes a confirmed final failure as another retry', () => {
  const current = workbench({ active_step: 'planning', events: [
    { message: 'planning agent attempt 1 started' }, { message: 'planning agent attempt 1 failed: first' },
    { message: 'planning agent attempt 2 started' }, { message: 'planning agent attempt 2 failed: invalid plan' },
  ] });
  const activity = nodes(current.tree).find((node) => node.props.className === 'planning-chat-activity');
  assert.equal(activity.props.role, 'alert'); assert.match(text(activity), /문제가 생겼습니다/);
  assert.doesNotMatch(text(activity), /다시 시도.*회째|자동 재시도/);
  const details = nodes(activity).find((node) => node.type === 'details');
  assert.ok(nodes(activity).some((node) => node.type === 'p' && !nodes(details).includes(node)));
});

test('guided central progress keeps its duplicate-display marker after leaving the message list', () => {
  const current = workbench({ repository_intent: 'new_project', active_step: 'planning',
    planning_apply_requests: [applyReceipt()] }, { bodyVisible: true });
  const activity = nodes(current.tree).find((node) => node.props.className === 'planning-chat-activity');
  assert.equal(activity.props['data-central-progress'], true);
  assert.equal(nodes(current.tree).some((node) => node.props.className === 'planning-follow-up'), false);
});


test('both chat composers ignore IME Ctrl/Cmd Enter and accept a fresh key after composition ends', () => {
  for (const fresh of [false, true]) {
    const sent = [];
    const result = workbench({}, { ...(fresh ? { run: undefined, request: '새 작업' } : { message: '질문' }),
      chatFirst: true, onStart: () => sent.push('start'), onSend: () => sent.push('send') });
    const input = nodes(result.tree).find(node => node.type === 'textarea');
    assert.ok(input);
    const key = nativeEvent => ({ key: 'Enter', ctrlKey: true, nativeEvent, preventDefault() {} });
    input.props.onCompositionStart();
    input.props.onKeyDown(key({ isComposing: false, keyCode: 13 }));
    input.props.onCompositionEnd();
    input.props.onKeyDown(key({ isComposing: true }));
    input.props.onKeyDown(key({ keyCode: 229 }));
    assert.deepEqual(sent, []);
    if (!fresh) {
      input.props.onKeyDown(key({ isComposing: false, keyCode: 13 }));
      assert.deepEqual(sent, ['send']);
    }
  }
});

test('a busy reply offers reservation beside interruption and the shortcut obeys IME composition', () => {
  for (const busy of [{busyAction:'runs.sendPlanningMessage',interruptible:true}, {executionPhase:'working'}]) {
    const actions=[];
    const current=workbench({}, {chatFirst:true,message:'끝나면 다음 요청',...busy,onQueue:()=>actions.push('queue'),onInterrupt:()=>actions.push('stop')});
    const reserve=nodes(current.tree).find(node=>node.type==='button' && text(node)==='예약');
    assert.ok(reserve); assert.equal(reserve.props.disabled,false);
    reserve.props.onClick(); assert.deepEqual(actions,['queue']);
    if(busy.interruptible)assert.ok(nodes(current.tree).some(node=>node.type==='button'&&node.props['aria-label']==='기획 중단'));
    const input=nodes(current.tree).find(node=>node.type==='textarea');
    const key=nativeEvent=>({key:'Enter',ctrlKey:true,nativeEvent,preventDefault(){}});
    input.props.onCompositionStart(); input.props.onKeyDown(key({isComposing:false}));
    input.props.onCompositionEnd(); input.props.onKeyDown(key({keyCode:229}));
    assert.deepEqual(actions,['queue']);
    input.props.onKeyDown(key({keyCode:13})); assert.deepEqual(actions,['queue','queue']);
    assert.equal(nodes(current.tree).some(node=>node.type==='button'&&text(node)==='전송'),false);
  }
});

test('one conversation answering never changes another same-project composer into a reservation or blocks a new chat', () => {
  const {planningRequestFor}=localRequire('../../shared/planningRequests.js');
  const snapshot={activeRequests:[{projectName:'project',runId:'answering',method:'runs.sendPlanningMessage',phase:'running'}],recent:[]};
  const currentOwner=planningRequestFor(snapshot,'project','other');
  const other=workbench({id:'other'}, {chatFirst:true,message:'다른 대화의 질문',busyAction:currentOwner?.method||'',interruptible:Boolean(currentOwner),
    onQueue:()=>assert.fail('another conversation does not require reservation')});
  const send=nodes(other.tree).find(node=>node.type==='button'&&text(node)==='전송');
  assert.ok(send);assert.equal(send.props.disabled,false);send.props.onClick();assert.deepEqual(other.calls,['send']);
  assert.equal(nodes(other.tree).some(node=>node.type==='button'&&text(node)==='예약'),false);
  const fresh=components.PlanningWorkbench({...other.props,run:undefined,request:'새 대화의 요청',
    capabilities:{repository_maturity:{kind:'existing_code',evidence:[],ignored_roots:[],detected_application_roots:[],diagnostics:[],inspected_file_count:0}},
    onStart:()=>other.calls.push('new-plan')});
  const start=nodes(fresh).find(node=>node.type==='button'&&node.props.className?.includes('chat-composer__send'));
  assert.equal(start.props.disabled,false);start.props.onClick();assert.deepEqual(other.calls,['send','new-plan']);
  const own=planningRequestFor(snapshot,'project','answering');
  const answering=workbench({id:'answering'},{chatFirst:true,message:'현재 대화의 후속 질문',busyAction:own.method,interruptible:true,onQueue(){}});
  assert.ok(nodes(answering.tree).some(node=>node.type==='button'&&text(node)==='예약'),'only the answering conversation retains its queue');
});

test('queue rows are scoped to the selected conversation and waiting items cannot be jumped by normal sends', () => {
  const own={id:'own',projectName:'project',runId:'group',status:'paused',text:'대기',profile:{planningModel:'opus'},revision:1};
  const other={...own,id:'other',projectName:'B'};
  const changes=[];
  const current=workbench({}, {chatFirst:true,message:'추가 예약',messageQueue:{items:[own,other],error:''},onQueue:()=>changes.push('queue'),
    onChangeQueued:async()=>true,onRestoreQueued:async()=>true});
  const rows=nodes(current.tree).find(node=>typeof node.type==='function'&&node.type.name==='QueuedChatMessages');
  assert.deepEqual(rows.props.items.map(item=>item.id),['own']);
  nodes(current.tree).find(node=>node.type==='button'&&text(node)==='예약').props.onClick();
  assert.deepEqual(changes,['queue']);
  const unavailable=workbench({}, {message:'대기',busyAction:'runs.sendPlanningMessage',onQueue(){},queueSubmitting:true});
  assert.equal(nodes(unavailable.tree).find(node=>node.type==='button'&&text(node)==='예약 중…').props.disabled,true);
});

test('reservation clears only the acknowledged original draft, keeps newer input and retries with the same id after an IPC failure',async()=>{
  const {DirectionChangeDrafts}=localRequire('./directionChangeDrafts.js');
  const callback=source.match(/^    const queuePlanningMessage = [\s\S]*?(?=^    const changeQueuedMessage =)/m);assert.ok(callback);
  for(const newer of ['', '추가로 쓰는 중']) {
    const drafts=new DirectionChangeDrafts();drafts.edit('project','group','다음 질문');drafts.edit('B','other','B 초안');
    let finish;const calls=[],errors=[];
    const context={react_1:{useCallback:fn=>fn},selectedProjectName:'project',selectedRun:{id:'group',tasks:[]},
      selectedPlanningProfile:{agent_id:'claude',model:'opus'},planningMessage:'다음 질문',planningReasoning:'high',taskDrafts:[],planDirty:false,nextExecutionProfileDirty:false,
      directionChangeDrafts:drafts,planningRequests:{active:{projectName:'project',runId:'group',requestId:'first-reply'}},queueSubmittingRef:{current:false},queuedSubmissionRef:{current:undefined},
      planningRequests_1:localRequire('../../shared/planningRequests.js'),
      selectedContextRef:{current:{projectName:'project',runId:'group'}},setQueueSubmitting(){},setPlanningRequests(){},setError:value=>errors.push(value),
      chatTaskRecovery_1:localRequire('./chatTaskRecovery.js'),runExecutionControl_1:localRequire('./runExecutionControl.js'),errorMessage:error=>error.message,crypto:require('node:crypto').webcrypto,
      runContextMatches:(a,b,c,d)=>a===c&&b===d,
      window:{orchestrator:{queuePlanningMessage:params=>{calls.push(params);return new Promise(resolve=>{finish=resolve})}}}};
    runInNewContext(`${callback[0]}\nthis.reserve=queuePlanningMessage;`,context);
    const pending=context.reserve();assert.equal(drafts.read('project','group').text,'다음 질문','draft stays until main confirms durable acceptance');
    context.selectedContextRef.current={projectName:'B',runId:'other'};if(newer)drafts.edit('project','group',newer);
    finish({items:[],error:''});await pending;
    assert.equal(drafts.read('project','group').text,newer);assert.equal(drafts.read('B','other').text,'B 초안');assert.deepEqual(errors,[]);
    assert.equal(calls[0].projectName,'project');assert.equal(calls[0].profile.planningModel,'opus');assert.equal(calls[0].afterRequestId,'first-reply');
    context.selectedContextRef.current={projectName:'project',runId:'group'};drafts.edit('project','group','다음 질문');
    context.window.orchestrator.queuePlanningMessage=async params=>{calls.push(params);throw Error('IPC disconnected')};
    await context.reserve();await context.reserve();
    assert.equal(calls[1].id,calls[2].id);assert.equal(drafts.read('project','group').text,'다음 질문');assert.match(errors.at(-1),/IPC disconnected/);
  }
});


test('global work queries wait for confirmed engine hello', async () => {
  for (const name of ['loadActiveGroups', 'loadAttentionItems']) {
    const start = source.indexOf(`const ${name} = `);
    const ending = '}, [backendChecked]);';
    const end = source.indexOf(ending, start);
    assert.ok(start >= 0 && end > start);
    const expression = source.slice(start, end + ending.length).replace(`const ${name} = `, '')
      .replace('(0, react_1.useCallback)', 'useCallback');
    let calls = 0;
    const query = runInNewContext(expression, { backendChecked: false, useCallback: fn => fn,
      window: { orchestrator: { request() { calls++; assert.fail('engine is not ready'); } } } });
    await query();
    assert.equal(calls, 0);
  }
});
