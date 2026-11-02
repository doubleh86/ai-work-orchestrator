const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, mkdirSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const { renderToStaticMarkup } = require('react-dom/server');
const root = resolve(__dirname, '../..'), tempRoot = join(root, '.tmp');
mkdirSync(tempRoot, { recursive: true });
const output = mkdtempSync(join(tempRoot, 'chat-recovery-test-'));
process.on('exit', () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); });
const ts = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(ts), require(ts).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
  'desktop/renderer/src/chatTaskRecovery.ts', 'desktop/renderer/src/ChatWorkActivity.tsx', 'desktop/renderer/src/TaskStatusOverview.tsx',
  'desktop/renderer/src/global.d.ts'],
  { cwd: root, stdio: 'inherit' });
const { chatRequestsTaskRecovery, chatRecoveryTask, recoverTaskFromChat } = require(join(output, 'renderer/src/chatTaskRecovery.js'));
const { ChatWorkActivity, ChatWorkStatus } = require(join(output, 'renderer/src/ChatWorkActivity.js'));
const { taskPlanningQuestionDraft } = require(join(output, 'renderer/src/TaskStatusOverview.js'));
const task = { id: 'broken', title: '테스트 복구', status: 'failed', last_attempt_id: 'attempt-1' };
const run = { id: 'group', stage: 'failed', failed_step: 'agent_execution', plan_revision: 3, planning_conversation_revision: 2,
  planning_messages: [], tasks: [task, { id: 'next', status: 'pending' }], events: [] };
const context = { task_id: 'broken', can_save: true, fingerprint: 'current-failure', plan_revision: 3, attempt_id: 'attempt-1' };
const options = changes => ({ projectName: 'project', run, task, message: '고쳐서 계속해줘', requestId: 'request-1',
  isCurrent: () => true, ...changes });

test('only complete explicit recovery commands execute; questions and prose remain conversation', () => {
  for (const text of ['고쳐서 계속해줘', '고쳐줘', '수정하고 계속해 주세요.', '복구해줘!', '그럼 직접 재시도해줘', '재실행해 주세요']) {
    assert.equal(chatRequestsTaskRecovery(text), true, text);
  }
  for (const text of ['왜 실패했어?', '고쳐줄 수 있어?', '고쳐줘도 되는 거야?', '고치지 마', '일단 냅둬', '수정하고 계속하면 되나?',
    '“고쳐서 계속해줘”', '고쳐서 계속해줘라고 말하면 돼?', '고쳐줘 그리고 테스트는 생략해', '고쳐줘 하지 마', '반영', '',
    'AI가 고쳐줘라고 했어', taskPlanningQuestionDraft(task)]) {
    assert.equal(chatRequestsTaskRecovery(text), false, text);
  }
});

test('only one settled failed execution task is eligible; scope and approval are never inferred', () => {
  assert.equal(chatRecoveryTask(run), task);
  assert.equal(chatRecoveryTask(run, 'broken'), task);
  assert.equal(chatRecoveryTask(run, 'next'), undefined);
  for (const change of [{archive:{}}, {stage:'executing'}, {failed_step:'verify'}, {active_step:'planning'},
    {tasks:[task,{id:'other',status:'failed'}]}, {tasks:[task,{id:'other',status:'running'}]},
    {tasks:[task,{id:'other',status:'waiting'}]}, {tasks:[task,{id:'other',status:'pending',active_action:'execute'}]}]) {
    assert.equal(chatRecoveryTask({...run,...change}), undefined);
  }
});

test('current failure evidence is checked before a single execution request, without a plan rewrite or second AI call', async () => {
  const calls = [];
  const result = { ...run, stage: 'ready_to_merge' };
  const updated = await recoverTaskFromChat(options({ request: async (method, params) => {
    calls.push([method, params]); return method === 'tasks.retryContext' ? context : result;
  } }));
  assert.equal(updated, result);
  assert.deepEqual(calls, [
    ['tasks.retryContext', {projectName:'project',runId:'group',taskId:'broken'}],
    ['tasks.repairFromChat', {projectName:'project',runId:'group',taskId:'broken',requestId:'request-1',message:'고쳐서 계속해줘',
      fingerprint:'current-failure',conversationRevision:2}],
  ]);
});

