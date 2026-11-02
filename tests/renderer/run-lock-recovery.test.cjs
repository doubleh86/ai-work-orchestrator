const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, mkdirSync, rmSync, readFileSync } = require('node:fs');
const { createRequire } = require('node:module');
const { runInNewContext } = require('node:vm');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const root = resolve(__dirname, '../..');
const tempRoot = join(root, '.tmp'); mkdirSync(tempRoot, { recursive: true });
const output = mkdtempSync(join(tempRoot, 'run-lock-recovery-'));
process.on('exit', () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); });
const ts = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(ts), require(ts).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
  'desktop/renderer/src/runLockRecovery.ts', 'desktop/renderer/src/RunLockNotice.tsx', 'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });
const { RunLockRecoverySession, runLockAction } = require(join(output, 'renderer/src/runLockRecovery.js'));
const copy = (value) => structuredClone(value);
function fixture(state = 'stale', changes = {}) {
  const run = { id: 'group', updated_at: '2026-10-10T00:00:00Z', summary: '선택 그룹', stage: 'executing',
    tasks: [{ id: 'active', last_attempt_id: 'attempt', active_invocation_id: 'invocation' }],
    execution_control: { situation: state === 'active' ? 'running' : 'attention_required', lock_state: state,
      operation: 'execute', execution_id: 'execution', active_task_id: 'active', can_stop: state === 'active' }, ...changes };
  return { run, lock: { run_id: run.id, state, operation: run.execution_control.operation, reason: 'owner process 12 is not running' } };
}
function harness(initial = fixture(), hooks = {}) {
  let data = copy(initial); const calls = []; const snapshots = [];
  const api = { request: async (method, params) => {
    calls.push({ method, params });
    if (hooks.request) { const result = await hooks.request(method, params); if (result !== undefined) return result; }
    if (method === 'runs.get') return copy(data.run);
    if (method === 'locks.get') return copy(data.lock);
    if (method === 'runs.requestStop') { data.run.execution_control.stop_phase = 'stopping'; return { phase: 'requested' }; }
    throw new Error('unexpected request ' + method);
  }, approve: async (method, params) => {
    calls.push({ method, params, approved: true });
    assert.equal(method, 'locks.clear');
    if (hooks.approve) return hooks.approve(method, params);
    data.lock.state = 'unlocked'; data.run.execution_control.lock_state = 'unlocked';
    return copy(data.lock);
  } };
  const session = new RunLockRecoverySession(api, 'selected-project', initial.run.id, (state) => snapshots.push(state));
  return { session, api, calls, snapshots, get data() { return data; }, set data(next) { data = copy(next); } };
}

test('slow refresh preserves the last lock display and blocks concurrent checks and stale mutations', async () => {
  let release; let hold = false;
  const h = harness(fixture(), { request: async method => {
    if (hold && method === 'runs.get') { hold = false; return new Promise(resolve => { release = resolve; }); }
  } });
  await h.session.check(); const previous=h.snapshots.at(-1); hold=true;
  const checking=h.session.check(); const count=h.calls.length;
  assert.equal(h.snapshots.at(-1).phase,'loading');
  assert.equal(h.snapshots.at(-1).run,previous.run); assert.equal(h.snapshots.at(-1).lock,previous.lock);
  await h.session.check(); await h.session.act('clear');
  assert.equal(h.calls.length,count); assert.ok(!h.calls.some(c=>c.approved));
  release(copy(h.data.run)); await checking; assert.equal(h.snapshots.at(-1).phase,'ready');
});

test('failed refresh preserves prior evidence but cannot use it for clear and later unlock is authoritative', async () => {
  let fail=false;
  const h=harness(fixture(),{request:async()=>{if(fail)throw new Error('refresh failed');}});
  await h.session.check();const previous=h.snapshots.at(-1);fail=true;await h.session.check();
  assert.equal(h.snapshots.at(-1).phase,'error');assert.equal(h.snapshots.at(-1).lock,previous.lock);
  assert.match(h.snapshots.at(-1).error,/refresh failed/);await h.session.act('clear');
  assert.ok(!h.calls.some(c=>c.approved));fail=false;h.data.lock.state='unlocked';h.data.run.execution_control.lock_state='unlocked';
  await h.session.check();assert.equal(h.snapshots.at(-1).error,'');
  assert.equal(runLockAction(h.snapshots.at(-1).run,h.snapshots.at(-1).lock),undefined);
});

