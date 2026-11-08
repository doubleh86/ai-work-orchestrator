const {test}=require('node:test');
const assert=require('node:assert/strict');
const {mkdirSync,mkdtempSync,readFileSync,rmSync}=require('node:fs');
const {dirname,join,resolve}=require('node:path');
const {createRequire}=require('node:module');
const {execFileSync}=require('node:child_process');
const {runInNewContext}=require('node:vm');
const {renderToStaticMarkup}=require('react-dom/server');
const root=resolve(__dirname,'../..'),temp=join(root,'.tmp');
mkdirSync(temp,{recursive:true});const output=mkdtempSync(join(temp,'claude-connection-test-'));
process.on('exit',()=>{assert.equal(dirname(output),temp);rmSync(output,{recursive:true,force:true})});
const pkg=require.resolve('typescript/package.json',{paths:[root]});
execFileSync(process.execPath,[resolve(dirname(pkg),require(pkg).bin.tsc),'--ignoreConfig','--strict','--target','ES2022',
  '--module','commonjs','--jsx','react-jsx','--skipLibCheck','--outDir',output,
  'desktop/renderer/src/ClaudeConnectionPanel.tsx','desktop/renderer/src/global.d.ts'],{cwd:root,stdio:'inherit'});
const modulePath=join(output,'renderer/src/ClaudeConnectionPanel.js'),local=createRequire(modulePath);
const connected=extra=>({installed:true,authenticated:true,auth_method:'claude_subscription',message:'Claude Pro 구독 로그인',
  account_email:'claude@example.test',plan_type:'pro',...extra});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function nodes(tree){if(!tree||typeof tree!=='object')return [];return Array.isArray(tree)?tree.flatMap(nodes):[tree,...nodes(tree.props?.children)]}
function text(tree){if(typeof tree==='string'||typeof tree==='number')return String(tree);return Array.isArray(tree)?tree.map(text).join(''):text(tree?.props?.children||'')}
const button=(tree,label)=>nodes(tree).find(node=>node.type==='button'&&text(node)===label);
function harness(extra={}){
  let cursor=0,props={visible:true,...extra};const slots=[],effects=[],scheduled=[],calls=[],statuses=[],continued=[];
  const api={request(method){return new Promise((resolve,reject)=>calls.push({method,resolve,reject}))},
    openClaudeLogin(){return new Promise((resolve,reject)=>calls.push({method:'login',resolve,reject}))}};
  const hooks={useState(initial){const index=cursor++;if(!(index in slots))slots[index]=initial;return [slots[index],value=>{slots[index]=typeof value==='function'?value(slots[index]):value}]},
    useRef(initial){const index=cursor++;return slots[index]||=( {current:initial})},
    useEffect(callback,deps){const index=cursor++,previous=effects[index];if(!previous||deps.some((value,i)=>value!==previous.deps[i])){
      effects[index]={deps,cleanup:previous?.cleanup};scheduled.push(()=>{effects[index].cleanup?.();effects[index].cleanup=callback()})}}};
  const exports={};runInNewContext(readFileSync(modulePath,'utf8'),{exports,window:{orchestrator:api},require:name=>name==='react'?hooks:local(name)});
  return {calls,statuses,continued,details:exports.claudeAccountDetails,
    render(patch={}){props={...props,...patch};cursor=0;const tree=exports.ClaudeConnectionPanel({onStatusChange:value=>statuses.push(value),onContinue:()=>continued.push(true),...props});for(const effect of scheduled.splice(0))effect();return tree},
    unmount(){for(const effect of effects)effect?.cleanup?.()}};
}
async function load(view,value=connected()) {view.render();view.calls.at(-1).resolve(value);await tick();return view.render()}

test('connected Claude shows continue and keeps account fields and management folded',async()=>{
  const view=harness(),tree=await load(view),markup=renderToStaticMarkup(tree);
  for(const label of ['현재 계정','로그인 방식','요금제','claude@example.test','Claude 구독 로그인','Pro'])assert.ok(markup.includes(label));
  assert.ok(nodes(tree).some(node=>node.props.className==='ai-auth-state'&&node.props['data-state']==='connected'));
  const details=nodes(tree).find(node=>node.type==='details');
  assert.ok(nodes(details).some(node=>node.type==='dl'&&node.props.className==='ai-account-details'));
  assert.notEqual(details.props.open,true);
  const footer=nodes(tree).find(node=>node.type==='footer');
  assert.deepEqual(nodes(footer).filter(node=>node.type==='button').map(text),['계속하기']);
  assert.equal(view.statuses.at(-1).account_email,'claude@example.test');
  assert.deepEqual(view.calls.map(call=>call.method),['auth.claude.status']);
  button(tree,'계속하기').props.onClick();assert.deepEqual(view.continued,[true]);view.unmount();
});

