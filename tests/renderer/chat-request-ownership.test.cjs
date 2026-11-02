const {test}=require('node:test'),assert=require('node:assert/strict');
const {mkdtempSync,mkdirSync,rmSync}=require('node:fs');
const {dirname,join,resolve}=require('node:path');
const {execFileSync}=require('node:child_process');
const root=resolve(__dirname,'../..'),temp=join(root,'.tmp');mkdirSync(temp,{recursive:true});
const output=mkdtempSync(join(temp,'chat-owner-'));
process.on('exit',()=>{assert.equal(dirname(output),temp);rmSync(output,{recursive:true,force:true});});
const ts=require.resolve('typescript/package.json',{paths:[root]});
execFileSync(process.execPath,[resolve(dirname(ts),require(ts).bin.tsc),'--ignoreConfig','--strict','--target','ES2022','--module','commonjs',
 '--skipLibCheck','--types','node','--outDir',output,'desktop/main/planningRequests.ts','desktop/main/chatControls.ts','desktop/renderer/src/composerInput.ts'],{cwd:root,stdio:'inherit'});
const {PlanningRequests}=require(join(output,'main/planningRequests.js'));
const {ChatControls}=require(join(output,'main/chatControls.js'));
const {composerIsComposing}=require(join(output,'renderer/src/composerInput.js'));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}};

test('project chat alternates owned AI decisions and work, keeps one receipt and reports actual completion',async()=>{
 const calls=[],gate=deferred();let step=0;
 const bridge={request:async(method,params)=>{
  calls.push([method,params]);
  if(method==='runs.requestChatControl'||method==='runs.finishPlanningRequest')return{};
  if(method==='runs.beginPlanningRequest')return{kind:'chat'};
  if(method==='runs.advanceChatControl')return{operation:{phase:step===3?'completed':'accepted',status:step===3?'succeeded':'running'},
   next_action:step===3?'none':step===1?'act':'decide',params:{requestId:'parent',stepId:'child'}};
  if(method==='runs.decideProjectChat'){step++;return{}};
  if(method==='runs.performProjectChat'){await gate.promise;step++;return{}};
  if(method==='runs.get')return{id:'original'};
  assert.fail(method);
 },restartPlanning:async()=>{}};
 const owners=new PlanningRequests(bridge),controls=new ChatControls(bridge,undefined,owners);
 const params={projectName:'A',runId:'original',requestId:'parent',intent:'project',message:'잠금해제 하고 계속 진행해줘'};
 const pending=controls.start(params);const duplicate=controls.start(params);
 await new Promise(setImmediate);assert.equal(controls.snapshot()[0].phase,'acting');
 gate.resolve();assert.equal((await pending).id,'original');await duplicate;
 assert.equal(calls.filter(([m])=>m==='runs.performProjectChat').length,1);
 const registrations=calls.filter(([m])=>m==='runs.beginPlanningRequest').map(([,p])=>p.requestId);
 assert.equal(new Set(registrations).size,2);assert.ok(!registrations.includes('parent'));
 assert.equal(controls.snapshot()[0].status,'succeeded');
 assert.ok(calls.every(([,p])=>p.projectName==='A'&&p.runId==='original'));
});

test('Planning slot rejects other conversations and mismatched interruption before touching the bridge',async()=>{
 const work=deferred(),calls=[];
 const bridge={request:async(method,params)=>{calls.push([method,params]);if(method==='runs.beginPlanningRequest')return{kind:'chat'};
  if(method==='runs.sendPlanningMessage')return work.promise;return{};},restartPlanning:async()=>assert.fail('wrong owner must not restart')};
 const owner=new PlanningRequests(bridge);
 const pending=owner.request('runs.sendPlanningMessage',{projectName:'A',runId:'one'});
 await new Promise(setImmediate);
 const original=owner.snapshot().active;
 await assert.rejects(owner.request('runs.sendPlanningMessage',{projectName:'B',runId:'two'}),/planning_capacity_busy/);
 await assert.rejects(owner.interrupt('B','two',original.requestId),/target_changed/);
 await assert.rejects(owner.interrupt('A','one',''),/request_target_required/);
 assert.equal(owner.snapshot().active.requestId,original.requestId);
 work.resolve({id:'one'});await pending;
 assert.equal(owner.snapshot().active,undefined);
 assert.equal(calls.filter(([method])=>method==='runs.sendPlanningMessage').length,1);
});

test('completed and archived reply interruption uses its actual owner kind and preserves the next request',async()=>{
 for(const kind of ['chat','archived_chat']){
  const work=deferred(),calls=[];let restarts=0;
  const bridge={request:async(method,params)=>{calls.push([method,params]);if(method==='runs.beginPlanningRequest')return{kind};
   if(method==='runs.sendPlanningMessage')return work.promise;return{id:'group'};},restartPlanning:async()=>{restarts++;work.reject(Error('terminated'));}};
  const requests=new PlanningRequests(bridge);
  const result=requests.request('runs.sendPlanningMessage',{projectName:'A',runId:'group'}).catch(error=>error.message);
  await new Promise(setImmediate);
  const target=requests.snapshot().active;
  assert.equal(target.kind,kind);
  assert.equal((await requests.interrupt('A','group',target.requestId)).id,'group');
  assert.equal((await result).id,'group');assert.equal(restarts,1);
  assert.equal(calls.find(([method])=>method==='runs.finishPlanningRequest')[1].phase,'interrupted');
  assert.equal(await requests.interrupt('A','group',target.requestId),null);assert.equal(restarts,1);
 }
});