// Run the actual component hooks and effects so refreshKey changes exercise the owner lifecycle.
function noticeHost(api, initial={}) {
  const slots=[];let cursor=0,changed=false,effects=[],tree;
  let props={projectName:'project',runId:'group',active:true,refreshKey:'1',onUpdated(){},onInspect(){},...initial};
  const same=(a,b)=>a&&b&&a.length===b.length&&a.every((value,index)=>Object.is(value,b[index]));
  const react={
    useState(value){const index=cursor++;if(!(index in slots))slots[index]=value;return[slots[index],update=>{
      const next=typeof update==='function'?update(slots[index]):update;if(!Object.is(slots[index],next)){slots[index]=next;changed=true;}
    }];},
    useRef(value){const index=cursor++;return slots[index]||=( {current:value} );},
    useEffect(effect,deps){const index=cursor++;if(same(slots[index]?.deps,deps))return;
      effects.push(()=>{slots[index]?.cleanup?.();slots[index]={deps,cleanup:effect()};});},
  };
  const file=join(output,'renderer/src/RunLockNotice.js');const exported={};const localRequire=createRequire(file);
  runInNewContext(readFileSync(file,'utf8'),{exports:exported,require:name=>name==='react'?react:localRequire(name),window:{orchestrator:api}});
  const render=(changes={},flushEffects=true)=>{
    props={...props,...changes};
    for(let turn=0;turn<20;turn++){
      cursor=0;changed=false;effects=[];tree=exported.RunLockNotice(props);
      if(!flushEffects)return tree;
      effects.forEach(effect=>effect());if(!changed)return tree;
    }
    assert.fail('notice did not settle');
  };
  return {render,async flush(){await new Promise(resolve=>setImmediate(resolve));return render();}};
}
function nodes(tree){if(!tree||typeof tree!=='object')return[];
  if(Array.isArray(tree))return tree.flatMap(nodes);return[tree,...nodes(tree.props?.children)];}
const notice=tree=>nodes(tree).find(node=>node.props.className==='run-lock-notice');
const noticeButton=tree=>nodes(notice(tree)).find(node=>node.type==='button');

test('compact header notices preserve explicit recovery and closed diagnostics through refresh and read failure', async () => {
  let fail = false;
  const h = harness(fixture(), { request: async () => { if (fail) throw Error('lock diagnostic'); } });
  const ui = noticeHost(h.api, { compact: true });
  ui.render(); let tree = await ui.flush();
  assert.equal(notice(tree).props['data-compact'], true);
  assert.equal(noticeButton(tree).props.children, '잠금 해제');
  const details = nodes(notice(tree)).find(node => node.type === 'details');
  assert.equal(details.props.open, undefined);
  assert.ok(nodes(details).some(node => node.type === 'summary' && node.props.children === '상세'));
  assert.ok(nodes(details).some(node => node.type === 'p' && node.props.children === '잠금만 해제 · 작업은 재개하지 않음'));
  fail = true; ui.render({ refreshKey: 'failed' }); tree = await ui.flush();
  assert.equal(notice(tree).props.role, 'alert');
  assert.equal(noticeButton(tree).props.children, '다시 확인');
  assert.ok(nodes(tree).some(node => node.type === 'pre' && node.props.children.includes('lock diagnostic')));
  assert.ok(h.calls.every(call => ['runs.get', 'locks.get'].includes(call.method)));
});

test('active lock progress owns one status while preserving stop, records, refresh stability and error distinctions', async () => {
  let fail=false,hold=false,release;const reports=[];
  const h=harness(fixture('active'),{request:async method=>{
    if(fail)throw new Error('progress lookup failed');
    if(hold&&method==='runs.get'){hold=false;return new Promise(resolve=>{release=resolve;});}
  }});
  const ui=noticeHost(h.api,{onBlocking:(blocking,progress)=>reports.push({blocking,progress})});
  ui.render();let tree=await ui.flush();
  assert.deepEqual(reports.at(-1),{blocking:false,progress:true});
  assert.equal(noticeButton(tree).props.children,'작업 중지');
  assert.equal(nodes(notice(tree)).filter(n=>n.type==='summary'&&n.props.children==='잠금 기록').length,1);
  reports.length=0;hold=true;tree=ui.render({refreshKey:'2'});
  assert.ok(notice(tree));assert.equal(noticeButton(tree).props.disabled,true);assert.deepEqual(reports,[]);
  release(copy(h.data.run));await ui.flush();
  ui.render({activeOnCards:true});
  assert.equal(notice(await ui.flush()),undefined);assert.deepEqual(reports.at(-1),{blocking:false,progress:false});
  ui.render({activeOnCards:false});await ui.flush();
  h.data.run.execution_control.stop_phase='stopping';ui.render({refreshKey:'3'});tree=await ui.flush();
  assert.equal(noticeButton(tree).props.children,'다시 확인');assert.deepEqual(reports.at(-1),{blocking:true,progress:true});
  fail=true;ui.render({refreshKey:'4'});tree=await ui.flush();
  assert.equal(notice(tree).props.role,'alert');assert.deepEqual(reports.at(-1),{blocking:true,progress:false});
  fail=false;h.data.lock.state='unlocked';h.data.run.execution_control.lock_state='unlocked';ui.render({refreshKey:'5'});
  assert.equal(notice(await ui.flush()),undefined);assert.deepEqual(reports.at(-1),{blocking:false,progress:false});
  assert.ok(h.calls.every(c=>!c.approved&&['runs.get','locks.get'].includes(c.method)));
});