test('old backends, missing account data and API authentication never invent a subscription account',async()=>{
  const view=harness();
  for(const data of [connected({account_email:undefined,plan_type:undefined}),connected({auth_method:'api_key'}),connected({auth_method:'external'})]){
    const details=view.details(data);
    if(data.auth_method==='claude_subscription') {assert.match(details.email,/제공되지/);assert.match(details.plan,/제공되지/)}
    else {assert.doesNotMatch(details.email,/claude@example/);assert.match(details.plan,/제공되지/)}
  }
  assert.equal(view.details(connected({authenticated:null})),undefined);
  assert.equal(view.details(connected({authenticated:false})),undefined);view.unmount();
});

test('refresh failures and logout clear the displayed account and update the provider card',async()=>{
  const view=harness();let tree=await load(view);
  button(tree,'연결 다시 확인').props.onClick();tree=view.render();
  assert.equal(nodes(tree).some(node=>node.type==='dl'),false,'old account is hidden during a check');
  view.calls.at(-1).reject(new Error('공개 상태 조회 실패'));await tick();tree=view.render();
  assert.equal(nodes(tree).some(node=>node.type==='dl'),false);assert.equal(view.statuses.at(-1),null);
  assert.match(renderToStaticMarkup(tree),/연결 확인 실패/);
  button(tree,'연결 다시 확인').props.onClick();view.calls.at(-1).resolve(connected({authenticated:false,auth_method:'none',message:'로그인 필요'}));
  await tick();tree=view.render();assert.equal(view.statuses.at(-1).authenticated,false);
  assert.equal(nodes(tree).some(node=>node.type==='dl'),false);assert.ok(button(tree,'Claude로 로그인'));view.unmount();
});

test('late checks after leaving the panel do not replace a newer account or start login',async()=>{
  const view=harness();view.render();const old=view.calls[0];view.render({visible:false});view.render({visible:true});
  const current=view.calls.at(-1);assert.notEqual(current,old);
  current.resolve(connected({account_email:'new@example.test'}));await tick();view.render();
  old.resolve(connected({account_email:'old@example.test'}));await tick();
  const markup=renderToStaticMarkup(view.render());assert.match(markup,/new@example.test/);assert.doesNotMatch(markup,/old@example.test/);
  assert.equal(view.statuses.length,1);assert.deepEqual(view.calls.map(call=>call.method),['auth.claude.status','auth.claude.status']);view.unmount();
});

test('login starts only once on an explicit click and a model refresh error keeps the confirmed connection',async()=>{
  const view=harness({onChanged:async()=>{throw Error('model list failure')}});let tree=await load(view);
  assert.match(renderToStaticMarkup(tree),/연결 상태는 확인했지만 모델 목록/);
  assert.match(renderToStaticMarkup(tree),/claude@example.test/);assert.equal(view.statuses.at(-1).authenticated,true);
  const manage=button(tree,'로그인 관리');manage.props.onClick();manage.props.onClick();
  button(tree,'연결 다시 확인').props.onClick();assert.equal(view.calls.filter(call=>call.method==='login').length,1);
  assert.equal(view.calls.filter(call=>call.method==='auth.claude.status').length,1);
  view.calls.at(-1).resolve(true);await tick();tree=view.render();assert.match(renderToStaticMarkup(tree),/로그인 터미널을 열었습니다/);view.unmount();
});

test('malformed account replies cannot crash rendering or leave a previous connected identity',async()=>{
  const view=harness();let tree=await load(view);button(tree,'연결 다시 확인').props.onClick();
  view.calls.at(-1).resolve(connected({account_email:{unexpected:'object'}}));await tick();tree=view.render();
  assert.equal(view.statuses.at(-1),null);assert.equal(nodes(tree).some(node=>node.type==='dl'),false);
  assert.match(renderToStaticMarkup(tree),/응답을 확인하지 못했습니다/);view.unmount();
});
