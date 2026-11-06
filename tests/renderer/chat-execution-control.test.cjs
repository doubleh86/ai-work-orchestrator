const {test}=require('node:test'),assert=require('node:assert/strict');
const {mkdtempSync,mkdirSync,rmSync}=require('node:fs');
const {dirname,join,resolve}=require('node:path');
const {execFileSync}=require('node:child_process');
const root=resolve(__dirname,'../..'),tmp=join(root,'.tmp');mkdirSync(tmp,{recursive:true});
const output=mkdtempSync(join(tmp,'chat-execution-'));
process.on('exit',()=>{assert.equal(dirname(output),tmp);rmSync(output,{recursive:true,force:true});});
const ts=require.resolve('typescript/package.json',{paths:[root]});
execFileSync(process.execPath,[resolve(dirname(ts),require(ts).bin.tsc),'--ignoreConfig','--strict','--target','ES2022','--module','commonjs',
 '--skipLibCheck','--outDir',output,'desktop/renderer/src/chatExecutionControl.ts'],{cwd:root,stdio:'inherit'});
const {controlExecutionFromChat,chatExecutionErrorReported}=require(join(output,'renderer/src/chatExecutionControl.js'));
const {chatExecutionIntent}=require(join(output,'renderer/src/chatTaskRecovery.js'));
const task={id:'task',title:'기존 작업',status:'running',last_attempt_id:'attempt',active_invocation_id:'invocation',active_action:'execute'};
const active={id:'group',stage:'executing',active_step:'agent_execution',plan_revision:1,planning_conversation_revision:2,tasks:[task],
 execution_control:{execution_id:'execution',can_stop:true,stop_scope:'task',stop_phase:'running',lock_state:'active'}};
const stopped={...active,active_step:null,tasks:[{...task,status:'stopped',active_action:null,active_invocation_id:''}],
 execution_control:{...active.execution_control,can_stop:false,stop_phase:'stopped',lock_state:'unlocked'}};
const failed={...stopped,stage:'failed',failed_step:'agent_execution',tasks:[{...stopped.tasks[0],status:'failed'}]};
const context={task_id:'task',can_save:true,fingerprint:'failure',plan_revision:1,attempt_id:'attempt'};
const options=changes=>({projectName:'project',run:active,message:'현재 작업 멈추고 오류를 고쳐서 계속 진행해줘',intent:'stop_repair',
 requestId:'request',isCurrent:()=>true,onRun(){},onPhase(){},...changes});

test('capable project chats use AI semantics and preserve the chosen profile and explicit target',async()=>{
 const run={...active,project_chat_available:true};
 for(const message of ['잠금해제 하고 계속 진행해줘','왜 멈췄어?','문제 해결하고 나머지도 진행해','완료 조건 바꿔줘'])
  assert.equal(chatExecutionIntent(message,run),'project');
 assert.equal(chatExecutionIntent('지금 중지해줘',run),'stop');
 assert.equal(chatExecutionIntent('잠금해제 하고 계속 진행해줘',{...run,archive:{}}),undefined);
 assert.equal(chatExecutionIntent('잠금해제 하고 계속 진행해줘',active),undefined);
 const profile={planningAgentId:'claude',planningModel:'selected',planningReasoningEffort:'high'},phases=[];
 await controlExecutionFromChat(options({run,intent:'project',taskId:'task',profile,onPhase:p=>phases.push(p),request:async(m,p)=>{
  assert.equal(m,'runs.controlChat');assert.equal(p.intent,'project');assert.deepEqual(p.profile,profile);
  assert.equal(p.expected.taskId,'task');return run;
 }}));
 assert.deepEqual(phases,['thinking']);
});

test('only the matching failure reply to the newly submitted command replaces its duplicate error banner', () => {
 const command = '고쳐서 계속해줘';
 const detail = 'policy_plan_review_required: selected effort mode differs from the approved plan';
 const error = `Error invoking remote method 'orchestrator:request': PythonBridgeRequestError: application_error: ${detail}`;
 const user = { role: 'user', text: command };
 const acknowledgement = { role: 'assistant', text: '중지·복구 요청을 접수했습니다.' };
 const reply = { role: 'assistant', text: `복구를 진행하지 못했습니다. ${detail}` };
 const reported = messages => ({ ...failed, planning_messages: messages });
 assert.equal(chatExecutionErrorReported(reported([user, acknowledgement, reply]), 0, command, error), true);
 assert.equal(chatExecutionErrorReported(reported([user, { ...reply, text: detail }]), 0, command, error), true);
 assert.equal(chatExecutionErrorReported(reported([user, acknowledgement]), 0, command, error), false);
 assert.equal(chatExecutionErrorReported(reported([user, reply]), 2, command, error), false);
 assert.equal(chatExecutionErrorReported(reported([user, reply]), 0, '다른 명령', error), false);
 assert.equal(chatExecutionErrorReported(reported([user, reply]), 0, command, 'Backend 조회 요청 시간 초과'), false);
 assert.equal(chatExecutionErrorReported(reported([user, { role: 'user', text: '다른 명령' }, reply]), 0, command, error), false);
});