test('a matching dedicated progress card suppresses only the generic live notice while errors and other locks remain visible', async () => {
  for(const operation of ['verify','verify-and-repair','merge','push','retry-main-push']) {
    let fail=false,hold=false,release; const reports=[];
    const data=fixture('active');data.lock.operation=operation;data.run.execution_control.operation=operation;
    const h=harness(data,{request:async method=>{
      if(fail)throw Error('lock read failed');
      if(hold&&method==='runs.get'){hold=false;return new Promise(resolve=>{release=resolve})}
    }});
    const ui=noticeHost(h.api,{progressOperation:operation,onBlocking:(blocking,progress)=>reports.push({blocking,progress})});
    ui.render();assert.equal(notice(await ui.flush()),undefined);
    assert.deepEqual(reports.at(-1),{blocking:false,progress:false});
    hold=true;assert.equal(notice(ui.render({refreshKey:'poll'})),undefined,'a pending refresh does not duplicate progress');
    release(copy(h.data.run));assert.equal(notice(await ui.flush()),undefined);
    assert.ok(notice(ui.render({progressOperation:'other'})),'another operation is not covered');
    ui.render({progressOperation:operation});fail=true;ui.render({refreshKey:'failed'});
    const failed=notice(await ui.flush());assert.ok(failed);assert.equal(failed.props.role,'alert');
    assert.equal(noticeButton(failed).props.children,'다시 확인');
    fail=false;h.data.lock.state='stale';h.data.run.execution_control.lock_state='stale';
    ui.render({refreshKey:'stale'});assert.ok(notice(await ui.flush()));
    assert.equal(noticeButton(await ui.flush()).props.children,'잠금 해제');
    assert.ok(h.calls.every(c=>!c.approved&&['runs.get','locks.get'].includes(c.method)));
  }
  const h=harness(fixture('active',{integration_control:{reason_code:'main_apply_interrupted'}}));
  const ui=noticeHost(h.api,{progressOperation:'execute'});ui.render();
  assert.equal(noticeButton(await ui.flush()).props.children,'원본 상태 확인');
});

test('stale, unknown, foreign and interrupted-main notices never claim normal progress', async () => {
  for(const [state,changes] of [['stale',{}],['unverifiable',{}],['active',{integration_control:{reason_code:'main_apply_interrupted'}}]]){
    const reports=[];const h=harness(fixture(state,changes));
    const ui=noticeHost(h.api,{onBlocking:(blocking,progress)=>reports.push({blocking,progress})});
    ui.render();assert.ok(notice(await ui.flush()));assert.deepEqual(reports.at(-1),{blocking:true,progress:false});
    const immediate=ui.render({projectName:'different'},false);assert.equal(notice(immediate),undefined);
  }
});

test('actual notice refresh keeps its owner, banner and blocking while the status read is pending', async () => {
  let hold=false,release;const blocking=[];
  const h=harness(fixture('active',{execution_control:{situation:'running',lock_state:'active',operation:'execute',can_stop:false}}),{
    request:async method=>{if(hold&&method==='runs.get'){hold=false;return new Promise(resolve=>{release=resolve;});}}
  });
  const ui=noticeHost(h.api,{onBlocking:value=>blocking.push(value)});ui.render();let tree=await ui.flush();
  assert.ok(notice(tree));assert.equal(blocking.at(-1),true);blocking.length=0;hold=true;
  tree=ui.render({refreshKey:'2'});assert.ok(notice(tree));assert.equal(notice(tree).props['aria-busy'],true);
  assert.equal(noticeButton(tree).props.disabled,true);assert.deepEqual(blocking,[]);
  const count=h.calls.length;tree=ui.render({refreshKey:'3'});assert.ok(notice(tree));assert.equal(h.calls.length,count);
  noticeButton(tree).props.onClick();assert.equal(h.calls.length,count);
  release(copy(h.data.run));tree=await ui.flush();assert.ok(notice(tree));assert.equal(noticeButton(tree).props.disabled,false);
  assert.deepEqual(blocking,[]);assert.ok(!h.calls.some(call=>call.approved));
});

