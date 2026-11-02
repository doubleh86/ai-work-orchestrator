const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');
const root = resolve(__dirname, '../..');
const temp = join(root, '.tmp');
mkdirSync(temp, { recursive: true });
const output = mkdtempSync(join(temp, 'planning-dialog-'));
process.on('exit', () => { assert.equal(dirname(output), temp); rmSync(output, { recursive: true, force: true }); });
const ts = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(ts), require(ts).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
  'desktop/renderer/src/App.tsx', 'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });
const path = join(output, 'renderer/src/App.js');
const source = readFileSync(path, 'utf8');
const localRequire = createRequire(path);
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children), ...nodes(tree.props?.footer)];
}
function text(tree) {
  if (typeof tree === 'string' || typeof tree === 'number') return String(tree);
  if (Array.isArray(tree)) return tree.map(text).join('');
  return tree ? text(tree.props?.children) : '';
}
function fixture(changes = {}) {
  let cursor = 0;
  const state = [], calls = [], exports = {};
  const maturity = {kind: 'existing_code', evidence: [{relative_path: 'src/app.ts', evidence_kind: 'source'}],
    inspected_file_count: 1, detected_application_roots: [], diagnostics: [], ignored_roots: []};
  const props = { project: {name: '선택 프로젝트'}, capabilities: {repository_maturity: maturity},
    repositoryIntent: '', path: '', mode: 'directed', request: '', profiles: [{provider_id:'codex',agent_id:'codex',model:'model'}],
    providerStatuses: [{id:'codex',available:true}], selectedProfileKey:'codex\u001fmodel', reasoning:'high', effortMode:'focused',
    profileManual: true, reasoningOptions:['high'], message:'', indexElapsed:0, planningElapsed:0, preparationMessage:'',
    busyAction:'', planDirty:false, draftConflict:false, interruptible:false,
    onStart: () => calls.push('start'), onChoosePath: () => calls.push('choose'), onSavePath: () => calls.push('save'),
    onRefreshIndex: () => calls.push('index'), onOpenCodexAuth: () => calls.push('auth'),
    onModeChange: (mode) => { props.mode = mode; }, onRequestChange: (request) => { props.request = request; },
    onPathChange: (path) => { props.path = path; }, onRepositoryIntentChange: (intent) => { props.repositoryIntent = intent; }, ...changes };
  runInNewContext(`${source}\nexports.Workbench = PlanningWorkbench;`, {exports, require: name => name === 'react' ? {
    ...localRequire(name), useState: initial => { const i = cursor++; if (!(i in state)) state[i] = typeof initial === 'function' ? initial() : initial;
      return [state[i], value => { state[i] = typeof value === 'function' ? value(state[i]) : value; }]; },
    useRef: current => ({current}), useEffect() {}, useLayoutEffect() {},
  } : localRequire(name)});
  const render = () => { cursor = 0; return exports.Workbench(props); };
  const dialog = tree => nodes(tree).find(node => node.props?.className === 'planning-start-dialog');
  const open = () => { nodes(render()).find(node => node.type === 'button' && text(node) === '기획 시작').props.onClick(); return dialog(render()); };
  const generate = tree => nodes(tree).find(node => node.type === 'button' && node.props.className?.includes('planning-start'));
  return {props, calls, render, dialog, open, generate};
}

test('task execution settings mount only when the composer menu opens and keep drafts when it closes', () => {
  const marker = require('react').createElement('div',{'data-task-settings':true},'선택 작업 설정');
  const f = fixture({chatFirst:true,taskSettings:marker});
  let tree = f.render();
  assert.equal(nodes(tree).some(node=>node.props?.['data-task-settings']),false);
  const menu = nodes(tree).find(node=>node.type==='details' && node.props.className==='chat-model-settings');
  menu.props.onToggle({currentTarget:{open:true}});
  tree = f.render();
  assert.equal(nodes(tree).some(node=>node.props?.['data-task-settings']),true);
  nodes(tree).find(node=>node.type==='details' && node.props.className==='chat-model-settings').props.onToggle({currentTarget:{open:false}});
  assert.equal(nodes(f.render()).some(node=>node.props?.['data-task-settings']),true);
  assert.deepEqual(f.calls,[]);
});

test('planning entry opens with missing input/auth/inspection and performs no start, save or indexing', () => {
  for (const changes of [{}, {profiles:[],providerStatuses:[]}, {capabilities:undefined},
    {mode:'auto'}, {busyAction:'runs.start',preparationMessage:'자료 확인 중'}]) {
    const f = fixture(changes);
    assert.equal(f.dialog(f.render()), undefined);
    assert.equal(nodes(f.render()).filter(node => node.type === 'textarea').length, 0);
    const modal = f.open();
    assert.ok(modal);
    assert.equal(f.generate(modal).props.disabled, true);
    modal.props.onClose();
    assert.equal(f.dialog(f.render()), undefined);
    assert.deepEqual(f.calls, []);
  }
});