test('a registration failure releases the slot and a failed restart stays confirmation-required',async()=>{
 const bad=new PlanningRequests({request:async()=>{throw Error('registration failed')},restartPlanning:async()=>{}});
 await assert.rejects(bad.request('runs.sendPlanningMessage',{projectName:'A',runId:'one'}),/registration failed/);
 assert.equal(bad.snapshot().active,undefined);
 const work=deferred();const owner=new PlanningRequests({request:async(method)=>method==='runs.beginPlanningRequest'?{kind:'chat'}:work.promise,
  restartPlanning:async()=>{throw Error('termination unconfirmed')}});
 void owner.request('runs.sendPlanningMessage',{projectName:'A',runId:'one'}).catch(()=>{});
 await new Promise(setImmediate);await assert.rejects(owner.interrupt('A','one',owner.snapshot().active.requestId),/unconfirmed/);
 assert.equal(owner.snapshot().active.phase,'confirmation_required');
});

test('main-owned stop and repair continue without a renderer and cannot dispatch repair before confirmed stop',async()=>{
 const calls=[];let stopConfirmed=false,finished=false;const gate=deferred();
 const bridge={request:async(method,params)=>{
  calls.push(method);
  if(method==='runs.requestChatControl')return{};
  if(method==='runs.advanceChatControl')return{operation:{phase:finished?'completed':stopConfirmed?'stop_confirmed':'stopping',status:finished?'succeeded':'running',error:''},
   next_action:finished?'none':stopConfirmed?'repair':calls.includes('runs.requestStop')?'none':'stop',params:{requestId:'child'}};
  if(method==='runs.requestStop')return{};
  if(method==='tasks.repairFromChat'){assert.equal(stopConfirmed,true);finished=true;return{id:'group'}};
  if(method==='runs.get')return{id:'group'};
  assert.fail(method);
 }};
 const controls=new ChatControls(bridge,async()=>{await gate.promise;stopConfirmed=true});
 const params={projectName:'A',runId:'group',requestId:'command',intent:'stop_repair',message:'멈추고 복구해줘'};
 const result=controls.start(params);const duplicate=controls.start(params);
 await new Promise(setImmediate);
 assert.equal(calls.filter(method=>method==='runs.requestStop').length,1);
 assert.equal(calls.includes('tasks.repairFromChat'),false);
 // A view closing or selecting B has no cancellation capability over this owner.
 assert.equal(controls.snapshot()[0].projectName,'A');gate.resolve();
 assert.equal((await result).id,'group');assert.equal((await duplicate).id,'group');
 assert.equal(calls.filter(method=>method==='tasks.repairFromChat').length,1);
 assert.equal(controls.snapshot()[0].phase,'completed');
});

test('IME guards cover composition tracking, native composition and the Windows compatibility key',()=>{
 for(const [composing,event]of [[true,{}],[false,{isComposing:true}],[false,{keyCode:229}]])assert.equal(composerIsComposing(composing,event),true);
 assert.equal(composerIsComposing(false,{isComposing:false,keyCode:13}),false);
});


test('a terminated reply rejecting after stop receipt completion cannot overwrite interruption or the next owner',async()=>{
 const reply=deferred();let restart=0;
 const owners=new PlanningRequests({request:async(method)=>{
  if(method==='runs.beginPlanningRequest')return{kind:'chat'};
  if(method==='runs.sendPlanningMessage')return reply.promise;
  return{id:'A'};
 },restartPlanning:async()=>{restart++}});
 const pending=owners.request('runs.sendPlanningMessage',{projectName:'project',runId:'A'});
 await new Promise(setImmediate);
 const id=owners.snapshot().active.requestId;
 await owners.interrupt('project','A',id);
 assert.equal(owners.snapshot().recent.at(-1).phase,'interrupted');
 reply.reject(Error('late terminated'));
 assert.equal((await pending).id,'A');
 assert.equal(owners.snapshot().recent.at(-1).phase,'interrupted');assert.equal(restart,1);
});


test('an interrupted preview cannot resolve with a Run in place of its declared preview result',async()=>{
 const reply=deferred();const calls=[];
 const owner=new PlanningRequests({request:async(method)=>{
  calls.push(method);if(method==='runs.beginPlanningRequest')return{kind:'replan'};
  if(method==='runs.previewPlanningApply')return reply.promise;
  return{};
 },restartPlanning:async()=>{reply.reject(Error('terminated'))}});
 const pending=owner.request('runs.previewPlanningApply',{projectName:'A',runId:'group'});
 const rejected=assert.rejects(pending,/request_interrupted/);
 await new Promise(setImmediate);await owner.interrupt('A','group',owner.snapshot().active.requestId);await rejected;
 assert.equal(owner.snapshot().recent.at(-1).phase,'interrupted');
 assert.equal(calls.filter(method=>method==='runs.get').length,1,'only the interrupt command returns a fresh Run');
});