test('actual notice exposes refresh after failure and never enables the cached clear action', async () => {
  let fail=false;
  const h=harness(fixture(),{request:async()=>{if(fail)throw new Error('query failed');}});
  const updated=[];const ui=noticeHost(h.api,{onUpdated:run=>updated.push(run.id)});ui.render();let tree=await ui.flush();
  assert.equal(noticeButton(tree).props.children,'잠금 해제');fail=true;ui.render({refreshKey:'2'});tree=await ui.flush();
  assert.ok(notice(tree));assert.equal(notice(tree).props.role,'alert');assert.equal(noticeButton(tree).props.children,'다시 확인');
  fail=false;h.data.lock.state='unlocked';h.data.run.execution_control.lock_state='unlocked';noticeButton(tree).props.onClick();
  tree=ui.render();assert.equal(noticeButton(tree).props.children,'다시 확인');assert.equal(noticeButton(tree).props.disabled,true);
  tree=await ui.flush();assert.equal(notice(tree),undefined);assert.deepEqual(updated,['group']);assert.ok(!h.calls.some(c=>c.approved));
});

test('same group id in another project cannot show old evidence and deactivation ignores late reads', async () => {
  let hold=false,release;const h=harness(fixture(),{request:async method=>{
    if(hold&&method==='runs.get'){hold=false;return new Promise(resolve=>{release=resolve;});}
  }});
  const ui=noticeHost(h.api);ui.render();assert.ok(notice(await ui.flush()));
  assert.equal(notice(ui.render({projectName:'other'},false)),undefined);
  ui.render();await ui.flush();hold=true;ui.render({refreshKey:'2'});ui.render({active:false});
  release(copy(h.data.run));assert.equal(notice(await ui.flush()),undefined);
  assert.ok(!h.calls.some(c=>c.approved));
});

test('error retry without a previous lock action retains its button and blocking until a confirmed read', async () => {
  let fail=false,hold=false,release;const blocking=[];
  const h=harness(fixture('unlocked'),{request:async method=>{
    if(fail)throw new Error('query failed');
    if(hold&&method==='runs.get'){hold=false;return new Promise(resolve=>{release=resolve;});}
  }});
  const ui=noticeHost(h.api,{onBlocking:value=>blocking.push(value)});ui.render();assert.equal(notice(await ui.flush()),undefined);
  fail=true;ui.render({refreshKey:'2'});let tree=await ui.flush();
  assert.equal(noticeButton(tree).props.children,'다시 확인');assert.equal(blocking.at(-1),true);blocking.length=0;
  fail=false;hold=true;noticeButton(tree).props.onClick();tree=ui.render();
  assert.ok(notice(tree));assert.equal(noticeButton(tree).props.children,'다시 확인');assert.equal(noticeButton(tree).props.disabled,true);
  assert.deepEqual(blocking,[]);release(copy(h.data.run));tree=await ui.flush();
  assert.equal(notice(tree),undefined);assert.deepEqual(blocking,[false]);assert.ok(!h.calls.some(c=>c.approved));
});

test('refreshKey changes during explicit approval preserve the same owner and completion receipt', async () => {
  let release;const h=harness(fixture(),{approve:async()=>new Promise(resolve=>{release=resolve;})});
  const updated=[];const ui=noticeHost(h.api,{onUpdated:run=>updated.push(run.id)});ui.render();let tree=await ui.flush();
  noticeButton(tree).props.onClick();await new Promise(resolve=>setImmediate(resolve));
  assert.ok(release);const count=h.calls.length;tree=ui.render({refreshKey:'2'});
  assert.ok(notice(tree));assert.equal(noticeButton(tree).props.disabled,true);assert.equal(h.calls.length,count);
  h.data.lock.state='unlocked';h.data.run.execution_control.lock_state='unlocked';release(copy(h.data.lock));
  tree=await ui.flush();assert.ok(notice(tree));assert.deepEqual(updated,['group']);
  assert.equal(h.calls.filter(c=>c.approved).length,1);
  assert.ok(nodes(tree).some(node=>node.type==='p'&&node.props.children==='잠금 해제됨'));
});

