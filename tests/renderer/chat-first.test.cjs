const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, mkdirSync, rmSync, readFileSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');
const { renderToStaticMarkup } = require('react-dom/server');
const root = resolve(__dirname, '../..'), temp = join(root, '.tmp');
mkdirSync(temp, { recursive: true });
const output = mkdtempSync(join(temp, 'chat-first-test-'));
process.on('exit', () => { assert.equal(dirname(output), temp); rmSync(output, { force: true, recursive: true }); });
const ts = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(ts), require(ts).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022', '--module', 'Node16', '--types', 'node', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
  'desktop/renderer/src/ChatHome.tsx', 'desktop/renderer/src/ChatWorkActivity.tsx', 'desktop/renderer/src/ChatProjectNavigation.tsx', 'desktop/renderer/src/failedTaskQuestionDrafts.ts', 'desktop/main/claudeLogin.ts'], { cwd: root, stdio: 'inherit' });
const { currentChatFailure, ChatWorkActivity, ChatWorkStatus } = require(join(output, 'renderer/src/ChatWorkActivity.js'));
const { ChatProjectNavigation } = require(join(output, 'renderer/src/ChatProjectNavigation.js'));
const { ChatHome } = require(join(output, 'renderer/src/ChatHome.js'));
const { FailedTaskQuestionDrafts } = require(join(output, 'renderer/src/failedTaskQuestionDrafts.js'));
const run = changes => ({ id: 'group', stage: 'failed', tasks: [{ id: 'one', title: '작업', status: 'failed', error: 'raw command error' }], events: [], ...changes });
const activity = value => renderToStaticMarkup(ChatWorkActivity({ run: value, busy: false, repairing: false,
  onAction() { assert.fail('render must not perform an action'); }, onDiscuss() {}, onTasks() {} }));

test('unconfirmed engine connection never presents an empty registry or project creation actions', () => {
  for (const connection of ['connecting', 'unavailable']) for (const projects of [[], [{ name: '기존 프로젝트' }]]) {
    let retries=0;
    const tree=ChatHome({projects,connection,choosing:false,onRetry(){retries++},onNew(){assert.fail('new project')},
      onRegister(){assert.fail('registration')},onCreate(){assert.fail('creation')},onConnect(){assert.fail('AI login')},onCancel(){}});
    const html=renderToStaticMarkup(tree);
    assert.match(html,/role="status"/);
    assert.doesNotMatch(html,/무엇을 함께 만들까요|AI 연결|기존 프로젝트 열기|새 프로젝트|새 대화/);
    const buttons=Array.isArray(tree.props.children)?tree.props.children.filter(item=>item?.type==='button'):[];
    assert.equal(buttons.length,connection==='unavailable'?1:0);
    if (buttons.length) { buttons[0].props.onClick(); assert.equal(retries,1); }
  }
  const html=renderToStaticMarkup(ChatHome({projects:[],choosing:false,onNew(){},onRegister(){},onCreate(){},onConnect(){},onCancel(){}}));
  assert.match(html,/새 프로젝트/,'a confirmed empty registry keeps its onboarding actions');
});

test('project names with spaces preserve unique accessible conversation disclosure targets', () => {
  const React = require('react');
  const html = renderToStaticMarkup(React.createElement(ChatProjectNavigation, { projects: [{name:'Sample Project A'}, {name:'한글 프로젝트'}],
    cache: {}, projectName: 'Sample Project A', onProject() {}, onOpen() {}, onNew() {}, onHistory() {} }));
  const targets = [...html.matchAll(/aria-controls="([^"]+)"/g)].map(match => match[1]);
  assert.equal(new Set(targets).size, 2);
  for (const target of targets) { assert.doesNotMatch(target, /\s/); assert.ok(html.includes(`id="${target}"`)); }
  assert.match(html, /Sample Project A에서 새 대화/);
});