test('both planning modes preserve drafts and use one explicit generation with optional/required sources', () => {
  const f = fixture({request:'요청 초안',path:'C:\\자료\\긴 폴더',startError:'자료 접근 실패'});
  let modal = f.open();
  assert.match(text(modal.props.footer), /자료 접근 실패/);
  assert.equal(f.generate(modal).props.disabled, false);
  assert.equal(nodes(modal).find(node => node.type === 'textarea').props.value, '요청 초안');
  modal.props.onClose(); modal = f.open();
  assert.equal(nodes(modal).find(node => node.type === 'textarea').props.value, '요청 초안');
  assert.match(text(modal), /설정.*model.*high.*집중/);
  nodes(modal).find(node => node.type === 'input' && node.props.value === 'auto').props.onChange();
  modal = f.dialog(f.render());
  assert.equal(nodes(modal).filter(node => node.type === 'textarea').length, 0);
  assert.equal(f.generate(modal).props.disabled, false);
  f.props.path = ''; assert.equal(f.generate(f.dialog(f.render())).props.disabled, true);
  f.props.path = 'C:\\자료'; f.generate(f.dialog(f.render())).props.onClick();
  assert.deepEqual(f.calls, ['start']);
  assert.equal(f.props.request, '요청 초안');
});

test('ambiguous configuration is resolved inside the dialog and prepared groups remove the creation form', () => {
  const f = fixture({request:'만들 내용'});
  f.props.capabilities.repository_maturity.kind = 'ambiguous';
  let modal = f.open();
  assert.equal(f.generate(modal).props.disabled, true);
  nodes(modal).find(node => node.type === 'input' && node.props.name === 'repository-intent').props.onChange();
  modal = f.dialog(f.render()); assert.equal(f.generate(modal).props.disabled, false);
  f.props.repositoryIntent = 'new_project';
  assert.equal(text(f.generate(f.dialog(f.render()))), '기술 구성 추천받기');
  f.props.run = {id:'prepared',stage:'reviewed',summary:'기획 준비',events:[],planning_messages:[],planning_questions:[],
    planning_follow_up_requests:[],tasks:[]};
  assert.equal(f.dialog(f.render()), undefined);
  assert.match(text(f.render()), /기획 준비가 저장/);
});

test('opening authentication leaves the planning modal without mutating its draft', () => {
  const f = fixture({request:'인증 후 계속할 초안',profiles:[],providerStatuses:[]});
  const modal = f.open();
  nodes(modal).find(node => node.type === 'button' && text(node) === 'ChatGPT로 로그인').props.onClick();
  assert.equal(f.dialog(f.render()), undefined);
  assert.equal(f.props.request, '인증 후 계속할 초안');
  assert.deepEqual(f.calls, ['auth']);
});

test('planning dialog swaps the compact chat modal and restores its DOM, scroll and focus on Escape/close', () => {
  const effects=[],events=[],attrs=new Set();
  class Element {}
  const previous=new Element(); previous.isConnected=true; previous.focus=()=>events.push('focus');
  const sidebar={open:true,isConnected:true,scrollTop:135,draft:'same draft',matches:()=>true,
    setAttribute:name=>attrs.add(name),removeAttribute:name=>attrs.delete(name),
    close(){this.open=false;events.push('chat-close');},showModal(){this.open=true;events.push('chat-modal');},show(){this.open=true;events.push('chat-show');}};
  const dialog={showModal:()=>events.push('start-modal'),close:()=>events.push('start-close')};
  let index=0,closed=0;
  const exports={};
  const file=join(output,'renderer/src/WorkDialog.js');
  runInNewContext(readFileSync(file,'utf8'),{exports,HTMLElement:Element,document:{activeElement:previous,getElementById:()=>sidebar},
    window:{matchMedia:()=>({matches:true})},require:name=>name==='react'?{useRef:()=>({current:index++===0?dialog:null}),useEffect:effect=>effects.push(effect)}:localRequire(name)});
  const tree=exports.WorkDialog({title:'기획',suspendPlanning:true,onClose:()=>closed++,children:'draft'});
  const cleanup=effects[0]();
  assert.deepEqual(events,['chat-close','start-modal']);
  assert.ok(attrs.has('data-planning-start-open'));
  let prevented=0; tree.props.onCancel({preventDefault:()=>prevented++});
  assert.equal(closed,1);assert.equal(prevented,1);
  cleanup();
  assert.deepEqual(events,['chat-close','start-modal','start-close','chat-modal','focus']);
  assert.equal(sidebar.scrollTop,135);assert.equal(sidebar.draft,'same draft');assert.equal(attrs.size,0);
});