test('opening a group only reads its current lock and original-apply state', async () => {
  const h = harness(); await h.session.check();
  assert.deepEqual(h.calls.map(c => c.method), ['runs.get', 'locks.get', 'runs.get']);
  assert.ok(h.calls.every(c => c.params.projectName === 'selected-project' && c.params.runId === 'group'));
  assert.equal(runLockAction(h.snapshots.at(-1).run, h.snapshots.at(-1).lock).kind, 'clear');
});

test('an explicit clear rechecks the same target, uses approval once, refreshes, and never resumes or applies', async () => {
  const h = harness(); await h.session.check(); await h.session.act('clear');
  const mutations = h.calls.filter(c => !['runs.get', 'locks.get'].includes(c.method));
  assert.deepEqual(mutations, [{ method: 'locks.clear', params: { projectName: 'selected-project', runId: 'group' }, approved: true }]);
  assert.deepEqual(h.calls.slice(-3).map(c => c.method), ['runs.get', 'locks.get', 'runs.get']);
  assert.equal(h.snapshots.at(-1).message, '잠금 해제됨'); assert.equal(h.snapshots.at(-1).lock.state, 'unlocked');
});

test('active, unverifiable, malformed, unknown and sidecar locks cannot use clear', async () => {
  for (const state of ['active', 'unverifiable', 'malformed', 'unknown', 'unlocked']) {
    const h = harness(fixture(state)); await h.session.check(); await h.session.act('clear');
    assert.ok(!h.calls.some(c => c.approved));
  }
  for (const operation of ['planning-chat', 'planning-preview', 'effort-policy', '']) {
    const data = fixture(); data.lock.operation = operation; data.run.execution_control.operation = operation;
    const h = harness(data); await h.session.check(); await h.session.act('clear');
    assert.equal(runLockAction(data.run, data.lock).kind, 'refresh'); assert.ok(!h.calls.some(c => c.approved));
  }
});

test('interrupted original application opens its existing inspection rather than clearing the run lock', async () => {
  for (const changes of [
    { integration_control: { reason_code: 'main_apply_interrupted' } },
    { integration_control: { reason_code: 'main_apply_recoverable', can_recover_main_apply: true } },
    { main_operations: { merge: { status: 'running', phase: 'applying_main' } } },
  ]) {
    const h = harness(fixture('stale', changes)); await h.session.check(); await h.session.act('clear');
    assert.equal(runLockAction(h.data.run, h.data.lock).kind, 'inspect'); assert.ok(!h.calls.some(c => c.approved));
  }
});

test('state, owner, group revision and interrupted original changes after display prevent approval', async () => {
  for (const mutate of [
    h => { h.data.lock.state = 'active'; h.data.run.execution_control.lock_state = 'active'; },
    h => { h.data.lock.reason = 'owner process 99 is not running'; },
    h => { h.data.run.updated_at = '2026-10-10T00:01:00Z'; },
    h => { h.data.run.integration_control = { reason_code: 'main_apply_interrupted' }; },
    h => { h.data.lock.operation = 'effort-policy'; h.data.run.execution_control.operation = 'effort-policy'; },
  ]) {
    const h = harness(); await h.session.check(); mutate(h); await h.session.act('clear');
    assert.ok(!h.calls.some(c => c.approved)); assert.match(h.snapshots.at(-1).message, /상태가 바뀌어/);
  }
});

test('approval cancellation preserves the lock and does not report success', async () => {
  const h = harness(fixture(), { approve: async () => null }); await h.session.check(); await h.session.act('clear');
  assert.equal(h.data.lock.state, 'stale'); assert.equal(h.snapshots.at(-1).message, '잠금 해제를 취소했습니다');
  assert.ok(!h.calls.some(c => ['runs.resume', 'tasks.retry', 'runs.merge'].includes(c.method)));
});