test('chat attaches only a settled failed Task and preserves the original error', () => {
  assert.equal(currentChatFailure(run()).id, 'one');
  assert.equal(currentChatFailure(run({ active_step: 'planning' })), undefined);
  assert.equal(currentChatFailure(run({ tasks: [...run().tasks, { id: 'two', status: 'running' }] })), undefined);
  const html = activity(run());
  assert.match(html, /오류 상세/); assert.match(html, /raw command error/); assert.doesNotMatch(html, /<details open/);
  assert.match(html, /원인 물어보기/); assert.doesNotMatch(html, /다시 실행|작업 중지/);
});

test('recorded automatic repair never invents a new retry or hides an exhausted failure', () => {
  const repairing = run({ stage: 'executing', tasks: [{ id: 'one', title: '현재 작업', status: 'revising' }],
    events: [{ kind: 'task_repair', message: 'one 검증 실패를 자동 수정합니다 · 2/3' }] });
  assert.match(activity(repairing), /자동 수정 시도 2\/3/);
  assert.match(activity(run({ events: repairing.events })), /작업이 멈췄어요/);
  assert.equal(ChatWorkActivity({ run: repairing, repairing: true }), null, 'manual recovery already owns its progress notice');
});

test('completed tasks use the top status without repeating a chat result or application card', () => {
  const completed = run({ stage: 'ready_to_merge', tasks: [{ id: 'one', status: 'completed' }] });
  for (const stage of ['ready_to_merge', 'verified', 'work_branch_pushed', 'merged', 'pushed', 'deployed']) {
    assert.equal(activity({...completed, stage}), '');
  }
  const failure = activity({...completed, stage:'failed', failure_message:'verification command failed'});
  assert.match(failure, /verification command failed/);
  assert.match(failure, /오류 상세/);
  const html = renderToStaticMarkup(ChatWorkStatus({ run: completed, action: { status: '검증 필요', tone: 'warning' } }));
  assert.match(html, /검증 필요/); assert.match(html, /1\/1 완료/); assert.doesNotMatch(html, /<button/);
});

test('automatic diagnostic cache does not prepare or edit a user draft', () => {
  const drafts = new FailedTaskQuestionDrafts();
  drafts.cacheDiagnostic('p', 'g', 'failed-source', 'original diagnostic');
  assert.equal(drafts.diagnostic('p', 'g', 'failed-source'), 'original diagnostic');
  assert.equal(drafts.diagnostic('p', 'g', 'new-attempt'), '');
  assert.equal(drafts.prepare('p', 'g', 'explicit-source', 'my question', 'help', 'new diagnostic'), 'my question\n\nhelp');
});

test('archived conversations do not repeat a result card or offer recovery of saved tasks', () => {
  const tree = ChatWorkActivity({run:run({archive:{cleanup_status:'completed'}}),busy:false,repairing:false,
    action:{kind:'operations',label:'반영 내용 확인'},onAction(){assert.fail('archived action');},
    onDiscuss(){assert.fail('archived recovery');},onTasks(){assert.fail('archived execution');}});
  assert.equal(tree,null);
});

test('Claude login exposes only a fixed official command, propagates spawn errors and never requests a shell', async () => {
  const modulePath = join(output, 'main/claudeLogin.js'), local = createRequire(modulePath), exports = {};
  let options, command, child;
  const listeners = new Map();
  runInNewContext(readFileSync(modulePath, 'utf8'), { exports, process: { platform: 'win32' },
    require: name => name === 'node:child_process' ? { spawn(executable, args, opts) {
      command = [executable, args]; options = opts;
      child = { once(event, callback) { listeners.set(event, callback); }, unref() {} }; return child;
    } } : local(name) });
  const pending = exports.openClaudeLogin('isolated-temp');
  assert.equal(command[0], 'powershell.exe'); assert.equal(command[1].at(-1), 'claude auth login');
  assert.equal(options.shell, false); assert.equal(options.windowsHide, false); assert.equal(options.cwd, 'isolated-temp');
  listeners.get('spawn')(); assert.equal(await pending, true);
  const failure = exports.openClaudeLogin('isolated-temp'); listeners.get('error')(new Error('private detail'));
  await assert.rejects(failure, /Claude 로그인 터미널/);
});