test('changed context, unavailable evidence and read errors never dispatch recovery', async () => {
  for (const change of [{task_id:'other'}, {can_save:false,reason:'busy'}, {fingerprint:''}, {plan_revision:4}, {attempt_id:'attempt-2'}]) {
    const calls = [];
    await assert.rejects(recoverTaskFromChat(options({ request: async method => {
      calls.push(method); return {...context,...change};
    } })));
    assert.deepEqual(calls, ['tasks.retryContext']);
  }
  await assert.rejects(recoverTaskFromChat(options({request:async()=>{throw new Error('read failed');}})), /read failed/);
});

test('switching the selected group while checking evidence cancels execution; execution failure is not silently retried', async () => {
  const calls = [];
  assert.equal(await recoverTaskFromChat(options({isCurrent:()=>false,request:async method=>{calls.push(method);return context;}})), undefined);
  assert.deepEqual(calls,['tasks.retryContext']);
  calls.length = 0;
  await assert.rejects(recoverTaskFromChat(options({request:async method=>{
    calls.push(method); if(method==='tasks.retryContext') return context; throw new Error('execution failed');
  }})), /execution failed/);
  assert.deepEqual(calls,['tasks.retryContext','tasks.repairFromChat']);
});

test('recovery progress appears immediately and replaces the stale failure card without running anything at render', () => {
  const html = renderToStaticMarkup(ChatWorkActivity({run,recovering:true,recoveryElapsed:12,busy:true,repairing:false,
    onAction(){assert.fail('render started work');},onDiscuss(){assert.fail('render started chat');},onTasks(){assert.fail('render navigated');}}));
  assert.match(html,/복구 작업 중입니다/); assert.match(html,/12초 경과/);
  assert.doesNotMatch(html,/작업이 멈췄어요|<button|오류 상세/);
  const status = renderToStaticMarkup(ChatWorkStatus({run,recovering:true}));
  assert.match(status,/복구 작업 중/); assert.match(status,/data-tone="active"/);
});

function buttons(tree) {
  if (!tree || typeof tree !== 'object') return [];
  if (Array.isArray(tree)) return tree.flatMap(buttons);
  return [...(tree.type === 'button' ? [tree] : []), ...buttons(tree.props?.children)];
}
const buttonText = button => renderToStaticMarkup(button).replace(/<[^>]+>/g, '');

test('failure card separates diagnosis and repair, summarizes the error and preserves raw evidence', () => {
  const calls=[];
  const value={...run,tasks:[{...task,error:'test command timed out: C:\\private\\task.log'},run.tasks[1]]};
  const tree=ChatWorkActivity({run:value,busy:false,repairing:false,onDiscuss:id=>calls.push(['discuss',id]),
    onRecover:id=>calls.push(['recover',id]),onAction(){assert.fail('unexpected group action');},onTasks(){}});
  const html=renderToStaticMarkup(tree);
  assert.match(html,/작업이 멈췄어요/);assert.match(html,/테스트 복구/);assert.match(html,/응답을 기다리는 시간이 초과되었습니다/);
  assert.match(html,/<details><summary>오류 상세<\/summary><pre>test command timed out/);
  assert.doesNotMatch(html,/고쳐서 계속해줘|작업 확인이 필요해요|AI와 논의|작업에 반영/);
  assert.deepEqual(calls,[],'rendering must not trigger recovery');
  const actions=buttons(tree);assert.equal(actions.length,2);
  actions.find(b=>buttonText(b)==='원인 물어보기').props.onClick();
  actions.find(b=>buttonText(b)==='수정하고 계속').props.onClick();
  assert.deepEqual(calls,[['discuss','broken'],['recover','broken']]);
});