test('natural stop and recovery requests execute without requiring a special phrase or a second button',()=>{
 for(const [text,intent]of [['진행 멈춰줘','stop'],['현재 작업 잠깐 중지해 주세요','stop'],['멈춰','stop'],
  ['지금 작업 멈추고 복구 진행해줘','stop_repair'],['진행 중지 후 복구를 진행해줘','stop_repair'],
  ['일단 멈추고 오류를 수정해서 계속해 줄래?','stop_repair'],['오류 원인 찾아서 고치고 이어서 진행해줘','repair'],
  ['복구 진행','repair'],['그럼 직접 재시도해줘','repair'],['복구를 해줘','repair'],['복구를 진행해줘','repair'],
  ['일단 멈추고 원인 알려줘','stop']])assert.equal(chatExecutionIntent(text),intent,text);
 for(const text of ['왜 멈췄어?','중지하는 방법 알려줘','복구할 수 있어?','고치지 마','중지하지 말고 설명해줘',
  '“중지하고 복구해줘”','중지해줘라고 하면 돼?','고쳐줘 그리고 테스트 생략해','수정 후 푸시해줘','복구하면 되나?',
  '실패 원인을 확인해서 Task 수정해줘','완료 조건을 변경해줘','수정한 내용 알려줘','복구 상황 알려줘',
  '복구 진행 상황 정리해줘','중지 상태 설명해줘','재시도 결과 보여줘','수정할 부분 알려줘',
  '내일 복구해줘','오류가 발생하면 멈춰줘','지금 작업 끝나면 복구해줘']) {
  assert.equal(chatExecutionIntent(text),undefined,text);
 }
});

test('planning without Tasks never dispatches an execution recovery, including the reported agreed-plan request', () => {
 const planning={...failed,stage:'needs_clarification',tasks:[],project_chat_available:false,
  execution_control:{...failed.execution_control,can_stop:false}};
 for(const message of ['계획 생성이 안 되는 문제 고치고, 합의한 6개 작업으로 이어서 진행해줘',
  '합의한 작업으로 계속 진행해줘','고쳐서 계속해줘','논의한 내용으로 Task 만들어줘','진행 멈춰줘'])
  assert.equal(chatExecutionIntent(message,planning),undefined,message);
 assert.equal(chatExecutionIntent('진행 멈춰줘',{...planning,execution_control:{...planning.execution_control,can_stop:true}}),'stop');
 assert.equal(chatExecutionIntent('고쳐서 계속해줘',failed),'repair','real execution recovery remains available');
});

test('a chat command sends one captured request to main, independent of the selected conversation',async()=>{
 const calls=[],observed=[],phases=[];
 const result=await controlExecutionFromChat(options({isCurrent:()=>false,onPhase:phase=>phases.push(phase),onRun:run=>observed.push(run),
  request:async(method,params)=>{calls.push([method,params]);return stopped;}}));
 assert.equal(result,stopped);assert.equal(calls.length,1);assert.equal(calls[0][0],'runs.controlChat');
 assert.equal(calls[0][1].runId,'group');assert.equal(calls[0][1].expected.taskId,'task');
 assert.equal(calls[0][1].expected.attemptId,'attempt');assert.equal(calls[0][1].expected.invocationId,'invocation');
 assert.equal(calls[0][1].expected.planRevision,1);assert.equal(calls[0][1].expected.conversationRevision,2);
 assert.deepEqual(observed,[stopped]);assert.deepEqual(phases,['stopping']);
});

test('stop alone, failed repair and stopped repair keep distinct intents without direct child mutation',async()=>{
 for(const [run,intent]of [[active,'stop'],[failed,'repair'],[stopped,'repair']]){
  const calls=[];await controlExecutionFromChat(options({run,intent,request:async(method,params)=>{
   calls.push(method);assert.equal(params.intent,intent);return run;}}));assert.deepEqual(calls,['runs.controlChat']);
 }
});

test('ambiguous running tasks require an explicit target and failed responses remain errors',async()=>{
 const ambiguous={...active,tasks:[task,{...task,id:'second'}]};
 await assert.rejects(controlExecutionFromChat(options({run:ambiguous,request:async()=>assert.fail('ambiguous target')})),/하나로 특정/);
 await controlExecutionFromChat(options({run:ambiguous,taskId:'second',request:async(method,params)=>{
  assert.equal(params.expected.taskId,'second');return ambiguous;}}));
 await assert.rejects(controlExecutionFromChat(options({request:async()=>{throw Error('stop unconfirmed')}})),/stop unconfirmed/);
 await assert.rejects(controlExecutionFromChat(options({request:async()=>({...active,id:'other'})})),/요청 대상/);
});

test('verification stop and repair keep their original scope in the main-owned command',async()=>{
 const run={...active,active_step:'verify',tasks:[{...task,status:'completed',active_action:null}],
  execution_control:{...active.execution_control,stop_scope:'verification'}};
 await controlExecutionFromChat(options({run,request:async(method,params)=>{
  assert.equal(method,'runs.controlChat');assert.equal(params.expected.scope,'verification');assert.equal(params.expected.taskId,'');return run;}}));
});
