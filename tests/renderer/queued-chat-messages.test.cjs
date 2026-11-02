const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, rmSync, readFileSync, writeFileSync } = require('node:fs');
const { createRequire } = require('node:module');
const { runInNewContext } = require('node:vm');
const { dirname, join, resolve } = require('node:path');
const { randomUUID } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const root = resolve(__dirname, '../..'), tempRoot = join(root, '.tmp');
mkdirSync(tempRoot, { recursive: true });
const output = mkdtempSync(join(tempRoot, 'message-queue-'));
process.on('exit', () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); });
const ts = require.resolve('typescript/package.json');
execFileSync(process.execPath, [resolve(dirname(ts), require(ts).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--types', 'node', '--outDir', output,
  'desktop/main/planningMessageQueue.ts', 'desktop/renderer/src/QueuedChatMessages.tsx'], { cwd: root, stdio: 'inherit' });
const { PlanningRequests } = require(join(output, 'main/planningRequests.js'));
const { PlanningMessageQueue } = require(join(output, 'main/planningMessageQueue.js'));
const { ChatControls } = require(join(output, 'main/chatControls.js'));
const { chatControlParams } = require(join(output, 'shared/chatExecution.js'));
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const tick = () => new Promise(resolve => setTimeout(resolve, 10));
async function until(predicate) { for (let i = 0; i < 200; i++) { if (predicate()) return; await tick(); } assert.fail('queue did not settle'); }
function input(changes = {}) { return { id: randomUUID(), projectName: 'A', runId: 'one', text: '다음 요청', message: '다음 요청',
  profile: { planningAgentId: 'claude', planningModel: 'opus', planningReasoningEffort: 'high' }, ...changes }; }
function harness(t, respond = () => undefined, path = join(output, `${randomUUID()}.json`)) {
  const calls = [];
  const bridge = { request: async (method, params) => {
    calls.push([method, structuredClone(params)]);
    const custom = respond(method, params); if (custom !== undefined) return custom;
    if (method === 'runs.beginPlanningRequest') return { kind: 'chat' };
    if (method === 'runs.get') return { id: params.runId, plan_revision: 2, tasks: [] };
    return { id: params.runId };
  }, restartPlanning: async () => {} };
  const owners = new PlanningRequests(bridge), controls = new ChatControls(bridge);
  const queue = new PlanningMessageQueue(path, owners, bridge, controls);
  t.after(() => queue.close());
  return { calls, bridge, owners, controls, queue, path };
}
function change(queue, id, action) {
  const item = queue.snapshot().items.find(item => item.id === id);
  return queue.change({ id, projectName: item.projectName, runId: item.runId, revision: item.revision, action });
}

test('busy replies accept a durable queue, keep frozen ownership/profile, edit and cancel before dispatch', async t => {
  const gate = deferred();
  const h = harness(t, (method, params) => method === 'runs.sendPlanningMessage' && params.message === 'first' ? gate.promise : undefined);
  const first = h.owners.request('runs.sendPlanningMessage', { projectName: 'B', runId: 'two', message: 'first' });
  await tick();
  const item = input(), second = input({ text: '취소', message: '취소' });
  h.queue.enqueue(item); h.queue.enqueue(item); h.queue.enqueue(second);
  assert.equal(h.queue.snapshot().items.length, 2);
  assert.equal(JSON.parse(readFileSync(h.path, 'utf8')).items.length, 2);
  item.profile.planningModel = 'changed after accepting';
  const edited={...h.queue.snapshot().items[0],id:randomUUID(),text:'수정한 요청',message:'수정한 요청'};
  change(h.queue, item.id, 'cancel');change(h.queue, second.id, 'cancel');h.queue.enqueue(edited);
  await tick(); assert.equal(h.calls.filter(([method]) => method === 'runs.sendPlanningMessage').length, 1);
  gate.resolve({ id: 'two' }); await first;
  await until(() => h.queue.snapshot().items[0].status === 'sent');
  const sent = h.calls.filter(([method]) => method === 'runs.sendPlanningMessage').at(-1)[1];
  assert.equal(sent.projectName, 'A'); assert.equal(sent.runId, 'one'); assert.equal(sent.message, '수정한 요청');
  assert.equal(sent.planningModel, 'opus'); assert.equal(sent.planningReasoningEffort, 'high');
});

test('queued messages send in order exactly once, and an already claimed item cannot be edited or cancelled', async t => {
  const gate = deferred();
  const h = harness(t, (method, params) => method === 'runs.sendPlanningMessage' && params.message === 'one' ? gate.promise : undefined);
  const a = input({ text: 'one', message: 'one' }), b = input({ text: 'two', message: 'two' });
  h.queue.enqueue(a); h.queue.enqueue(b);
  await until(() => h.owners.snapshot().active);
  assert.throws(() => change(h.queue, a.id, 'cancel'), /이미 전송/);
  assert.deepEqual(h.calls.filter(([method]) => method === 'runs.sendPlanningMessage').map(([, params]) => params.message), ['one']);
  gate.resolve({ id: 'one' });
  await until(() => h.queue.snapshot().items.every(item => item.status === 'sent'));
  h.queue.enqueue(a); await tick();
  assert.deepEqual(h.calls.filter(([method]) => method === 'runs.sendPlanningMessage').map(([, params]) => params.message), ['one', 'two']);
});

test('failed or interrupted owning replies pause successors; a failed different conversation does not pause this one', async t => {
  for (const interrupted of [false, true]) {
    const gate = deferred();
    const h = harness(t, (method, params) => method === 'runs.sendPlanningMessage' && params.message === 'first' ? gate.promise : undefined);
    h.bridge.restartPlanning = async () => gate.reject(Error('terminated'));
    const first = h.owners.request('runs.sendPlanningMessage', { projectName: 'A', runId: 'one', message: 'first' }).catch(() => {});
    await tick(); const owner = h.owners.snapshot().active;
    const queued = input({ afterRequestId: owner.requestId }); h.queue.enqueue(queued);
    if (interrupted) await h.owners.interrupt('A', 'one', owner.requestId); else gate.reject(Error('provider failed'));
    await first; await tick(); assert.equal(h.queue.snapshot().items[0].status, 'paused');
    change(h.queue, queued.id, 'resume'); await until(() => h.queue.snapshot().items[0].status === 'sent');
  }
  const gate = deferred(), h = harness(t, method => method === 'runs.sendPlanningMessage' && h.owners.snapshot().active?.runId === 'two' ? gate.promise : undefined);
  const first = h.owners.request('runs.sendPlanningMessage', { projectName: 'B', runId: 'two' }).catch(() => {});
  await tick(); h.queue.enqueue(input()); gate.reject(Error('B failed')); await first;
  await until(() => h.queue.snapshot().items[0].status === 'sent');
});

test('restart restores waiting messages paused and in-flight messages uncertain without automatic replay', async t => {
  const gate = deferred(), h = harness(t, method => method === 'runs.sendPlanningMessage' ? gate.promise : undefined);
  const a = input(); h.queue.enqueue(a);
  await until(() => h.owners.snapshot().active);
  const b = input(); h.queue.enqueue(b); h.queue.close();
  const restored = harness(t, undefined, h.path);
  assert.deepEqual(restored.queue.snapshot().items.map(item => item.status), ['uncertain', 'paused']);
  await tick(); assert.equal(restored.calls.length, 0);
  assert.throws(() => change(restored.queue, a.id, 'resume'), /이전 전송 결과/);
  change(restored.queue, a.id, 'cancel'); change(restored.queue, b.id, 'resume');
  await until(() => restored.queue.snapshot().items[0].status === 'sent');
  gate.resolve({ id: 'one' });
});

test('preflight failure is retryable, dispatched failure is uncertain, and following items remain paused', async t => {
  let fail = true;
  const h = harness(t, method => { if (method === 'runs.get' && fail) return Promise.reject(Error('offline')); });
  const a = input(); h.queue.enqueue(a); await until(() => h.queue.snapshot().items[0].status === 'failed');
  fail = false; change(h.queue, a.id, 'resume'); await until(() => h.queue.snapshot().items[0].status === 'sent');
  const bad = harness(t, method => method === 'runs.sendPlanningMessage' ? Promise.reject(Error('provider disconnected')) : undefined);
  bad.queue.enqueue(input()); bad.queue.enqueue(input());
  await until(() => bad.queue.snapshot().items[0].status === 'uncertain');
  assert.deepEqual(bad.queue.snapshot().items.map(item => item.status), ['uncertain', 'paused']);
  assert.equal(bad.calls.filter(([method]) => method === 'runs.sendPlanningMessage').length, 1);
});

test('stale revisions, corrupt storage, invalid payloads and failed persistence never silently accept messages', async t => {
  const gate = deferred(), h = harness(t, method => method === 'runs.sendPlanningMessage' ? gate.promise : undefined);
  const pending = h.owners.request('runs.sendPlanningMessage', { projectName: 'A', runId: 'one' }); await tick();
  const a = input(); h.queue.enqueue(a); change(h.queue, a.id, 'resume');
  assert.throws(() => h.queue.change({ ...a, revision: 1, action: 'cancel' }), /예약이 변경/);
  assert.throws(() => h.queue.enqueue({ ...a, id: randomUUID(), profile: {} }), /설정/);
  const path = join(output, 'corrupt.json'); writeFileSync(path, '{broken');
  const corrupt = harness(t, undefined, path); assert.match(corrupt.queue.snapshot().error, /읽지 못/);
  assert.throws(() => corrupt.queue.enqueue(input()), /읽지 못/); assert.equal(readFileSync(path, 'utf8'), '{broken');
  const blocked = join(output, 'not-directory'); writeFileSync(blocked, 'file');
  const storage = harness(t, undefined, join(blocked, 'queue.json'));
  assert.throws(() => storage.queue.enqueue(input())); assert.equal(storage.queue.snapshot().items.length, 0);
  gate.resolve({ id: 'one' }); await pending;
});

test('a late reservation after its answer failed is paused even when the renderer has an old busy snapshot', async t => {
  const h = harness(t, method => method === 'runs.sendPlanningMessage' ? Promise.reject(Error('failed')) : undefined);
  await h.owners.request('runs.sendPlanningMessage', { projectName: 'A', runId: 'one', requestId: randomUUID() }).catch(() => {});
  h.queue.enqueue(input({ afterRequestId: h.owners.snapshot().recent.at(-1).requestId }));
  await tick(); assert.equal(h.queue.snapshot().items[0].status, 'paused');
});

test('queued execution commands keep their captured task and attempt but read the latest conversation revision', async t => {
  for (const changed of [false, true]) {
    const run={id:'one',plan_revision:2,planning_conversation_revision:4,tasks:[{id:'task',status:'failed',last_attempt_id:'attempt'}]};
    const h=harness(t,method=>method==='runs.get'?run:undefined);
    const {conversationRevision,...controlTarget}=chatControlParams('A',run,'고쳐서 계속해줘',randomUUID(),'repair').expected;
    let dispatched;
    h.controls.start=async params=>{dispatched=params;return{id:'one'}};
    if(changed)run.tasks[0].last_attempt_id='new-attempt';
    h.queue.enqueue(input({text:'고쳐서 계속해줘',message:'고쳐서 계속해줘',controlTarget}));
    await until(()=>['sent','failed'].includes(h.queue.snapshot().items[0].status));
    if(changed){assert.equal(dispatched,undefined);assert.match(h.queue.snapshot().items[0].error,/실행 대상이 변경/)}
    else {assert.equal(dispatched.expected.taskId,'task');assert.equal(dispatched.expected.attemptId,'attempt');assert.equal(dispatched.expected.conversationRevision,4)}
  }
});

test('queued autonomous messages retain their project mode and model while rechecking the same plan', async t => {
  const run={id:'one',project_chat_available:true,plan_revision:2,planning_conversation_revision:4,
    tasks:[{id:'task',status:'failed',last_attempt_id:'current-attempt'}]};
  const h=harness(t,method=>method==='runs.get'?run:undefined);
  const {conversationRevision,...controlTarget}=chatControlParams('A',run,'잠금해제 하고 계속해줘',randomUUID(),'project').expected;
  let dispatched;
  h.controls.start=async params=>{dispatched=params;return run};
  const message=input({text:'잠금해제 하고 계속해줘',executionMode:'project',controlTarget});
  h.queue.enqueue(message);
  assert.equal(JSON.parse(readFileSync(h.path,'utf8')).items[0].executionMode,'project');
  await until(()=>h.queue.snapshot().items[0].status==='sent');
  assert.equal(dispatched.intent,'project');assert.deepEqual(dispatched.profile,message.profile);
  assert.equal(dispatched.expected.conversationRevision,4);assert.equal(dispatched.expected.taskId,'');
  run.plan_revision++;
  h.queue.enqueue({...message,id:randomUUID()});
  await until(()=>h.queue.snapshot().items.at(-1).status==='failed');
  assert.match(h.queue.snapshot().items.at(-1).error,/실행 대상이 변경/);
});

test('app closure during preflight prevents dispatch and untrusted payload extras cannot become RPC flags',async t=>{
  const gate=deferred(),h=harness(t,method=>method==='runs.get'?gate.promise:undefined);
  h.queue.enqueue(input());await until(()=>h.queue.snapshot().items[0].status==='sending');h.queue.close();
  gate.resolve({id:'one',plan_revision:2,tasks:[]});await until(()=>h.queue.snapshot().items[0].status==='paused');
  assert.equal(h.calls.some(([method])=>method==='runs.sendPlanningMessage'),false);
  const normal=harness(t);const value=input();value.profile.approved=true;value.approved=true;value.method='runs.push';
  normal.queue.enqueue(value);await until(()=>normal.queue.snapshot().items[0].status==='sent');
  const params=normal.calls.find(([method])=>method==='runs.sendPlanningMessage')[1];
  assert.equal(params.approved,undefined);assert.equal(params.method,undefined);
});

test('a queued message waits for an accepted execution control before using the chat slot',async t=>{
  let completed=false;
  const h=harness(t,method=>method==='runs.advanceChatControl'?{operation:{phase:completed?'completed':'stopping',status:completed?'succeeded':'running',error:''},next_action:'none',params:{}}:undefined);
  const control=h.controls.start({projectName:'A',runId:'one',requestId:randomUUID(),intent:'stop',message:'멈춰'});
  await tick();h.queue.enqueue(input());await tick();
  assert.equal(h.calls.some(([method])=>method==='runs.sendPlanningMessage'),false);
  completed=true;await control;await until(()=>h.queue.snapshot().items[0].status==='sent');
});

test('a new control accepted during asynchronous preflight postpones message dispatch',async t=>{
  const gate=deferred();let controls=[];
  const h=harness(t,method=>method==='runs.get'?gate.promise:undefined);
  h.controls.snapshot=()=>controls;
  h.queue.enqueue(input());await until(()=>h.queue.snapshot().items[0].status==='sending');
  controls=[{projectName:'A',runId:'one',status:'running'}];gate.resolve({id:'one',plan_revision:2,tasks:[]});
  await until(()=>h.queue.snapshot().items[0].status==='queued');
  assert.equal(h.calls.some(([method])=>method==='runs.sendPlanningMessage'),false);
});

test('queued rows expose real status, edit returns to the composer, and rapid cancellation cannot submit twice',async()=>{
  const componentPath=join(output,'renderer/src/QueuedChatMessages.js'),localRequire=createRequire(componentPath),components={};
  runInNewContext(readFileSync(componentPath,'utf8'),{exports:components,require:name=>name==='react'?{
    ...localRequire(name),useState:initial=>[initial,()=>{}],useRef:value=>({current:value})}:localRequire(name)});
  const nodes=tree=>!tree||typeof tree!=='object'?[]:Array.isArray(tree)?tree.flatMap(nodes):[tree,...nodes(tree.props?.children)];
  const statuses=['queued','paused','sending','sent','failed','uncertain'];
  const items=statuses.map(status=>({...input({id:status}),status,revision:4,error:status==='uncertain'?'unknown reply':'',createdAt:1,waitForRequestId:''}));
  let cancelled,restored,cancelCount=0;const gate=deferred();
  const tree=components.QueuedChatMessages({items,onChange:async change=>{cancelCount++;cancelled=change;await gate.promise;return true},onRestore:async item=>{restored=item;return true}});
  const rows=nodes(tree).filter(node=>node.type==='li');assert.equal(rows.length,5);
  const sending=rows.find(row=>row.props['data-status']==='sending');assert.equal(nodes(sending).some(node=>node.type==='button'),false);
  const uncertain=rows.find(row=>row.props['data-status']==='uncertain');
  assert.equal(nodes(uncertain).some(node=>node.type==='button'&&node.props.children?.includes?.('다시 예약')),false);
  assert.equal(nodes(uncertain).find(node=>node.props?.role==='alert').props.children,'unknown reply');
  nodes(rows[0]).find(node=>node.props['aria-label']==='예약 메시지 수정').props.onClick();await tick();assert.equal(restored.id,'queued');
  const cancel=nodes(rows[0]).find(node=>node.props['aria-label']==='예약 취소');
  cancel.props.onClick();cancel.props.onClick();assert.equal(cancelled.id,'queued');assert.equal(cancelled.revision,4);assert.equal(cancelCount,1);
  gate.resolve();await tick();
});