test('verification timeout recovery names the verification action and unchanged repeated timeouts cannot resubmit', () => {
  const calls = [];
  const props = { busy:false, repairing:false, onDiscuss:id=>calls.push(['discuss',id]),
    onRecover:id=>calls.push(['recover',id]), onAction(){assert.fail('unexpected action');}, onTasks(){} };
  const failed = {...task, failed_action:'verify', error:'command timed out after 300s: dotnet test Suite.sln'};
  const value = {...run,tasks:[failed,run.tasks[1]]};
  let tree = ChatWorkActivity({...props,run:value,recovery:{kind:"verify_with_timeout_adjustment",can_execute:true,current_limits:[300,600],proposed_limits:[900,1800],will_change:true}});
  const html = renderToStaticMarkup(tree);
  assert.match(html,/검증 시간 초과 · 완료 여부 미확인/);
  const recovery = buttons(tree).find(button=>buttonText(button)==='검증 한도 보완 후 계속');
  assert.equal(recovery.props.disabled,false);
  assert.deepEqual(calls,[]);
  recovery.props.onClick(); assert.deepEqual(calls,[['recover','broken']]);
  failed.error='Task 검증 시간 초과 · 완료 여부 미확인: 같은 검증 조건에서 시간 초과가 반복됐습니다.';
  tree = ChatWorkActivity({...props,run:value,recovery:{kind:"diagnose",can_execute:false,current_limits:[900,1800],proposed_limits:[900,1800],will_change:false}});
  assert.equal(buttons(tree).some(button=>buttonText(button)==='검증 한도 보완 후 계속'),false);
  assert.equal(buttons(tree).find(button=>buttonText(button)==='지연 원인 물어보기').props.disabled,false);
});

test('scope review opens discussion and never submits an unchanged repair', () => {
  const calls = [];
  for (const error of ['task_scope_review_required: {"reason":"Task 검증 시간 초과 원인 수정에 추가 파일 필요","paths":["src/Adapter.cs"]}', 'agent worker produced no commit']) {
    const value = {...run, tasks:[{...task,error},run.tasks[1]]};
    const tree = ChatWorkActivity({run:value,busy:false,repairing:false,
      recovery:{kind:'unavailable',can_execute:false,reason_code:'task_scope_review_required'},
      onDiscuss:id=>calls.push(id),onRecover(){assert.fail('must not repair');},onAction(){},onTasks(){}});
    const html = renderToStaticMarkup(tree);
    assert.match(html,/수정 범위를 확인해 주세요/);
    assert.doesNotMatch(html,/수정하고 계속/);
    assert.doesNotMatch(html,/복구 가능 상태 확인 중|검증 한도 보완|현재 한도/);
    buttons(tree).find(b=>buttonText(b)==='수정 범위 논의').props.onClick();
  }
  assert.deepEqual(calls,['broken','broken']);
});

test('the status RPC scope summary is sufficient before the retry-context request completes', () => {
  const value = {...run,tasks:[{...task,error:'task_scope_review_required: {"reason":"두 파일 허용 경로 추가 승인 필요","paths":["src/SampleRunner/SampleMcpAdapter.cs","tests/SampleRunner.Tests/RunnerRuntimeTests.cs"]}'},run.tasks[1]]};
  const tree = ChatWorkActivity({run:value,busy:false,repairing:false,onDiscuss(){},onRecover(){assert.fail('must discuss scope');},onAction(){},onTasks(){}});
  const html = renderToStaticMarkup(tree);
  assert.match(html,/수정 범위를 확인해 주세요/);
  assert.match(html,/수정 범위 논의/);
  assert.doesNotMatch(html,/수정하고 계속|작업의 변경 기록을 확인하지 못했습니다/);
});

test('repair action stays unavailable for ambiguous failures, archive and unsaved or pending work', () => {
  const props={busy:false,repairing:false,onDiscuss(){},onRecover(){},onAction(){},onTasks(){}};
  for(const value of [{...run,failed_step:'verify'},{...run,tasks:[task,{id:'other',status:'failed'}]},
    {...run,tasks:[task,{id:'other',status:'running'}]}]) {
    const tree=ChatWorkActivity({...props,run:value});
    assert.equal(buttons(tree).some(b=>buttonText(b)==='수정하고 계속'),false);
  }
  assert.equal(ChatWorkActivity({...props,run:{...run,archive:{}}}),null);
  for(const change of [{busy:true},{recoveryDisabled:true}]) {
    const tree=ChatWorkActivity({...props,run,...change});
    const repair=buttons(tree).find(b=>buttonText(b)==='수정하고 계속');
    assert.equal(repair.props.disabled,true);
    if(change.recoveryDisabled)assert.equal(buttons(tree).find(b=>buttonText(b)==='원인 물어보기').props.disabled,false);
  }
});