test('clear failure and a failed status refresh remain explicit and cannot enable a stale action', async () => {
  const h = harness(fixture(), { approve: async () => { throw new Error('owner changed before clear'); } });
  await h.session.check(); await h.session.act('clear');
  assert.equal(h.snapshots.at(-1).message, '잠금 해제 실패'); assert.match(h.snapshots.at(-1).error, /owner changed/);
  let failed = false;
  const second = harness(fixture(), { request: async () => { if (failed) throw new Error('status unavailable'); },
    approve: async () => { failed = true; return { run_id: 'group', state: 'unlocked' }; } });
  await second.session.check(); await second.session.act('clear');
  assert.equal(second.snapshots.at(-1).phase, 'error'); assert.match(second.snapshots.at(-1).error, /status unavailable/);
  assert.notEqual(second.snapshots.at(-1).message, '잠금 해제됨');
  const count = second.calls.length; await second.session.act('clear'); assert.equal(second.calls.length, count);
});

test('different groups are queried and cleared separately', async () => {
  const first = harness(); const second = harness(fixture('stale', { id: 'second' }));
  await Promise.all([first.session.check(), second.session.check()]); await second.session.act('clear');
  assert.ok(first.calls.every(c => !c.approved && c.params.runId === 'group'));
  assert.ok(second.calls.every(c => c.params.runId === 'second')); assert.equal(first.data.lock.state, 'stale');
});

test('navigation during the fresh read discards late results and never opens approval for the old group', async () => {
  let release; let hold = false;
  const h = harness(fixture(), { request: async method => {
    if (hold && method === 'runs.get') return new Promise(resolve => { release = resolve; });
  } });
  await h.session.check(); hold = true; const acting = h.session.act('clear');
  const count = h.snapshots.length; h.session.dispose(); release(copy(h.data.run)); await acting;
  assert.equal(h.snapshots.length, count); assert.ok(!h.calls.some(c => c.approved));
});

test('navigation while an explicitly targeted approval is pending never publishes into the new context', async () => {
  let release; const h = harness(fixture(), { approve: async () => new Promise(resolve => { release = resolve; }) });
  await h.session.check(); const acting = h.session.act('clear');
  while (!release) await new Promise(resolve => setImmediate(resolve));
  const count = h.snapshots.length; h.session.dispose(); release({ run_id: 'group', state: 'unlocked' }); await acting;
  assert.equal(h.snapshots.length, count); assert.equal(h.calls.filter(c => c.approved).length, 1);
});

test('owner control only permits the existing task stop with its execution and attempt identifiers', async () => {
  const h = harness(fixture('active')); await h.session.check(); await h.session.act('stop');
  const stop = h.calls.find(c => c.method === 'runs.requestStop');
  assert.equal(stop.params.scope, 'task'); assert.equal(stop.params.taskId, 'active'); assert.equal(stop.params.executionId, 'execution');
  assert.equal(stop.params.attemptId, 'attempt'); assert.equal(stop.params.invocationId, 'invocation');
  assert.ok(!h.calls.some(c => c.approved)); assert.match(h.snapshots.at(-1).message, /중지를 요청/);
  for (const changes of [{ can_stop: false }, { execution_id: '' }, { stop_phase: 'stopping' }, { active_task_id: 'missing-task' }]) {
    const data = fixture('active'); Object.assign(data.run.execution_control, changes); const blocked = harness(data);
    await blocked.session.check(); await blocked.session.act('stop'); assert.ok(!blocked.calls.some(c => c.method === 'runs.requestStop'));
  }
});

test('failed, wrong-target and inconsistent reads retain a retryable error instead of an actionable old snapshot', async () => {
  for (const request of [
    async () => { throw new Error('query failed'); },
    async method => method === 'locks.get' ? { run_id: 'foreign', state: 'stale' } : undefined,
    async method => method === 'locks.get' ? { run_id: 'group', state: 'active', operation: 'execute' } : undefined,
  ]) {
    const h = harness(fixture(), { request }); await h.session.check(); const before = h.calls.length; await h.session.act('clear');
    assert.equal(h.snapshots.at(-1).phase, 'error'); assert.ok(h.snapshots.at(-1).error); assert.equal(h.calls.length, before);
    assert.equal(h.snapshots.at(-1).lock, undefined);
  }
});

test('repeated clicks while approval is pending produce only one explicit mutation', async () => {
  let release; const h = harness(fixture(), { approve: async () => new Promise(resolve => { release = resolve; }) });
  await h.session.check(); const first = h.session.act('clear'); await h.session.act('clear'); await h.session.check();
  while (!release) await new Promise(resolve => setImmediate(resolve));
  h.data.lock.state = 'unlocked'; h.data.run.execution_control.lock_state = 'unlocked'; release(copy(h.data.lock)); await first;
  assert.equal(h.calls.filter(c => c.approved).length, 1);
});
