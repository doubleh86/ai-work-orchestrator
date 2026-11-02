const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');
const { renderToStaticMarkup } = require('react-dom/server');
const root = resolve(__dirname, '../..');
const tempRoot = join(root, '.tmp');
mkdirSync(tempRoot, { recursive: true });
const output = mkdtempSync(join(tempRoot, 'work-centered-'));
process.on('exit', () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); });
const ts = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(ts), require(ts).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
  'desktop/renderer/src/WorkOverview.tsx', 'desktop/renderer/src/TaskFlow.tsx', 'desktop/renderer/src/taskContinuation.ts',
  'desktop/renderer/src/App.tsx',
  'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });
const { projectWork, initialWorkBucket } = require(join(output, 'renderer/src/projectWorkPresentation.js'));
const { canContinueTaskRetry } = require(join(output, 'renderer/src/taskContinuation.js'));
const { TaskFlow } = require(join(output, 'renderer/src/TaskFlow.js'));
const { TaskStatusOverview, TaskTechnicalRecord, taskDialogPresentation, TaskDetailSummary } = require(join(output, 'renderer/src/TaskStatusOverview.js'));
const appFile = join(output, 'renderer/src/App.js');
const appComponents = {};
runInNewContext(`${readFileSync(appFile, 'utf8')}\nexports.ApplySummaryEntry = ApplySummaryEntry; exports.PaneResizer = PaneResizer; exports.projectRemovalReason = projectRemovalReason; exports.TaskWorkbench = TaskWorkbench; exports.ProjectNavigation = ProjectNavigation; exports.CurrentWorkNavigation = CurrentWorkNavigation; exports.ApplicationErrorBanner = ApplicationErrorBanner; exports.VerificationFailureNotice = VerificationFailureNotice; exports.VerificationHistory = VerificationHistory; exports.VerificationAttemptRecord = VerificationAttemptRecord; exports.ProjectDialog = ProjectDialog;`, {
  exports: appComponents, require: createRequire(appFile),
});
runInNewContext(`${readFileSync(appFile, 'utf8')}\nexports.runLockConflictOperation = runLockConflictOperation;`, {
  exports: appComponents, require: createRequire(appFile),
});
runInNewContext(`${readFileSync(appFile, 'utf8')}\nexports.TaskDependencyLinks = TaskDependencyLinks; exports.workOverviewHasOperations = workOverviewHasOperations; exports.workOverviewProgressOperation = workOverviewProgressOperation;`, {
  exports: appComponents, require: createRequire(appFile),
});
const operationsComponents = {};
const appRequire = createRequire(appFile);
runInNewContext(`${readFileSync(appFile, 'utf8')}\nexports.OperationsWorkbench = OperationsWorkbench;`, {
  exports: operationsComponents,
  require: (id) => id === 'react' ? { ...appRequire(id), useState: (value) => [value, () => {}], useEffect: () => {} } : appRequire(id),
});
const projects = Array.from({ length: 10 }, (_, i) => ({ name: `Project ${i}` }));

test('automatic task models are concrete before execution and their reason starts closed', () => {
  const task = { id: 'copy', title: '문구 수정', provider_id: 'codex', model: 'gpt-6-luna', reasoning_effort: 'high',
    status: 'pending', profile_source: 'mode', model_selection_reason: '절약 · 명확한 작은 수정', result_history: [], action_results: [] };
  const tree = TaskDetailSummary({ task });
  const markup = renderToStaticMarkup(tree);
  assert.match(markup, /자동 · gpt-6-luna/);
  const reasons = elements(tree, item => item.type === 'details');
  assert.equal(reasons.length, 1); assert.equal(reasons[0].props.open, undefined);
  assert.match(renderToStaticMarkup(reasons[0]), /모델 선택 이유.*절약 · 명확한 작은 수정/);
  assert.doesNotMatch(renderToStaticMarkup(TaskDetailSummary({ task: { ...task, profile_source: 'manual' } })), /모델 선택 이유/);
});
const emptyActive = { items: [], errors: [], checked_at: '' };
const summary = (id, changes = {}) => ({ id, summary: `Work ${id}`, stage: 'planned', attention_reasons: [],
  failed_task_count: 0, completed_task_count: 1, task_count: 5, pipeline_complete: false, execution_situation: 'ready', ...changes });
const snapshot = (groups, error = '') => ({ groups, checkedAt: '2026-10-06T00:00:00Z', error });

test('header project navigation uses a card-selection button with the full current project name', () => {
  let selections = 0;
  for (const projectName of ['', '매우 긴 프로젝트 이름 '.repeat(12)]) {
    const tree = appComponents.ProjectNavigation({ projectName, onSelect: () => selections++ });
    assert.equal(tree.type, 'button'); assert.equal(tree.props.type, 'button');
    assert.equal(tree.props['aria-haspopup'], undefined, 'this navigates to cards rather than opening a dropdown');
    assert.equal(tree.props['aria-label'], projectName ? `현재 프로젝트 ${projectName} · 프로젝트 변경` : '프로젝트 선택');
    assert.doesNotMatch(renderToStaticMarkup(tree), /<select|<option/);
    const actions = elements(tree, (item) => item.props.className === 'project-navigation__action');
    assert.equal(actions.length, 0, 'no duplicate project-change caption');
    if (projectName) {
      const name = elements(tree, (item) => item.props.className === 'project-navigation__name')[0];
      assert.equal(name.props.children, projectName); assert.equal(name.props.title, projectName);
    }
    tree.props.onClick();
  }
  assert.equal(selections, 2);
});

test('Main conflict errors show the next location and preserve the complete RPC error in closed details', () => {
  const message = "Error invoking remote method 'orchestrator:request': PythonBridgeRequestError: application_error: 최신 Main과 7개 파일이 충돌했습니다. Operations에서 AI 해결안을 검토하세요.";
  const tree = appComponents.ApplicationErrorBanner({ message });
  assert.equal(tree.props.role, 'alert');
  const details = elements(tree, (item) => item.type === 'details')[0];
  assert.equal(details.props.open, undefined);
  assert.equal(elements(details, (item) => item.type === 'pre')[0].props.children, message);
  const summary = renderToStaticMarkup(elements(tree, (item) => item.type === 'p')[0]);
  assert.match(summary, /파일 7개/); assert.match(summary, /반영·마무리/);
  assert.doesNotMatch(summary, /PythonBridge|application_error|remote method|Operations/);
});

test('file-lock errors give app-stop guidance while preserving the complete failure in closed details', () => {
  const message = "Error invoking remote method 'orchestrator:request': 실행 중인 앱이 빌드 출력 파일을 사용하고 있어 검증을 완료하지 못했습니다.";
  const tree = appComponents.ApplicationErrorBanner({ message });
  const details = elements(tree, (item) => item.type === 'details')[0];
  assert.equal(details.props.open, undefined);
  assert.equal(elements(details, (item) => item.type === 'pre')[0].props.children, message);
  const summary = renderToStaticMarkup(elements(tree, (item) => item.type === 'p')[0]);
  assert.match(summary, /앱\/서버를 종료/); assert.match(summary, /반영·마무리/);
  assert.doesNotMatch(summary, /remote method|application_error/);
  const notice = renderToStaticMarkup(appComponents.VerificationFailureNotice({ fileLocked: true, message }));
  assert.match(notice, /role="alert"/); assert.match(notice, /실행 중인 앱 종료 필요/);
  assert.match(notice, /앱 종료 후 다시 검증/); assert.match(notice, /코드 자동 수정은 진행하지 않습니다/);
  const sourceFailure = renderToStaticMarkup(appComponents.VerificationFailureNotice({ fileLocked: false, message: 'specific source failure' }));
  assert.match(sourceFailure, /동작 확인을 통과하지 못했습니다/); assert.doesNotMatch(sourceFailure, /specific source failure|실행 중인 앱 종료 필요/);
});

test('unrecognized errors and the existing execution-engine recovery action are preserved', () => {
  const { createElement } = require('react'); let recovered = 0;
  const recovery = createElement('button', { onClick: () => recovered++ }, '실행 엔진 재시작');
  const tree = appComponents.ApplicationErrorBanner({ message: 'unknown backend failure', children: recovery });
  assert.match(renderToStaticMarkup(tree), /unknown backend failure/);
  const detail = elements(tree, (item) => item.type === 'details');
  assert.equal(detail.length, 1); assert.ok(!detail[0].props.open);
  assert.match(renderToStaticMarkup(tree), /요청을 처리하지 못했습니다/);
  elements(tree, (item) => item.type === 'button')[0].props.onClick(); assert.equal(recovered, 1);
});

test('current work is a compact navigation item without the long group title and preserves its destination', () => {
  const projectName = '전체 이름을 보존할 긴 프로젝트 '.repeat(12);
  const run = workbenchRun({ summary: '사이드바에서 제외할 긴 작업 제목 '.repeat(20),
    execution_control: { situation: 'running', action: 'none' } });
  let opened = 0;
  for (const active of [false, true]) {
    const tree = appComponents.CurrentWorkNavigation({ projectName, run, active, pendingAction: '', onOpen: () => opened++ });
    assert.equal(tree.type, 'button'); assert.equal(tree.props.type, 'button');
    assert.equal(tree.props['aria-current'], active ? 'page' : undefined);
    assert.equal(tree.props['aria-haspopup'], undefined, 'the shortcut returns to the work area without a popup');
    assert.equal(tree.props['aria-label'], `열어본 작업으로 돌아가기 · ${projectName} · ${run.summary.trim()}`);
    const label = elements(tree, (item) => item.props.className === 'current-work-navigation__label')[0];
    assert.equal(label.props.children, '열어본 작업');
    const project = elements(tree, (item) => item.props.className === 'current-work-navigation__project')[0];
    assert.equal(project.props.children, projectName); assert.equal(project.props.title, projectName);
    assert.ok(!renderToStaticMarkup(elements(tree, item => item.props.className === 'current-work-navigation__copy')[0]).includes(run.summary.trim()), 'the full group title is available in the accessible destination, not repeated visibly');
    tree.props.onClick();
  }
  assert.equal(opened, 2);
});

test('current work status follows execution evidence, including resumable, failed, unknown and completed work', () => {
  const cases = [
    [{ situation: 'running', action: 'none' }, 'executing', '', '실행 중', 'active'],
    [{ situation: 'preparing', action: 'none' }, 'executing', '', '다음 작업 준비 중', 'active'],
    [{ situation: 'resumable', action: 'resume', stop_phase: 'stopped' }, 'executing', '', '재개 가능', 'warning'],
    [{ situation: 'resumable', action: 'resume' }, 'failed', '', '실패 · 재개 가능', 'warning'],
    [{ situation: 'status_unknown', action: 'none' }, 'executing', '', '상태 확인 필요', 'warning'],
    [undefined, 'executing', '', '상태 확인 필요', 'warning'],
    [{ situation: 'tasks_complete', action: 'none' }, 'work_branch_pushed', '', '작업 실행 완료', 'success'],
    [{ situation: 'ready', action: 'execute' }, 'planned', 'runs.execute', '실행 시작 확인 중', 'active'],
    [{ situation: 'attention_required', action: 'none' }, 'failed', '', '확인 필요', 'danger'],
  ];
  for (const [control, stage, pendingAction, label, tone] of cases) {
    const run = workbenchRun({ stage, execution_control: control,
      tasks: [{ id: 'stored-running', title: '저장된 실행 상태', status: 'running' }] });
    const tree = appComponents.CurrentWorkNavigation({ projectName: 'Sample Project A', run, active: true, pendingAction, onOpen: () => {} });
    assert.equal(elements(tree, (item) => item.props.className === 'current-work-navigation__status').length, 0);
    assert.match(renderToStaticMarkup(tree), /열어본 작업/);
    assert.doesNotMatch(tree.props['aria-label'], new RegExp(label));
  }
});

test('project registration dialog is named by its visible heading and its close control cannot submit the form', () => {
  const { createElement } = require('react');
  const unexpected = () => assert.fail('rendering a dialog must not submit or change a project');
  const markup = renderToStaticMarkup(createElement(appComponents.ProjectDialog, {
    open: true, draft: { name: '', repo: '', config: '', planningSource: '' }, busy: false,
    onChange: unexpected, onChoosePath: unexpected, onClose: unexpected, onSubmit: unexpected,
  }));
  assert.match(markup, /<dialog[^>]+aria-labelledby="project-registration-title"/);
  assert.match(markup, /<h2 id="project-registration-title">프로젝트 등록<\/h2>/);
  assert.match(markup, /<button[^>]+type="button"[^>]+aria-label="닫기"/);
});

test('empty Task sequence gives an explicit status without implying completion or adding an execution action', () => {
  const markup = renderToStaticMarkup(TaskFlow({ run: { tasks: [] }, selectedTaskId: '', onOpen: () => assert.fail('no task to open') }));
  assert.match(markup, /role="status">이 그룹에 표시할 작업이 없습니다/);
  assert.doesNotMatch(markup, /task-flow-card|표시 순서|실행 완료|<button/);
});

function workbenchRun(changes = {}) {
  return { id: 'group-layout', summary: '긴 제목의 작업 그룹', base_commit: '123456789', stage: 'work_branch_pushed',
    workspace_mode: 'shared', plan_revision: 1, plan_approved_revision: 1, recovery_tasks: [],
    execution_control: { situation: 'completed', action: 'none', reason: '작업 실행 완료' },
    tasks: [{ id: 'task-a', title: '첫 작업', status: 'completed', readiness: 'done', conflict_group: ['task-a', 'task-b'],
      blocked_by: [], action_results: [], progress: {}, description: '', model: '', agent_id: '', provider_id: '', reasoning_effort: '' }], ...changes };
}

function workbenchProps(run, changes = {}) {
  return { run, selectedTaskId: 'task-a', selectedTaskIds: [], planDirty: false, draftConflict: false, draftErrorCount: 0,
    busyAction: '', executionAction: '', profileOptions: {}, profiles: {}, onSelectTask: () => {}, onOpenTaskLog: () => {},
    onStop: () => {}, onExclude: () => {}, onAddTask: () => {}, onResetPlan: () => {}, onSavePlan: () => {},
    onProfileChange: () => {}, onRecovery: () => {}, onBack: () => {}, ...changes };
}

function verificationWorkbench(changes = {}, snapshotChanges = {}, propChanges = {}) {
  const run = workbenchRun({ stage: 'failed', failed_step: 'verify', updated_at: 'revision-1', main_operations: {},
    integration_control: { can_verify: true, can_apply_main: false, remote_configured: false },
    verification_attempts: [{ status: 'failed', failure_phase: 'file_lock' }], ...changes });
  return operationsComponents.OperationsWorkbench({ projectName: 'Example', recoveryTaskId: '', deployConfigured: false, run,
    operationsSnapshot: { projectName: 'Example', runId: run.id, runUpdatedAt: run.updated_at,
      mainOperationsSignature: JSON.stringify(run.main_operations), status: 'ready', workspaces: [], lock: { state: 'unlocked' },
      ...snapshotChanges }, busyAction: '', executionElapsed: 0, stopRequestPending: false, deleting: false, archiving: false,
    onRefresh: () => {}, onVerify: () => {}, onVerifyAndRepair: () => {}, onStop: () => {}, onApprovedAction: () => {},
    onDeleteRun: () => {}, onArchiveRun: () => {}, onRetryArchiveCleanup: () => {}, onOpenArchiveFolder: () => {}, ...propChanges });
}

test('the single task page shows cards and critical actions without repeated summary, post-execution settings or records', () => {
  const { createElement } = require('react'); const calls=[];
  for(const stage of ['executing','failed','ready_to_merge','pushed']) {
    const nextAction=createElement('button',{onClick:()=>calls.push('resume')},'확인 후 재개');
    const tree=appComponents.TaskWorkbench(workbenchProps(workbenchRun({stage}),{cardsOnly:true,nextAction,
      usage:createElement('div',null,'사용량 기록'),effortControls:createElement('div',null,'강도 변경'),
      onSelectTask:id=>calls.push(id)}));
    const html=renderToStaticMarkup(tree);
    assert.doesNotMatch(html,/긴 제목의 작업 그룹|내 프로젝트|완료 1\/1|AI 설정·작업 강도|강도 변경|기술 기록|사용량 기록/);
    assert.equal(elements(tree,n=>n.type?.name==='TaskFlow').length,1);
    assert.match(html,/첫 작업|확인 후 재개/);
    assert.deepEqual(calls,[],'showing cards never starts or stops work');
    elements(tree,n=>n.type?.name==='TaskFlow')[0].props.onOpen('task-a');
    assert.deepEqual(calls,['task-a']);calls.length=0;
  }
  const prepared=appComponents.TaskWorkbench(workbenchProps(workbenchRun({stage:'planned'}),{cardsOnly:true}));
  assert.match(renderToStaticMarkup(prepared),/실행 설정/,'preparation keeps explicit settings');
});

test('inline operations are present for the relevant integration stage and stay absent during ordinary task execution', () => {
  assert.equal(appComponents.workOverviewHasOperations(undefined),false);
  for(const stage of ['planned','executing','failed'])
    assert.equal(appComponents.workOverviewHasOperations(workbenchRun({stage})),false);
  for(const stage of ['ready_to_merge','verified','work_branch_pushed','merged','pushed','deployed'])
    assert.equal(appComponents.workOverviewHasOperations(workbenchRun({stage})),true);
  for(const update of [{active_step:'verify'},{failed_step:'verify'},
    {integration_conflict:{resolution_status:'unresolved'}},{archive:{cleanup_status:'blocked'}},
    {integration_control:{reason_code:'main_apply_recoverable'}}, {integration_control:{reason_code:'main_apply_interrupted'}}])
    assert.equal(appComponents.workOverviewHasOperations(workbenchRun({stage:'failed',...update})),true);
  assert.equal(appComponents.workOverviewHasOperations(workbenchRun({stage:'executing',integration_conflict:{resolution_status:'applied'}})),false);
});

test('dedicated progress ownership requires current group evidence and an operation the work page actually renders', () => {
  const run=workbenchRun({stage:'ready_to_merge',active_step:'verify',updated_at:'now',main_operations:{}});
  const snapshot={projectName:'Example',runId:run.id,runUpdatedAt:run.updated_at,mainOperationsSignature:'{}',status:'ready',
    lock:{run_id:run.id,state:'active',operation:'verify-and-repair'},workspaces:[]};
  assert.equal(appComponents.workOverviewProgressOperation(run,snapshot,'Example'),'verify-and-repair');
  assert.equal(appComponents.workOverviewProgressOperation({...run,active_step:null},snapshot,'Example'),'');
  for(const patch of [{status:'loading'},{status:'error'},{runUpdatedAt:'old'},{projectName:'other'},
    {lock:{run_id:'other',state:'active',operation:'verify-and-repair'}},
    {lock:{run_id:run.id,state:'stale',operation:'verify-and-repair'}},
    {lock:{run_id:run.id,state:'active',operation:'execute'}}])
    assert.equal(appComponents.workOverviewProgressOperation(run,{...snapshot,...patch},'Example'),'');
  for(const operation of ['merge','push','retry-main-push','conflict-resolution-prepare'])
    assert.equal(appComponents.workOverviewProgressOperation(run,{...snapshot,lock:{...snapshot.lock,operation}},'Example'),operation);
});

test('compact operations keep errors and approval callbacks while omitting technical browsing and duplicate tasks', () => {
  const calls=[];
  const tree=verificationWorkbench({failure_message:'exact verify failure',push_receipts:[]},{},{summaryOnly:true,
    onVerify:()=>calls.push('verify'),onVerifyAndRepair:()=>calls.push('repair')});
  const html=renderToStaticMarkup(tree);
  assert.match(html,/오류 원문|exact verify failure/);
  assert.doesNotMatch(html,/기술 기록|포함된 작업|세부 기록·관리|작업공간·기록 관리/);
  assert.deepEqual(calls,[]);
  const retry=elements(tree,n=>n.type==='button'&&renderToStaticMarkup(n).includes('앱 종료 후 다시 검증'))[0];
  assert.equal(retry.props.disabled,false);retry.props.onClick();assert.deepEqual(calls,['verify']);
  const stale=verificationWorkbench({push_receipts:[]},{runUpdatedAt:'old'},{summaryOnly:true});
  assert.ok(elements(stale,n=>n.type==='button').every(n=>n.props.disabled||n.props.children==='상태 다시 확인'));
});

test('apply view prefers a live conflict operation over old failure and passes the guarded verify-only path', () => {
  for (const [operation, label] of [['conflict-resolution-prepare', '충돌 해결안 생성 중'],
    ['conflict-resolution-apply', '충돌 해결 처리 중']]) {
    const onVerify = () => assert.fail('rendering never requests verification');
    const tree = verificationWorkbench({ integration_conflict: { id: 'conflict' } },
      { lock: { run_id: 'group-layout', state: 'active', operation } }, { onVerify, planDirty: true });
    const current = elements(tree, item => item.props?.className === 'apply-summary__current')[0];
    assert.match(visibleHistoryText(current), new RegExp(label));
    assert.doesNotMatch(visibleHistoryText(current), /결과 검사 실패|최종 검증에 실패|실행 중인 앱 종료 필요/);
    assert.equal(elements(current, item => item.type?.name === 'VerificationFailureNotice').length, 0);
    const panel = elements(tree, item => item.type?.name === 'ConflictResolutionPanel')[0];
    assert.ok(panel); assert.equal(panel.props.onVerify, onVerify); assert.equal(panel.props.verifyDisabled, true);
    assert.equal(panel.props.operationsSnapshot.lock.operation, operation);
  }
});

test('file-lock verification offers the original verify callback and blocks AI repair without weakening snapshot guards', () => {
  const calls = [];
  const tree = verificationWorkbench({}, {}, { onVerify: () => calls.push('verify'), onVerifyAndRepair: () => calls.push('repair') });
  const retry = elements(tree, (item) => item.type === 'button' && renderToStaticMarkup(item).includes('앱 종료 후 다시 검증'))[0];
  const repair = elements(tree, (item) => item.type === 'button' && renderToStaticMarkup(item).includes('검증·자동 수정'))[0];
  assert.equal(retry.props.disabled, false); assert.equal(repair.props.disabled, true);
  assert.match(repair.props.title, /파일 잠금/); retry.props.onClick(); assert.deepEqual(calls, ['verify']);
  for (const [snapshotChanges, propChanges] of [[{ runUpdatedAt: 'old' }, {}], [{ status: 'loading' }, {}], [{}, { busyAction: 'runs.verify' }]]) {
    const onVerify = () => calls.push('guarded verify');
    const guarded = verificationWorkbench({}, snapshotChanges, { ...propChanges, onVerify });
    const verification = elements(guarded, (item) => item.type === 'button' && item.props.onClick === onVerify);
    assert.equal(verification.length, 1); assert.equal(verification[0].props.disabled, true);
  }
});

test('the primary source-failure retry uses automatic repair without requiring the technical-record button', () => {
  const calls = [];
  const tree = verificationWorkbench({ verification_attempts: [{ status: 'failed', failure_phase: 'verification_command' }] }, {},
    { onVerify: () => calls.push('verify-only'), onVerifyAndRepair: () => calls.push('repair') });
  const primary = elements(tree, item => item.type === 'button' && item.props.className === 'button button--primary'
    && renderToStaticMarkup(item).includes('최종 검증 재시도'))[0];
  assert.ok(primary); assert.equal(primary.props.disabled, false);
  assert.deepEqual(calls, []);
  primary.props.onClick();
  assert.deepEqual(calls, ['repair']);
});

test('source failures remain repairable and an old file-lock attempt does not label a successful retry as locked', () => {
  const failed = verificationWorkbench({ verification_attempts: [{ failure_phase: 'verification_command' }] });
  const repair = elements(failed, (item) => item.type === 'button' && renderToStaticMarkup(item).includes('검증·자동 수정'))[0];
  assert.equal(repair.props.disabled, false);
  assert.ok(elements(failed, (item) => item.type === 'button' && renderToStaticMarkup(item).includes('최종 검증 재시도')).length);
  const retried = verificationWorkbench({ stage: 'verified', failed_step: '', verification_attempts: [
    { failure_phase: 'file_lock', status: 'failed' }, { failure_phase: '', status: 'succeeded' },
  ] });
  assert.equal(elements(retried, (item) => item.type === 'button' && renderToStaticMarkup(item).includes('앱 종료 후 다시 검증')).length, 0);
  const enabledRepair = elements(retried, (item) => item.type === 'button' && renderToStaticMarkup(item).includes('검증·자동 수정'))[0];
  assert.equal(enabledRepair.props.disabled, false);
});

const verificationAttempt = (changes = {}) => ({
  id: 'attempt-2', status: 'succeeded', started_at: '2026-10-08T01:08:00Z', finished_at: '2026-10-08T01:10:00Z',
  main_head: 'main-commit-full', integration_head: 'candidate-commit-full', task_heads: { 'task-a': 'task-commit' },
  phase: 'complete', current_command: ['dotnet', 'test', 'Example.sln'],
  passed_commands: [['dotnet', 'build', 'Example.sln'], ['dotnet', 'test', 'Example.sln']],
  commit_queue_task_ids: ['task-a', 'task-b'], last_integrated_task_id: 'task-b', failed_task_id: '', failure_phase: '',
  failed_command: [], candidate_task_ids: [], attribution_reason: '', log_path: '', error: '', stop_reason: '',
  command_timeout_seconds: 600, total_timeout_seconds: 1800, repair_count: 1, ...changes,
});

test('apply summary leads with the current action and folds included titles and technical history', () => {
  const tree = verificationWorkbench({ stage: 'ready_to_merge', failed_step: null,
    verification_attempts: [verificationAttempt()], push_receipts: [{ scope: 'work_branch', remote: 'origin', branch: 'work-branch',
      local_commit: 'candidate-commit-full', remote_commit: 'candidate-commit-full', pushed_at: '', operation_request_id: 'request' }],
    tasks: [{ id: 'internal-task', title: '저장 기능 정리', status: 'completed' }, { id: 'not-included', title: '미완료 작업', status: 'pending' }],
    integration_control: { status: 'needs_verification', can_verify: true, can_apply_main: false, remote_configured: true, reason: '반영 준비 완료' } });
  const visible = visibleHistoryText(tree);
  assert.match(visible, /세부 기록·관리/); assert.match(visible, /작업 브랜치에 반영/);
  assert.doesNotMatch(visible, /저장 기능 정리|internal-task|미완료 작업|최근 검증 기록|Push 기록|candidate-commit-full|dotnet|결과 검사/);
  const tasks = elements(tree, item => item.props.className === 'apply-summary__tasks')[0];
  assert.equal(tasks.type, 'details'); assert.equal(tasks.props.open, undefined);
  assert.match(renderToStaticMarkup(tasks), /저장 기능 정리/);
  assert.doesNotMatch(renderToStaticMarkup(tasks), /미완료 작업/);
  const tech = elements(tree, (item) => item.props?.className === 'apply-summary__technical')[0];
  assert.equal(tech.type, 'details'); assert.equal(tech.props.open, undefined);
  const raw = renderToStaticMarkup(tech);
  assert.match(raw, /최근 검증 기록/); assert.match(raw, /Push 기록/); assert.match(raw, /candidate-commit-full/);
  const actions = elements(tree, (item) => item.props?.className === 'apply-summary__actions')[0];
  assert.equal(elements(actions, (item) => item.type === 'button' && item.props.className.includes('primary')).length, 1);
});

test('Main summary action requires current backend permission and confirmed upload, and keeps the exact separate callback', () => {
  const calls = [];
  const control = { status: 'verified', can_verify: false, can_apply_main: true, remote_configured: true,
    verified_main_head: 'main', current_main_head: 'main', verified_integration_head: 'candidate', current_integration_head: 'candidate' };
  const current = { stage: 'work_branch_pushed', active_step: null, failed_step: null, verification_attempts: [],
    pushed_work_branch_head: 'candidate', push_receipts: [{ scope: 'work_branch', local_commit: 'candidate', remote_commit: 'candidate' }], integration_control: control };
  const tree = verificationWorkbench(current, {}, { onApplySummary: (action) => calls.push(action) });
  const action = elements(tree, (item) => item.type === 'button' && renderToStaticMarkup(item).includes('메인 브랜치에 적용'))[0];
  assert.ok(action); assert.equal(action.props.disabled, false); assert.deepEqual(calls, []);
  action.props.onClick(); assert.deepEqual(calls, ['main']);
  for (const blocked of [{ status: 'loading' }, { runUpdatedAt: 'old' }]) {
    const stale = verificationWorkbench(current, blocked);
    assert.doesNotMatch(visibleHistoryText(stale), /메인 브랜치에 적용/);
  }
  assert.doesNotMatch(visibleHistoryText(verificationWorkbench({ ...current, integration_control: { ...control, can_apply_main: false } })), /메인 브랜치에 적용/);
});

test('resolved conflict history leaves the visible next apply action usable through work upload and separate Main approval', () => {
  const integration_conflict = { id: 'resolved-conflict', resolution_status: 'applied' };
  const control = { status: 'verified', can_verify: true, can_apply_main: false, remote_configured: true,
    verified_main_head: 'main', current_main_head: 'main', verified_integration_head: 'candidate', current_integration_head: 'candidate' };
  for (const [stage, remote, action, label] of [['verified', true, 'work', '작업 브랜치에 반영'],
    ['work_branch_pushed', true, 'main', '메인 브랜치에 적용'], ['verified', false, 'main', '메인 브랜치에 적용']]) {
    const calls = [];
    const current = { stage, active_step: null, failed_step: null, verification_attempts: [], integration_conflict,
      pushed_work_branch_head: stage === 'work_branch_pushed' ? 'candidate' : '',
      push_receipts: stage === 'work_branch_pushed' ? [{ scope: 'work_branch', local_commit: 'candidate', remote_commit: 'candidate' }] : [],
      integration_control: { ...control, can_apply_main: action === 'main', remote_configured: remote } };
    const tree = verificationWorkbench(current, {}, { onApplySummary: next => calls.push(next) });
    const region = elements(tree, item => item.props?.className === 'apply-summary__current')[0];
    const buttons = elements(region, item => item.type === 'button' && item.props.className?.includes('button--primary'));
    assert.equal(buttons.length, 1); assert.equal(visibleHistoryText(buttons[0]), label);
    assert.equal(buttons[0].props.disabled, false); assert.deepEqual(calls, []);
    buttons[0].props.onClick(); assert.deepEqual(calls, [action]);
    const dirty = verificationWorkbench(current, {}, { planDirty: true });
    assert.ok(elements(dirty, item => item.type === 'button' && item.props.className?.includes('button--primary'))
      .every(button => button.props.disabled), 'unsaved changes still block the action');
  }
});

test('apply progress has one current status and retains stop, original inspection and management guards', () => {
  const calls = [];
  const active = verificationWorkbench({ stage: 'ready_to_merge', failed_step: null, active_step: 'verify', verification_attempts: [], push_receipts: [],
    execution_control: { stop_scope: 'verification', stop_phase: '', can_stop: true },
    verification_progress_detail: 'technical command argument', verification_progress_current: 1, verification_progress_total: 2 },
    { lock: { state: 'active', operation: 'verify' } }, { onStop: () => calls.push('stop') });
  assert.equal(elements(active, (item) => item.props?.className === 'apply-summary__current').length, 1);
  const stops = elements(active, (item) => item.type === 'button' && renderToStaticMarkup(item).includes('검증 중지'));
  assert.equal(stops.length, 1);
  const stop = stops[0];
  const progress = elements(active, item => item.props.className?.includes('verification-progress--active'))[0];
  assert.ok(elements(progress, item => item === stop).length, 'stop belongs to the current progress card');
  assert.doesNotMatch(visibleHistoryText(active), /완료한 작업을 검사|완료한 작업이 정상적으로/);
  assert.ok(stop); assert.equal(stop.props.disabled, false); stop.props.onClick(); assert.deepEqual(calls, ['stop']);
  assert.doesNotMatch(visibleHistoryText(active), /technical command argument/);
  const interrupted = verificationWorkbench({ stage: 'work_branch_pushed', failed_step: null, verification_attempts: [], push_receipts: [],
    integration_control: { status: 'unknown', can_verify: false, can_apply_main: false, reason_code: 'main_apply_interrupted', remote_configured: true } });
  assert.match(visibleHistoryText(interrupted), /중단된 Main 반영 원본 확인/);
  const management = elements(interrupted, (item) => item.props?.className === 'apply-summary__management')[0];
  assert.equal(management.props.open, undefined);
  const remove = elements(management, (item) => item.type === 'button' && renderToStaticMarkup(item).includes('작업 그룹 삭제'))[0];
  assert.equal(remove.props.disabled, true, 'interrupted original state cannot be deleted');
});

test('verification card retains progress, elapsed time and stop permission through pending and stopping requests', () => {
  for (const [canStop, requestPending, stopping] of [[true, false, false], [false, false, false],
    [true, true, false], [false, false, true], [true, false, true]]) {
    const calls = [];
    const tree = verificationWorkbench({ stage: 'ready_to_merge', failed_step: null, active_step: 'verify',
      verification_attempts: [], verification_progress_phase: 'running_command',
      verification_progress_current: 9, verification_progress_total: 12,
      execution_control: { stop_scope: 'verification', stop_phase: stopping ? 'stopping' : '', can_stop: canStop } },
    { lock: { state: 'active', operation: 'verify-and-repair' } },
    { stopRequestPending: requestPending, executionElapsed: 342, onStop: () => calls.push('stop') });
    const progress = elements(tree, item => item.props.className?.includes('verification-progress--active'))[0];
    const stops = elements(tree, item => item.type === 'button' && renderToStaticMarkup(item).includes('검증 중지'));
    assert.equal(stops.length, 1); assert.equal(stops[0].props.disabled, stopping || !canStop || requestPending);
    assert.ok(elements(progress, item => item === stops[0]).length);
    const bar = elements(progress, item => item.props.role === 'progressbar')[0];
    assert.equal(bar.props['aria-valuenow'], 9); assert.equal(bar.props['aria-valuemax'], 12);
    assert.match(renderToStaticMarkup(progress), /5분 42초/);
    assert.deepEqual(calls, []);
    if (stopping) assert.match(visibleHistoryText(progress), /검증 중지 중.*실행 종료를 기다립니다/);
    else assert.match(visibleHistoryText(progress), /검증 명령 실행 중 · 9\/12/);
    if (requestPending) assert.match(renderToStaticMarkup(stops[0]), /검증 중지 중/);
    if (!stops[0].props.disabled) { stops[0].props.onClick(); assert.deepEqual(calls, ['stop']); }
  }
});

test('verification start pending, stale snapshots and other operation locks cannot show an active stop card', () => {
  for (const [snapshot, props] of [
    [{ status: 'loading' }, {}], [{ runUpdatedAt: 'old' }, {}],
    [{ lock: { state: 'active', operation: 'execute' } }, {}],
    [{ lock: { state: 'unlocked' } }, { busyAction: 'runs.verify', executionElapsed: 12 }],
  ]) {
    const tree = verificationWorkbench({ stage: 'ready_to_merge', failed_step: null, active_step: 'verify',
      verification_attempts: [], execution_control: { stop_scope: 'verification', can_stop: true } }, snapshot, props);
    assert.equal(elements(tree, item => item.props.className?.includes('verification-progress--active')).length, 0);
    assert.equal(elements(tree, item => item.type === 'button' && renderToStaticMarkup(item).includes('검증 중지')).length, 0);
    if (props.busyAction) assert.match(visibleHistoryText(tree), /최종 검증 시작이 지연/);
  }
});

test('verification status moves to the fixed header without duplicating body cards or stop requests', () => {
  const target = { nodeType: 1 }, calls = [];
  const tree = verificationWorkbench({ stage: 'ready_to_merge', failed_step: null, active_step: 'verify',
    verification_attempts: [], verification_progress_phase: 'running_command',
    verification_progress_current: 4, verification_progress_total: 10,
    execution_control: { stop_scope: 'verification', can_stop: true } },
    { lock: { state: 'active', operation: 'verify-and-repair' } },
    { statusTarget: target, executionElapsed: 15, onStop: () => calls.push('stop') });
  const portal = tree.props.children[0];
  assert.equal(portal.containerInfo, target);
  assert.equal(elements(tree, item => item.props?.className === 'apply-summary__current').length, 0);
  const status = portal.children;
  assert.match(visibleHistoryText(status), /검증 명령 실행 중 · 4\/10/);
  assert.match(renderToStaticMarkup(status), /15초/);
  const stops = elements(status, item => item.type === 'button' && renderToStaticMarkup(item).includes('검증 중지'));
  assert.equal(stops.length, 1); assert.equal(stops[0].props.disabled, false);
  assert.deepEqual(calls, []); stops[0].props.onClick(); assert.deepEqual(calls, ['stop']);
  const progress = elements(status, item => item.props.role === 'progressbar')[0];
  assert.equal(progress.props['aria-valuenow'], 4); assert.equal(progress.props['aria-valuemax'], 10);
});

test('header status keeps failure descriptions closed, preserves current actions and vanishes when its view closes', () => {
  const target = { nodeType: 1 };
  for (const changes of [{}, { stage: 'ready_to_merge', failed_step: null, verification_attempts: [] },
    { stage: 'pushed', failed_step: null, verification_attempts: [] }]) {
    const open = verificationWorkbench(changes, {}, { statusTarget: target });
    const status = open.props.children[0].children;
    assert.equal(open.props.children[0].containerInfo, target);
    const descriptions = elements(status, item => item.type === 'details');
    assert.ok(descriptions.every(item => item.props.open === undefined));
    if (changes.stage !== 'pushed') {
      assert.ok(elements(status, item => item.type === 'button').length > 0);
    }
    const closed = verificationWorkbench(changes, {}, { statusTarget: target, statusVisible: false });
    assert.equal(closed.props.children[0], null);
    assert.equal(elements(closed, item => item.props?.className === 'apply-summary__current').length, 0);
  }
});

test('operations retain one current state and action region while stages and snapshot availability change', () => {
  const stages = [
    [{ stage: 'ready_to_merge', failed_step: null }, {}, {}],
    [{ stage: 'ready_to_merge', failed_step: null, active_step: 'verify',
      execution_control: { stop_scope: 'verification', can_stop: true } }, { lock: { state: 'active', operation: 'verify' } }, {}],
    [{ stage: 'ready_to_merge', failed_step: null }, { status: 'loading' }, { busyAction: 'runs.verify' }],
    [{ stage: 'work_branch_pushed', failed_step: null }, { lock: { state: 'active', operation: 'merge' } }, { busyAction: 'runs.merge' }],
    [{ stage: 'pushed', failed_step: null }, {}, { onViewResults() {} }],
    [{ stage: 'pushed', failed_step: null }, { status: 'loading' }, { onViewResults() {} }],
    [{ stage: 'ready_to_merge', failed_step: null }, {}, { planDirty: true, actionError: '미저장 작업을 먼저 확인하세요.' }],
  ];
  for (const [run, snapshot, props] of stages) {
    const tree = verificationWorkbench({ verification_attempts: [], ...run }, snapshot, props);
    const current = elements(tree, item => item.props.className === 'apply-summary__current');
    assert.equal(current.length, 1);
    const basicSections = tree.props.children.filter(child => child && typeof child === 'object');
    assert.equal(basicSections[0], current[0], 'the state and controls precede every list, notice and diagnostic');
    assert.equal(elements(current[0], item => item.props.className === 'apply-summary__actions').length, 1);
    assert.equal(elements(tree, item => item.props.className === 'apply-summary__tasks').length, 1);
    assert.equal(elements(tree, item => item.props.className === 'apply-summary__technical').length, 1);
    assert.equal(elements(tree, item => item.props.className === 'apply-summary__management').length, 1);
    assert.equal(elements(current[0], item => item.type === 'button').length > 0, run.stage !== 'pushed',
      'completed status has no duplicate result or cleanup action');
    const progress = elements(current[0], item => item.props.role === 'progressbar');
    assert.equal(progress.length, snapshot.lock?.operation === 'verify' ? 1 : 0);
    if (props.busyAction) {
      const placeholder = elements(current[0], item => item.type === 'button' && renderToStaticMarkup(item).includes('요청 처리 중'))[0];
      assert.ok(placeholder); assert.equal(placeholder.props.disabled, true); assert.equal(placeholder.props.onClick, undefined);
    }
  }
});

test('apply failures keep one issue heading and full diagnostics without a second failure card', () => {
  for (const fileLocked of [true, false]) {
    const tree = verificationWorkbench({ failure_message: 'exact raw verification failure', push_receipts: [],
      verification_attempts: [verificationAttempt({ status: 'failed', failure_phase: fileLocked ? 'file_lock' : 'verification_command' })] });
    const current = elements(tree, item => item.props.className === 'apply-summary__current')[0];
    const visible = visibleHistoryText(current);
    assert.match(visible, fileLocked ? /빌드 파일 사용 중/ : /결과 검사 실패/);
    assert.doesNotMatch(visible, /최종 검증에 실패했습니다|exact raw verification failure/);
    assert.equal(elements(current, item => item.props.className?.split(' ').includes('verification-progress')).length, 1,
      'one status card without a nested failure notice');
    assert.match(renderToStaticMarkup(tree), /exact raw verification failure/);
  }
  const dirty = verificationWorkbench({}, {}, { planDirty: true, actionError: '미저장 작업을 먼저 확인하세요.' });
  assert.equal(visibleHistoryText(dirty).split('미저장 작업').length - 1, 1);
  const done = verificationWorkbench({ stage: 'pushed', failed_step: '', verification_attempts: [],
    integration_control: { remote_configured: true, can_verify: false, can_apply_main: false } });
  assert.doesNotMatch(visibleHistoryText(done), /적용한 결과와 기록을 확인|반영할 작업/);
  const conflicted = verificationWorkbench({ integration_conflict: { id: 'conflict', resolution_status: 'candidate_ready' } });
  const current = elements(conflicted, item => item.props.className === 'apply-summary__current')[0];
  assert.equal(current.props['data-compact'], undefined);
  assert.match(visibleHistoryText(current), /빌드 파일 사용 중.*빌드 파일을 사용하는 앱\/서버를 종료/s);
});

test('archived group entry names the records it opens and performs no operation on render', () => {
  const calls = [];
  const entry = appComponents.ApplySummaryEntry({ projectName: 'Example', run: workbenchRun({ archive: { cleanup_status: 'completed' } }),
    busyAction: '', onOpen: () => calls.push('open') });
  const buttons = elements(entry, item => item.type === 'button');
  assert.equal(buttons.length, 1); assert.match(renderToStaticMarkup(buttons[0]), /보관 기록 보기/);
  assert.doesNotMatch(renderToStaticMarkup(entry), /반영 내용 확인/);
  assert.deepEqual(calls, []); buttons[0].props.onClick(); assert.deepEqual(calls, ['open']);
});

test('closing the apply popup leaves a selected-group status card whose single action only opens the popup', () => {
  const run = workbenchRun({ stage: 'pushed', updated_at: 'current',
    main_operations: { merge: { status: 'succeeded', phase: 'cleanup_deferred' } } });
  const snapshot = { projectName: 'Example', runId: run.id, runUpdatedAt: run.updated_at,
    mainOperationsSignature: JSON.stringify(run.main_operations), status: 'ready', lock: { state: 'unlocked' }, workspaces: [] };
  const calls = [];
  const props = { run, projectName: 'Example', operationsSnapshot: snapshot, busyAction: '', onOpen: () => calls.push('open') };
  for (const current of [props, { ...props, operationsSnapshot: { ...snapshot, status: 'loading' } }]) {
    const entry = appComponents.ApplySummaryEntry(current);
    const text = renderToStaticMarkup(entry);
    assert.match(text, /반영·마무리/); assert.match(text, /긴 제목의 작업 그룹/);
    assert.match(text, current === props ? /Main Push 완료 · 작업공간 정리 보류/ : /최신 상태 확인 중/);
    const buttons = elements(entry, item => item.type === 'button');
    assert.equal(buttons.length, 1); assert.equal(buttons[0].props.disabled, false);
    assert.equal(buttons[0].props['aria-haspopup'], 'dialog'); buttons[0].props.onClick();
  }
  assert.deepEqual(calls, ['open', 'open']);
  const empty = appComponents.ApplySummaryEntry({ ...props, run: undefined });
  assert.equal(elements(empty, item => item.type === 'button')[0].props.disabled, true);
});

test('actual approval adapter tracks a requested command through close and returns cancellation or failures without chaining', async () => {
  const callback = readFileSync(appFile, 'utf8').match(/^    const requestApplySummaryCommand = [\s\S]*?(?=^    const performApplySummary =)/m);
  assert.ok(callback);
  for (const method of ['runs.push', 'runs.verifyAndRepair']) for (const outcome of ['success', 'cancel', 'failure']) {
    let requests = {}; let resolveCommand, rejectCommand;
    const calls = [], replacements = [];
    const context = { react_1: { useCallback: (fn) => fn }, applyCommandPendingRef: { current: false },
      runExecutionControl_1: appRequire('./runExecutionControl.js'),
      applySummaryFlow_1: appRequire('./applySummaryFlow.js'),
      selectedContextRef: { current: { projectName: 'project', runId: 'group' } }, executionRequestSequenceRef: { current: 0 },
      runContextMatches: (a, b, c, d) => a === c && b === d, runRequestKey: (a, b) => JSON.stringify([a, b]),
      setExecutionRequests: (update) => { requests = update(requests); }, replaceRun: (project, run) => replacements.push([project, run]),
      isRunState: (value) => value?.id && value.stage, setError() {}, errorMessage: (cause) => cause.message,
      window: { setInterval: () => 1, clearInterval() {}, crypto: { randomUUID: () => 'approval-id' },
        orchestrator: { request: (method, params) => {
          calls.push([method, params, 'request']); return new Promise((resolve, reject) => { resolveCommand = resolve; rejectCommand = reject; });
        }, approve: (method, params) => {
          calls.push([method, params, 'approve']); return new Promise((resolve, reject) => { resolveCommand = resolve; rejectCommand = reject; });
        } } },
    };
    runInNewContext(`${callback[0]}\nthis.command = requestApplySummaryCommand;`, context);
    const promise = context.command('project', 'group', method, { workspaceMode: 'shared' });
    assert.equal(Object.values(requests)[0].method, method);
    context.selectedContextRef.current = { projectName: 'other-project', runId: 'other-group' };
    if (outcome === 'failure') { rejectCommand(new Error('remote failed')); await assert.rejects(promise, /remote failed/); }
    else { resolveCommand(outcome === 'cancel' ? null : { id: 'group', stage: 'work_branch_pushed' }); assert.equal((await promise)?.stage || null, outcome === 'cancel' ? null : 'work_branch_pushed'); }
    assert.equal(Object.keys(requests).length, 0); assert.equal(context.applyCommandPendingRef.current, false);
    assert.equal(calls.length, 1); assert.equal(calls[0][0], method);
    assert.equal(calls[0][2], method === 'runs.verifyAndRepair' ? 'request' : 'approve');
    assert.equal(calls[0][1].projectName, 'project'); assert.equal(calls[0][1].runId, 'group'); assert.equal(calls[0][1].requestId, 'approval-id');
    assert.equal(replacements.length, outcome === 'success' ? 1 : 0);
    if (replacements.length) assert.equal(replacements[0][0], 'project', 'late response retains original target');
  }
});

test('completion separates optional archive cleanup from the completed status and avoids a duplicate result action', () => {
  for (const [stage, remote] of [['pushed', true], ['deployed', true], ['merged', false]]) {
    const calls = []; const onArchiveRun = () => calls.push('archive');
    const tree = verificationWorkbench({ stage, failed_step: null, verification_attempts: [], push_receipts: [],
      integration_control: { remote_configured: remote, can_verify: false, can_apply_main: false } }, {},
      { onArchiveRun, onViewResults() {} });
    assert.match(visibleHistoryText(tree), /작업 마무리.*선택.*실행 기록/u);
    const buttons = elements(tree, (node) => node.type === 'button' && node.props.onClick === onArchiveRun);
    assert.equal(buttons.length, 1); assert.equal(buttons[0].props.disabled, false);
    const management = elements(tree, (node) => node.type === 'details' && node.props.className === 'apply-summary__management')[0];
    assert.doesNotMatch(renderToStaticMarkup(management), /보관하고 정리/);
    const finish = elements(tree, (node) => node.props.className === 'apply-summary__finish')[0];
    assert.ok(elements(finish, (node) => node.props.onClick === onArchiveRun).length);
    assert.equal(buttons[0].props.className, 'button button--secondary');
    assert.deepEqual(calls, [], 'showing completion never archives automatically');
    buttons[0].props.onClick(); assert.deepEqual(calls, ['archive']);
    assert.equal(elements(tree, (node) => node.type === 'button' && node.props.children === '결과 보기').length, 0);
    const records = elements(tree, (node) => node.props.className === 'apply-summary__records')[0];
    assert.equal(records.type, 'details'); assert.ok(!records.props.open);
    assert.doesNotMatch(visibleHistoryText(tree), /포함된 작업|작업 그룹 관리/);
    assert.match(renderToStaticMarkup(records), /포함된 작업|작업 그룹 관리/);
  }
  for (const stage of ['executing', 'failed', 'ready_to_merge', 'verified', 'work_branch_pushed', 'merged']) {
    const tree = verificationWorkbench({ stage, verification_attempts: [],
      integration_control: { remote_configured: true, can_verify: false, can_apply_main: false } });
    assert.doesNotMatch(visibleHistoryText(tree), /보관하고 정리/);
  }
});

test('visible completion cleanup retains snapshot, active lock and archive-in-progress guards', () => {
  for (const [snapshot, props] of [[{ runUpdatedAt: 'old' }, {}], [{ status: 'loading' }, {}], [{ status: 'error' }, {}],
    [{ lock: { state: 'active', operation: 'archive' } }, {}], [{}, { archiving: true }]]) {
    const onArchiveRun = () => assert.fail('render must not archive');
    const tree = verificationWorkbench({ stage: 'pushed', failed_step: null, verification_attempts: [],
      integration_control: { remote_configured: true, can_verify: false, can_apply_main: false } }, snapshot, { ...props, onArchiveRun });
    assert.match(visibleHistoryText(tree), /보관하고 정리|보관·정리 중/);
    const button = elements(tree, (node) => node.type === 'button' && node.props.onClick === onArchiveRun)[0];
    assert.equal(button.props.disabled, true);
  }
});

test('archive popup leads with status and cleanup while technical records and permanent deletion start closed', () => {
  const calls = [];
  const tree = verificationWorkbench({ archive: { archived_at: '', snapshot_path: 'snapshot-original', manifest_path: 'manifest-original',
    cleanup_status: 'blocked', cleanup_targets: [{ id: 'target', status: 'failed', recorded_path: 'workspace-original', error: 'locked' }] },
    push_receipts: [{ scope: 'main', remote: 'origin', branch: 'main', pushed_at: '', local_commit: 'local', remote_commit: 'remote' }] }, {}, {
    onOpenArchiveFolder: () => calls.push('folder'), onRetryArchiveCleanup: () => calls.push('retry'), onDeleteRun: () => calls.push('delete'),
  });
  const visible = visibleHistoryText(tree);
  assert.match(visible, /작업공간 정리 확인 필요.*0\/1/);
  assert.match(visible, /정리 다시 시도.*기록 폴더 열기/);
  assert.doesNotMatch(visible, /ARCHIVED|archive ref|snapshot-original|manifest-original|workspace-original|Push 기록|locked|영구 삭제/);
  assert.equal(elements(tree, (item) => item.type === 'h3').length, 0, 'the dialog title is not repeated in a body card');
  const tech = elements(tree, (item) => item.props?.className === 'apply-summary__technical')[0];
  assert.equal(tech.props.open, undefined); const raw = renderToStaticMarkup(tech);
  assert.match(raw, /snapshot-original/); assert.match(raw, /manifest-original/); assert.match(raw, /Push 기록/);
  assert.match(raw, /archive ref/); assert.match(raw, /locked/);
  const deletion = elements(tree, (item) => item.props?.className === 'archive-record__delete')[0];
  assert.equal(deletion.type, 'details'); assert.equal(deletion.props.open, undefined);
  assert.match(renderToStaticMarkup(deletion), /복구할 수 없습니다/);
  assert.deepEqual(calls, [], 'opening the popup or its disclosures does not perform an action');
  for (const label of ['기록 폴더 열기', '정리 다시 시도', '보관 기록 영구 삭제']) {
    const button = elements(tree, (item) => item.type === 'button' && renderToStaticMarkup(item).includes(label))[0];
    assert.ok(button); assert.ok(!button.props.disabled); button.props.onClick();
  }
  assert.deepEqual(calls, ['folder', 'retry', 'delete']);
});

test('archive cleanup completion and busy states keep the original actions and accurate counts', () => {
  for (const state of ['pending', 'running', 'partial', 'blocked', 'completed']) {
    const tree = verificationWorkbench({ archive: { archived_at: '', snapshot_path: '', manifest_path: '',
      cleanup_status: state, cleanup_targets: [{ id: 'removed', status: 'removed' }, { id: 'gone', status: 'already_removed' },
        ...(state === 'completed' ? [] : [{ id: 'remaining', status: 'blocked', error: 'remaining raw reason' }])] } }, {},
      { busyAction: 'runs.retryArchiveCleanup', deleting: true });
    const visible = visibleHistoryText(tree);
    assert.match(visible, state === 'completed' ? /작업공간 정리 완료.*2\/2/ : /작업공간 정리 확인 필요.*2\/3/);
    assert.doesNotMatch(visible, /remaining raw reason|영구 삭제/);
    const retry = elements(tree, (item) => item.type === 'button' && renderToStaticMarkup(item).includes('정리 다시 시도'));
    assert.equal(retry.length, state === 'completed' ? 0 : 1);
    if (retry.length) assert.equal(retry[0].props.disabled, true);
    const deletion = elements(tree, (item) => item.type === 'button' && renderToStaticMarkup(item).includes('보관 기록 영구 삭제'))[0];
    assert.equal(deletion.props.disabled, true);
  }
  const empty = verificationWorkbench({ archive: { cleanup_status: 'completed', cleanup_targets: [] } });
  assert.match(visibleHistoryText(empty), /작업공간 정리 완료.*0\/0/);
  assert.doesNotMatch(visibleHistoryText(empty), /정리 다시 시도/);
});

test('archive cleanup explains a file lock briefly and keeps the full error closed', () => {
  const raw = "작업공간이 다른 프로그램에서 사용 중입니다: C:\\private\\work. 원인: [WinError 32] lengthy internal diagnostic";
  const tree = verificationWorkbench({ push_receipts: [], archive: { cleanup_status: 'blocked', cleanup_targets: [
    { id: 'shared', status: 'failed', recorded_path: 'C:\\private\\work', error: raw },
  ] } });
  const visible = visibleHistoryText(tree);
  assert.match(visible, /다른 프로그램이 작업 폴더를 사용 중입니다/);
  assert.match(visible, /정리 다시 시도/);
  assert.doesNotMatch(visible, /private|WinError|internal diagnostic/);
  const technical = elements(tree, (item) => item.props?.className === 'apply-summary__technical')[0];
  assert.equal(technical.props.open, undefined);
  assert.ok(renderToStaticMarkup(technical).includes(raw));
  const banner = appComponents.ApplicationErrorBanner({ message: raw });
  assert.match(visibleHistoryText(banner), /다른 프로그램이 작업 폴더를 사용 중입니다/);
  assert.doesNotMatch(visibleHistoryText(banner), /private|WinError|internal diagnostic/);
  const details = elements(banner, (item) => item.type === 'details')[0];
  assert.equal(details.props.open, undefined);
  assert.equal(elements(details, (item) => item.type === 'pre')[0].props.children, raw);
});

// Native closed details expose their summary; this checks content grouping, not browser layout.
function visibleHistoryText(tree) {
  if (tree == null || typeof tree === 'boolean') return '';
  if (typeof tree !== 'object') return String(tree);
  if (Array.isArray(tree)) return tree.map(visibleHistoryText).join('');
  if (typeof tree.type === 'function') return visibleHistoryText(tree.type(tree.props));
  if (tree.type === 'details' && !tree.props.open) {
    return visibleHistoryText([tree.props.children].flat().find((child) => child?.type === 'summary'));
  }
  return visibleHistoryText(tree.props?.children);
}

test('verification history leads with the latest result and folds earlier failures separately', () => {
  const previous = verificationAttempt({ id: 'attempt-1', status: 'failed', error: 'earlier failure raw output' });
  const latest = verificationAttempt();
  const tree = appComponents.VerificationHistory({ run: { verification_attempts: [previous, latest], verification_repair_limit: 2 } });
  const visible = visibleHistoryText(tree);
  assert.match(visible, /2차.*성공/);
  assert.match(visible, /이 시도의 검증을 통과했습니다/);
  assert.match(visible, /이전 검증.*1.*회/);
  assert.doesNotMatch(visible, /1차|실패|earlier failure|main-commit-full|candidate-commit-full|dotnet|Main 반영 완료/);
  const history = elements(tree, (item) => item.props?.className === 'verification-history__previous')[0];
  assert.equal(history.type, 'details'); assert.equal(history.props.open, undefined);
  const oldMarkup = renderToStaticMarkup(history);
  assert.match(oldMarkup, /1차.*실패/); assert.match(oldMarkup, /earlier failure raw output/);
  assert.doesNotMatch(oldMarkup, /role="alert"/, 'a historical failure does not become a current alert');
  const refreshed = appComponents.VerificationHistory({ run: { verification_attempts: [{ ...previous }, { ...latest }], verification_repair_limit: 2 } });
  assert.equal(tree.props.children[1].key, refreshed.props.children[1].key, 'polling keeps the current record identity');
  assert.equal(appComponents.VerificationHistory({ run: { verification_attempts: [] } }), null);
});

test('technical verification evidence and exact error output remain in closed native details', () => {
  const attempt = verificationAttempt({ status: 'failed', failed_command: ['dotnet', 'test', 'Example.sln'],
    failed_task_id: 'task-a', candidate_task_ids: ['task-a', 'task-b'], attribution_reason: 'bounded attribution evidence',
    failure_phase: 'verification_command', error: 'line one\nline two <raw>', repair_count: 2 });
  const tree = appComponents.VerificationAttemptRecord({ attempt, index: 0, repairLimit: 2 });
  const visible = visibleHistoryText(tree);
  assert.match(visible, /실패/); assert.doesNotMatch(visible, /dotnet|task-a|bounded attribution|line one/);
  const details = elements(tree, (item) => item.type === 'details')[0];
  assert.equal(details.props.open, undefined);
  assert.equal(elements(details, (item) => item.type === 'summary')[0].props.children, '기술 정보 · 상세 기록');
  assert.equal(elements(details, (item) => item.type === 'pre')[0].props.children, attempt.error);
  const markup = renderToStaticMarkup(details);
  for (const evidence of ['main-commit-full', 'candidate-commit-full', 'dotnet build Example.sln', 'dotnet test Example.sln',
    'task-a → task-b', 'verification_command', 'bounded attribution evidence', '2/2']) assert.ok(markup.includes(evidence));
  assert.match(markup, /명령 제한 시간/); assert.match(markup, /전체 제한 시간/);
  assert.doesNotMatch(markup, /경과/, 'time limits are not elapsed-time claims');
  assert.equal(elements(tree, (item) => item.type === 'time')[0].props.dateTime, attempt.finished_at);
  const one = appComponents.VerificationHistory({ run: { verification_attempts: [attempt], verification_repair_limit: 2 } });
  assert.equal(elements(one, (item) => item.props?.className === 'verification-history__previous').length, 0);
});

test('verification records distinguish interruption, file locks, stale and unknown results without claiming live execution', () => {
  const cases = [
    [{ status: 'failed', failure_phase: 'file_lock' }, /실행 중인 앱이 파일을 사용/, /이 시도의 검증을 통과/],
    [{ status: 'succeeded', stop_reason: 'user_stop' }, /사용자가 검증을 중지/, /이 시도의 검증을 통과/],
    [{ status: 'interrupted' }, /검증이 중단되어/, /이 시도의 검증을 통과/],
    [{ status: 'stale' }, /재검증 필요/, /이 시도의 검증을 통과/],
    [{ status: 'running', finished_at: '' }, /진행 기록.*현재 실행 상태/, /검증 중입니다|실행 중입니다|이 시도의 검증을 통과/],
    [{ status: 'unrecognized_status' }, /확인 필요.*결과를 확인할 수 없습니다/, /unrecognized_status|이 시도의 검증을 통과/],
    [{ status: 'toString' }, /확인 필요.*결과를 확인할 수 없습니다/, /이 시도의 검증을 통과/],
  ];
  for (const [changes, expected, absent] of cases) {
    const tree = appComponents.VerificationAttemptRecord({ attempt: verificationAttempt(changes), index: 0, repairLimit: 2 });
    const visible = visibleHistoryText(tree);
    assert.match(visible, expected); assert.doesNotMatch(visible, absent);
    if (changes.stop_reason) assert.match(renderToStaticMarkup(tree), /user_stop/);
    if (changes.status === 'unrecognized_status') assert.match(renderToStaticMarkup(tree), /unrecognized_status/);
    if (!changes.finished_at && changes.status === 'running') {
      assert.equal(elements(tree, (item) => item.type === 'time')[0].props.dateTime, verificationAttempt().started_at);
    }
  }
});

test('completed group puts title, one progress summary and next action before cards, with supporting details folded below', () => {
  const { createElement } = require('react');
  const calls = [];
  const props = workbenchProps(workbenchRun(), {
    nextAction: createElement('button', { onClick: () => calls.push('operations') }, '통합·정리로 이동'),
    usage: createElement('details', null, createElement('summary', null, '사용량·작업 기록')),
    onSelectTask: (id) => calls.push(id), onBack: () => calls.push('overview'),
  });
  const tree = appComponents.TaskWorkbench(props);
  const markup = renderToStaticMarkup(tree);
  assert.ok(markup.indexOf('tasks-workbench-title') < markup.indexOf('통합·정리로 이동'));
  assert.ok(markup.indexOf('통합·정리로 이동') < markup.indexOf('task-flow-card'));
  assert.equal((markup.match(/완료 1\/1/g) || []).length, 1);
  assert.doesNotMatch(markup, /execution-overview|0개 실행 가능|선택한 작업 그룹|작업 대기열|workflow-strip|작업 그룹 진행 단계/);
  for (const label of ['AI 설정·작업 강도', '기술 기록', '사용량·작업 기록', '같은 파일을 수정할 수 있는 작업']) {
    assert.ok(markup.indexOf(label) > markup.indexOf('task-flow-card'), `${label} belongs below the cards`);
  }
  const disclosures = elements(tree, (item) => item.type === 'details');
  assert.ok(disclosures.every((item) => !item.props.open), 'supporting details are initially collapsed');
  elements(tree, (item) => item.type === 'button' && item.props.children === '통합·정리로 이동')[0].props.onClick();
  elements(tree, (item) => item.props['aria-label'] === '전체 현황으로')[0].props.onClick();
  elements(tree, (item) => item.type === TaskFlow)[0].props.onOpen('task-a');
  assert.deepEqual(calls, ['operations', 'overview', 'task-a']);
});

test('potential file overlaps live only inside technical records, with titles and separately disclosed IDs', () => {
  const base = workbenchRun().tasks[0];
  const groupA = ['internal-a', 'internal-b'], groupB = ['internal-c', 'unknown-reference'];
  const tasks = [
    { ...base, id: 'internal-a', title: '결과를 저장합니다', conflict_group: groupA },
    { ...base, id: 'internal-b', title: '저장 결과를 확인합니다', conflict_group: groupA },
    { ...base, id: 'internal-c', title: '알림을 표시합니다', conflict_group: groupB },
  ];
  const tree = appComponents.TaskWorkbench(workbenchProps(workbenchRun({ tasks })));
  const support = elements(tree, item => item.props.className === 'work-group-support')[0];
  const defaultText = visibleHistoryText(support);
  assert.doesNotMatch(defaultText, /internal-|unknown-reference|경로 충돌|같은 파일|glob/);
  const records = elements(support, item => item.type === 'details' && item.props.children[0]?.props.children === '기술 기록')[0];
  const analysis = elements(records, item => item.props.className === 'task-path-overlap')[0];
  assert.ok(analysis); assert.equal(elements(analysis, item => item.props.className === 'plan-review-state').length, 0);
  const titled = visibleHistoryText(analysis);
  for (const title of ['결과를 저장합니다', '저장 결과를 확인합니다', '알림을 표시합니다', '작업 정보를 확인할 수 없습니다']) assert.match(titled, new RegExp(title));
  assert.doesNotMatch(titled, /internal-|unknown-reference|→|glob/);
  assert.equal(elements(analysis, item => item.type === 'details').length, 2, 'duplicate group references share one record');
  const original = renderToStaticMarkup(analysis);
  for (const id of [...groupA, ...groupB]) assert.ok(original.includes(`<code>${id}</code>`));
  assert.doesNotMatch(original, /→|경로 충돌 가능성 분석/);
});

test('unsaved plans disclose saved overlap analysis without treating draft tasks as a recalculation', () => {
  const base = workbenchRun().tasks[0];
  const saved = [{ ...base, title: '저장한 작업 제목', conflict_group: ['task-a', 'saved-peer'] }];
  const draft = [{ ...base, title: '아직 저장하지 않은 제목', conflict_group: ['draft-peer'] }];
  const tree = appComponents.TaskWorkbench(workbenchProps(workbenchRun({ tasks: draft }), { planDirty: true, analysisTasks: saved }));
  const analysis = elements(tree, item => item.props.className === 'task-path-overlap')[0];
  assert.match(visibleHistoryText(analysis), /저장된 계획의 분석/);
  assert.match(visibleHistoryText(analysis), /저장한 작업 제목/);
  assert.doesNotMatch(renderToStaticMarkup(analysis), /아직 저장하지 않은 제목|draft-peer/);
  assert.match(renderToStaticMarkup(analysis), /saved-peer/);
  const empty = appComponents.TaskWorkbench(workbenchProps(workbenchRun({ tasks: draft }), { analysisTasks: [] }));
  assert.equal(elements(empty, item => item.props.className === 'task-path-overlap').length, 0);
});

test('dependency detail keeps real direct and automatic blockers visible and folds only potential overlaps', () => {
  const base = { id: 'selected', title: '선택 작업', status: 'pending', dependencies: ['declared', 'missing'],
    conflict_dependencies: ['declared', 'automatic'], conflict_group: ['selected', 'peer', 'unknown-peer'], blocked_by: ['declared', 'automatic', 'missing'] };
  const tasks = [base, { id: 'declared', title: '먼저 마칠 작업', status: 'running' }, { id: 'automatic', title: '자동 선행 작업 제목', status: 'pending' },
    { id: 'peer', title: '같은 파일의 다른 작업', status: 'completed' }];
  const calls = [], tree = appComponents.TaskDependencyLinks({ task: base, tasks, onOpenTask: id => calls.push(id) });
  const visible = visibleHistoryText(tree);
  assert.match(visible, /먼저 마칠 작업.*현재 대기/); assert.match(visible, /자동 선행 작업 제목.*현재 대기/);
  assert.match(visible, /현재 대기.*참조한 작업이 현재 그룹에 없습니다/);
  assert.doesNotMatch(visible, /같은 파일의 다른 작업|peer|충돌 가능/);
  const technical = elements(tree, item => item.props.className === 'task-dependency-links__technical')[0];
  assert.ok(technical); assert.equal(technical.props.open, undefined);
  assert.match(renderToStaticMarkup(technical), /같은 파일의 다른 작업|unknown-peer/);
  assert.ok(elements(technical, item => item.type === 'button').every(item => !item.props['data-blocked']));
  elements(tree, item => item.type === 'button' && item.props['data-blocked'])[0].props.onClick();
  elements(technical, item => item.type === 'button')[0].props.onClick();
  assert.deepEqual(calls, ['declared', 'peer']);
  assert.equal(appComponents.TaskDependencyLinks({ task: { ...base, dependencies: [], conflict_dependencies: [], conflict_group: [] }, tasks, onOpenTask() {} }), null);
});

test('normal execution lives on cards while group preparation, stop, failure and unknown diagnostics stay accessible', () => {
  const { ExecutionOverview } = require(join(output, 'renderer/src/ExecutionMonitor.js'));
  const base = workbenchRun();
  const cases = [
    { stage: 'executing', execution_control: { situation: 'running', can_stop: true },
      tasks: [{ ...base.tasks[0], status: 'running' }] },
    { stage: 'executing', execution_control: { situation: 'preparing' } },
    { stage: 'executing', execution_control: { situation: 'resumable', stop_phase: 'stopped' } },
    { execution_control: { situation: 'status_unknown' } },
    { execution_control: { situation: 'attention_required' } },
    { stage: 'failed', failure_message: 'specific failure', tasks: [{ ...base.tasks[0], status: 'failed' }] },
    { integration_control: { reason_code: 'main_apply_recoverable' } },
    { stage: 'executing', active_step: 'verify' },
  ];
  for (const changes of cases) {
    const stopped = []; const logs = [];
    const tree = appComponents.TaskWorkbench(workbenchProps(workbenchRun(changes), {
      onStop: (task) => stopped.push(task.id), onOpenTaskLog: (id) => logs.push(id),
    }));
    const monitor = elements(tree, (item) => item.type === ExecutionOverview)[0];
    if (changes.execution_control?.situation === 'running') {
      assert.equal(monitor, undefined);
      const flow = elements(tree, (item) => item.type === TaskFlow)[0];
      flow.props.onStop(base.tasks[0]); assert.deepEqual(stopped, ['task-a']);
      continue;
    }
    assert.ok(monitor, JSON.stringify(changes));
    assert.ok(renderToStaticMarkup(tree).indexOf('execution-overview') < renderToStaticMarkup(tree).indexOf('task-flow-card'));
    monitor.props.onStop(base.tasks[0]); monitor.props.onOpenLog('task-a');
    assert.deepEqual(stopped, ['task-a']); assert.deepEqual(logs, ['task-a']);
  }
});

test('a progress status owned by the lock notice cannot reappear through the fallback execution overview', () => {
  const {createElement, Fragment}=require('react');
  const {ExecutionOverview}=require(join(output,'renderer/src/ExecutionMonitor.js'));
  const base=workbenchRun();
  const current=workbenchRun({stage:'executing',active_step:null,
    tasks:Array.from({length:12},(_,index)=>({...base.tasks[0],id:`done-${index}`,conflict_group:[]})),
    execution_control:{situation:'preparing',action:'none',reason:'그룹 작업이 진행 중입니다.'}});
  const standalone=appComponents.TaskWorkbench(workbenchProps(current));
  assert.ok(elements(standalone,n=>n.type===ExecutionOverview).length);
  const covered=appComponents.TaskWorkbench(workbenchProps(current,{nextAction:createElement(Fragment)}));
  assert.equal(elements(covered,n=>n.type===ExecutionOverview).length,0);
  const markup=renderToStaticMarkup(covered);
  assert.match(markup,/완료 12\/12/);assert.equal((markup.match(/class="task-flow-card"/g)||[]).length,12);
  assert.doesNotMatch(markup,/execution-overview/);
  assert.doesNotMatch(visibleHistoryText(covered),/다음 작업 준비 중|그룹 작업이 진행 중입니다/);
});

test('group cleanup preserves plan save, draft conflict and explicit edit actions without starting execution', () => {
  const calls = [];
  const tree = appComponents.TaskWorkbench(workbenchProps(workbenchRun({ stage: 'planned', plan_approved_revision: 0 }), {
    planDirty: true, draftConflict: true,
    onSavePlan: () => calls.push('save'), onResetPlan: () => calls.push('reset'), onAddTask: () => calls.push('add'),
  }));
  const markup = renderToStaticMarkup(tree);
  assert.match(markup, /미저장 변경 있음/);
  assert.match(markup, /저장된 계획이 변경되었습니다/);
  const save = elements(tree, (item) => item.type === 'button' && item.props.children === '변경 저장')[0];
  assert.equal(save.props.disabled, true, 'conflicting drafts cannot overwrite the saved plan');
  elements(tree, (item) => item.type === 'button' && item.props.children === '변경 취소')[0].props.onClick();
  const add = elements(tree, (item) => item.type === 'button' && Array.isArray(item.props.children) && item.props.children.includes('작업 추가'))[0];
  add.props.onClick();
  assert.deepEqual(calls, ['reset', 'add']);
  const editable = appComponents.TaskWorkbench(workbenchProps(workbenchRun({ stage: 'planned' }), {
    planDirty: true, onSavePlan: () => calls.push('save'),
  }));
  const enabledSave = elements(editable, (item) => item.type === 'button' && item.props.children === '변경 저장')[0];
  assert.equal(enabledSave.props.disabled, false); enabledSave.props.onClick();
  assert.deepEqual(calls, ['reset', 'add', 'save']);
});

test('manual addition is in a closed disclosure while real unsaved changes expose save and cancel', () => {
  const clean = appComponents.TaskWorkbench(workbenchProps(workbenchRun({ stage: 'planned' })));
  const manual = elements(clean, item => item.type === 'details' && renderToStaticMarkup(item).includes('직접 계획 편집'))[0];
  assert.ok(manual); assert.equal(manual.props.open, undefined);
  assert.match(visibleHistoryText(clean), /직접 계획 편집/);
  assert.doesNotMatch(visibleHistoryText(clean), /작업 추가|변경 취소|변경 저장/);
  const dirty = appComponents.TaskWorkbench(workbenchProps(workbenchRun({ stage: 'planned' }), { planDirty: true }));
  assert.match(visibleHistoryText(dirty), /변경 취소.*변경 저장/);
  assert.equal(elements(dirty, item => item.props.className === 'plan-review-actions').length, 1);
});

test('ten projects have one card each, disjoint group buckets and independent activity counts', () => {
  const saved = { 'Project 0': snapshot([summary('failed', { stage: 'failed' }), summary('active'), summary('done', { pipeline_complete: true })]),
    'Project 1': snapshot([summary('active')]) };
  const active = { ...emptyActive, items: [0, 1].map((i) => ({ project_name: `Project ${i}`, run_id: 'active', status: 'active', activity_kinds: ['task'] })) };
  const cards = projectWork(projects, saved, active);
  assert.equal(cards.length, 10);
  const first = cards[0];
  assert.equal(first.groups.length, 3);
  assert.deepEqual(first.counts, { attention: 1, running: 1, waiting: 0, completed: 1 });
  assert.equal(first.completedTasks, 3);
  assert.equal(first.totalTasks, 15);
  assert.deepEqual(initialWorkBucket(first), ['running']);
  assert.equal(cards[1].name, 'Project 1');
});

test('confirmed running projects rank before attention while equal priorities stay stable and stale activity stays uncertain', () => {
  const selectedProjects = projects.slice(0, 4);
  const saved = Object.fromEntries(selectedProjects.map(({ name }) => [name, snapshot([summary('work')])]));
  saved['Project 0'] = snapshot([summary('failed', { stage: 'failed' })]);
  const active = { ...emptyActive, items: [1, 2, 3].map((i) => ({ project_name: `Project ${i}`, run_id: 'work', status: 'active',
    activity_kinds: ['task'], stale: i === 3 })) };
  const cards = projectWork(selectedProjects, saved, active);
  assert.deepEqual(cards.map((card) => card.name), ['Project 1', 'Project 2', 'Project 0', 'Project 3']);
  assert.equal(cards[3].counts.running, 0); assert.equal(cards[3].counts.attention, 1);
  assert.equal(cards[3].unknown, true);
  saved['Project 1'].groups[0].updated_at = '2026-10-07T12:00:00Z';
  assert.deepEqual(projectWork(selectedProjects, saved, active).map((card) => card.name), cards.map((card) => card.name));
});

test('partial query failure keeps previous groups as unknown and cannot look active or complete', () => {
  const saved = { 'Project 0': snapshot([summary('done', { pipeline_complete: true })], 'query failed'),
    'Project 1': snapshot([summary('done', { pipeline_complete: true })]) };
  const cards = projectWork(projects, saved, emptyActive);
  assert.equal(cards[0].groups[0].bucket, 'attention');
  assert.equal(cards[0].groups[0].reason, '최신 상태 확인 불가');
  assert.equal(cards.find((item) => item.name === 'Project 1').counts.completed, 1);
});

test('stopped work is visibly waiting and changing timestamps does not shuffle equal priorities', () => {
  const saved = Object.fromEntries(projects.map((project) => [project.name, { ...snapshot([summary('same', { execution_situation: 'resumable', attention_reasons: ['resume'] })]),
    controls: { same: { stop_phase: 'stopped', action: 'resume' } } }]));
  const before = projectWork(projects, saved, emptyActive);
  assert.ok(before.every((card) => card.groups[0].bucket === 'waiting' && card.groups[0].reason.startsWith('중지됨')));
  saved['Project 9'].groups[0].updated_at = '2099-01-01';
  assert.deepEqual(projectWork(projects, saved, emptyActive).map((item) => item.name), before.map((item) => item.name));
});

test('5, 10 and 15 task cards expose real status, stable selection and separate dependency waits', () => {
  for (const count of [5, 10, 15]) {
    const tasks = Array.from({ length: count }, (_, i) => ({ id: `t${i}`, title: `긴 제목 작업 ${i}`, action_results: [], status: i === 1 ? 'running' : 'pending', readiness: i === 2 ? 'blocked' : 'ready' }));
    const markup = renderToStaticMarkup(TaskFlow({ run: { tasks, plan_revision: 1, plan_approved_revision: 1, execution_control: { situation: 'running' } }, selectedTaskId: 't0', onOpen: () => {} }));
    assert.equal((markup.match(/aria-haspopup="dialog"/g) || []).length, count);
    assert.equal((markup.match(/data-selected="true"/g) || []).length, 1);
    assert.equal((markup.match(/data-active="true"/g) || []).length, 1);
    assert.match(markup, /앞 작업 대기/);
    assert.doesNotMatch(markup, /표시 순서/);
  }
});

test('stored running Task cannot appear live after a stop or without confirmed execution control', () => {
  const task = { id: 'running', title: '작업', status: 'running', action_results: [] };
  for (const [control, label] of [[{ situation: 'resumable', stop_phase: 'stopped' }, '중지됨'],
    [{ situation: 'resumable' }, '중단됨'], [{ situation: 'status_unknown' }, '실행 상태 확인 필요']]) {
    const markup = renderToStaticMarkup(TaskFlow({ run: { tasks: [task], execution_control: control }, selectedTaskId: task.id, onOpen: () => {} }));
    assert.match(markup, new RegExp(label));
    assert.doesNotMatch(markup, /data-active="true"/);
  }
});

function retryStates() {
  const before = { id: 'run', plan_revision: 4, tasks: [{ id: 'done', status: 'completed', completed_commit: 'kept' },
    { id: 'fix', status: 'failed', last_attempt_id: 'old' }, { id: 'next', status: 'pending', readiness: 'ready' }] };
  before.tasks = before.tasks.map((task) => ({ action_results: [], ...task }));
  const latest = { ...before, stage: 'executing', tasks: [before.tasks[0], { action_results: [], id: 'fix', status: 'completed', completed_commit: 'new', last_attempt_id: 'new-attempt' }, before.tasks[2]],
    execution_control: { lock_state: 'unlocked', situation: 'resumable', action: 'resume' },
    waiting_prompt: { kind: 'resume', action: 'resume', next_task_id: 'next', source_key: 'task:fix:remaining_tasks_resume_required:4:new-attempt:new:instruction' } };
  return { before, latest };
}
test('explicit continuation admits only successful current retry and preserves earlier completed results', () => {
  const { before, latest } = retryStates();
  assert.equal(canContinueTaskRetry(before, latest, 'fix'), true);
  assert.equal(canContinueTaskRetry(before, { ...latest, waiting_prompt: null }, 'fix', latest), true);
  assert.equal(canContinueTaskRetry(before, latest, 'fix', { ...latest, tasks: before.tasks }), false);
  for (const change of [{ id: 'other' }, { plan_revision: 5 }, { archive: {} }, { active_step: 'agent_execution' },
    { waiting_prompt: { ...latest.waiting_prompt, source_key: 'other-confirmation' } },
    { tasks: [{ ...latest.tasks[0], completed_commit: 'changed' }, ...latest.tasks.slice(1)] },
    { tasks: [...latest.tasks.slice(0, 2), { ...latest.tasks[2], status: 'stopped' }] },
    { execution_control: { ...latest.execution_control, stop_phase: 'stopping' } },
    { execution_control: { ...latest.execution_control, dispatch_paused: true } }]) {
    assert.equal(canContinueTaskRetry(before, { ...latest, ...change }, 'fix'), false, JSON.stringify(change));
  }
});

function overviewHarness(api) {
  const file = join(output, 'renderer/src/WorkOverview.js');
  const localRequire = createRequire(file);
  const slots = []; let index = 0; const effects = [];
  const exported = {};
  runInNewContext(readFileSync(file, 'utf8'), { exports: exported, window: { orchestrator: api, setInterval: () => 1, clearInterval: () => {} },
    require(name) {
      if (name !== 'react') return localRequire(name);
      return { useState(initial) { const i = index++; if (!(i in slots)) slots[i] = initial;
        return [slots[i], (value) => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; }]; },
      useRef(initial) { const i = index++; if (!(i in slots)) slots[i] = { current: initial }; return slots[i]; },
      useEffect(effect, deps) { const i = index++; if (JSON.stringify(slots[i]) !== JSON.stringify(deps)) { slots[i] = deps; effects.push(effect); } } };
    } });
  return { render(props) { index = 0; return exported.WorkOverview({ onSelectProject: () => {}, onNewWork: () => assert.fail('unexpected new work'), ...props }); }, effects, slots,
    flushEffects() { let cleanup; while (effects.length) { const result = effects.shift()(); if (typeof result === 'function') cleanup ||= result; } return cleanup; } };
}
function elements(tree, predicate, found = []) {
  if (!tree || typeof tree !== 'object') return found;
  if (predicate(tree)) found.push(tree);
  const children = tree.props?.children;
  for (const child of Array.isArray(children) ? children.flat() : [children]) elements(child, predicate, found);
  return found;
}

test('choosing an empty or unavailable project selects its context and offers new work without creating anything', async () => {
  for (const failure of [false, true]) {
    const calls = []; const selected = []; const started = [];
    const harness = overviewHarness({ request: async (method, params) => {
      calls.push([method, params.projectName]);
      assert.equal(method, 'runs.list');
      if (failure && params.projectName === 'Project 1') throw new Error('목록 확인 실패');
      return [];
    } });
    const props = { projects: projects.slice(0, 2), active: emptyActive,
      onSelectProject: (name) => selected.push(name), onNewWork: (name) => started.push(name),
      onOpen: () => assert.fail('there is no group to open'), onRegister: () => {} };
    harness.render(props); harness.flushEffects(); await new Promise(setImmediate);
    let tree = harness.render(props);
    elements(tree, (item) => item.props.className === 'project-work-card' && item.props['aria-label'].startsWith('Project 1'))[0].props.onClick();
    assert.deepEqual(selected, ['Project 1']);
    tree = harness.render(props);
    assert.equal(elements(tree, (item) => item.type === 'button' && item.props.children === '작업 열기').length, 0);
    assert.match(renderToStaticMarkup(tree), failure ? /목록 확인 실패/ : /등록된 작업 그룹이 없습니다/);
    const start = elements(tree, (item) => item.type === 'button' && item.props.children === '이 프로젝트에서 새 작업')[0];
    assert.match(start.props.className, /button--primary/, 'new work stays the main action when no existing groups are known');
    assert.equal(start.props.disabled, undefined); start.props.onClick();
    assert.deepEqual(started, ['Project 1']); assert.equal(harness.slots[1], '');
    assert.deepEqual(calls, [['runs.list', 'Project 0'], ['runs.list', 'Project 1']]);
  }
});

test('running work stays visible ahead of new work even when activity arrives after the user collapsed other groups', async () => {
  const opened = []; const requests = [];
  const harness = overviewHarness({ request: async (method) => {
    requests.push(method); assert.equal(method, 'runs.list');
    return [summary('live'), summary('failed', { stage: 'failed' })];
  } });
  const props = { projects: projects.slice(0, 1), active: emptyActive, onOpen: (...args) => opened.push(args), onRegister: () => {} };
  harness.render(props); harness.flushEffects(); await new Promise(setImmediate);
  let tree = harness.render(props);
  elements(tree, (item) => item.props.className === 'project-work-card')[0].props.onClick();
  tree = harness.render(props);
  elements(tree, (item) => item.props.className === 'project-work-bucket__toggle')[0].props.onClick();
  const updatedProps = { ...props, active: { ...emptyActive, items: [{ project_name: 'Project 0', run_id: 'live', status: 'active', activity_kinds: ['task'] }] } };
  tree = harness.render(updatedProps);
  const sections = elements(tree, (item) => item.props.className === 'project-work-bucket');
  assert.deepEqual(sections.map((section) => section.props['data-bucket']), ['running', 'attention']);
  const running = sections[0];
  assert.equal(elements(running, (item) => item.props.className === 'project-work-bucket__toggle').length, 0, 'running work needs no expansion step');
  assert.equal(elements(running, (item) => item.type === 'div')[0].props.hidden, false);
  const attention = elements(sections[1], (item) => item.type === 'button' && item.props.className === 'project-work-bucket__toggle')[0];
  assert.equal(attention.props['aria-expanded'], false, 'other explicit collapsed choices survive the refresh');
  const open = elements(running, (item) => item.type === 'button' && item.props.children === '작업 열기')[0];
  assert.match(open.props.className, /button--primary/);
  const create = elements(tree, (item) => item.type === 'button' && item.props.children === '이 프로젝트에서 새 작업')[0];
  assert.match(create.props.className, /button--secondary/);
  const markup = renderToStaticMarkup(tree);
  assert.ok(markup.indexOf('data-bucket="running"') < markup.indexOf('data-bucket="attention"'));
  assert.ok(markup.indexOf('data-bucket="attention"') < markup.indexOf('이 프로젝트에서 새 작업'));
  assert.deepEqual(opened, []); assert.deepEqual(requests, ['runs.list']);
  open.props.onClick();
  assert.deepEqual(opened, [['Project 0', 'live', false]]); assert.equal(harness.slots[1], '');
});

test('project status popup keeps status and navigation without mounting execution or lock controls', async () => {
  const {RunLockNotice}=require(join(output,'renderer/src/RunLockNotice.js'));
  for(const situation of ['running','resumable','attention_required']){
    const calls=[],opened=[];
    const h=overviewHarness({request:async(method)=>{
      calls.push(method);
      if(method==='runs.list')return [summary('selected',{execution_situation:situation})];
      if(method==='runs.get')return {id:'selected',execution_control:{situation,stop_phase:situation==='resumable'?'stopped':'',action:'resume'}};
      assert.fail(`project popup cannot request ${method}`);
    }});
    const props={projects:projects.slice(0,1),active:emptyActive,onOpen:(...args)=>opened.push(args),onRegister(){}};
    h.render(props);h.flushEffects();await new Promise(setImmediate);
    let tree=h.render(props);elements(tree,n=>n.props.className==='project-work-card')[0].props.onClick();tree=h.render(props);
    assert.equal(elements(tree,n=>n.type===RunLockNotice).length,0);
    const html=renderToStaticMarkup(tree);
    assert.doesNotMatch(html,/작업 중지|잠금 해제|잠금 기록|원본 상태 확인/);
    assert.match(html,/완료 Task/);assert.match(html,/작업 열기/);assert.match(html,/이 프로젝트에서 새 작업/);
    assert.ok(calls.every(method=>['runs.list','runs.get'].includes(method)));
    assert.deepEqual(opened,[]);
    elements(tree,n=>n.type==='button'&&n.props.children==='작업 열기')[0].props.onClick();
    assert.deepEqual(opened,[['Project 0','selected',false]]);
  }
});

test('global new work separates existing and new projects, then preserves existing work before adding a group', () => {
  const selected = []; const started = []; let cancelled = 0;
  const harness = overviewHarness({ request: () => assert.fail('card navigation itself must not issue work requests') });
  const props = { projects: projects.slice(0, 2), active: emptyActive, choosingNewWork: true,
    onCancelNewWork: () => cancelled++, onSelectProject: (name) => selected.push(name), onNewWork: (name) => started.push(name),
    onOpen: () => assert.fail('no existing group was chosen'), onRegister: () => {} };
  let tree = harness.render(props);
  assert.match(renderToStaticMarkup(tree), /기존 프로젝트 열기/);
  elements(tree, (item) => item.props.className === 'new-work-entry__card')[0].props.onClick();
  tree = harness.render(props);
  const card = elements(tree, (item) => item.props.className === 'project-work-card')[1];
  assert.equal(card.props['aria-haspopup'], 'dialog');
  card.props.onClick();
  assert.deepEqual(started, []); assert.deepEqual(selected, ['Project 1']);
  tree = harness.render(props);
  elements(tree, (item) => item.type === 'button' && item.props.children === '이 프로젝트에서 새 작업')[0].props.onClick();
  assert.deepEqual(started, ['Project 1']); assert.equal(harness.slots[1], '');
  elements(tree, (item) => item.type === 'button' && item.props.children === '선택 취소')[0].props.onClick();
  assert.equal(cancelled, 1);
  tree = harness.render({ ...props, choosingNewWork: false });
  const normalCard = elements(tree, (item) => item.props.className === 'project-work-card')[0];
  assert.equal(normalCard.props['aria-haspopup'], 'dialog'); normalCard.props.onClick();
  assert.deepEqual(selected, ['Project 1', 'Project 0']); assert.deepEqual(started, ['Project 1']);
});
test('project query failure preserves prior results; popup expansion survives refresh and group opening closes it', async () => {
  let fail = false; const opened = [];
  const harness = overviewHarness({ request: async (method, params) => {
    assert.equal(method, 'runs.list');
    if (fail && params.projectName === 'Project 0') throw new Error('partial failure');
    return [summary('same', { stage: 'failed' }), summary('complete', { pipeline_complete: true })];
  } });
  const props = { projects: projects.slice(0, 2), active: emptyActive, onOpen: (...args) => opened.push(args), onRegister: () => {} };
  harness.render(props); harness.flushEffects();
  await new Promise(setImmediate);
  let tree = harness.render(props);
  elements(tree, (item) => item.props?.className === 'project-work-card')[0].props.onClick();
  tree = harness.render(props);
  const toggles = elements(tree, (item) => item.props?.className === 'project-work-bucket__toggle');
  assert.equal(toggles[0].props['aria-expanded'], true);
  toggles[1].props.onClick();
  fail = true;
  tree = harness.render(props);
  elements(tree, (item) => item.type === 'button' && String(item.props.children).includes('현황 새로고침'))[0].props.onClick();
  await new Promise(setImmediate);
  tree = harness.render(props);
  assert.match(renderToStaticMarkup(tree), /partial failure/);
  assert.equal(harness.slots[0]['Project 0'].groups.length, 2);
  assert.deepEqual(Array.from(harness.slots[2]['Project 0']), ['attention', 'completed']);
  elements(tree, (item) => item.type === 'button' && item.props.children === '작업 열기')[0].props.onClick();
  assert.deepEqual(opened, [['Project 0', 'same', false]]);
  assert.equal(harness.slots[1], '');
});

test('completed records combine completed current groups and archives without opening a different scope', async () => {
  const calls = [];
  const harness = overviewHarness({ request: async (method, params) => {
    calls.push(params.scope);
    return params.scope === 'active' ? [summary('waiting'), summary('finished', { pipeline_complete: true })]
      : [summary('archive', { archived: true })];
  } });
  const opened = [];
  const props = { projects: projects.slice(0, 1), active: emptyActive, history: true,
    onOpen: (...args) => opened.push(args), onRegister: () => {} };
  harness.render(props); harness.flushEffects(); await new Promise(setImmediate);
  assert.deepEqual(calls, ['active', 'archived']);
  assert.deepEqual(Array.from(harness.slots[0]['Project 0'].groups, (item) => item.id), ['finished', 'archive']);
  let tree = harness.render(props);
  elements(tree, (item) => item.props?.className === 'project-work-card')[0].props.onClick();
  tree = harness.render(props);
  elements(tree, (item) => item.type === 'button' && item.props.children === '작업 열기').at(-1).props.onClick();
  assert.deepEqual(opened, [['Project 0', 'finished', false]]);
  tree = harness.render(props);
  elements(tree, (item) => item.props?.className === 'project-work-card')[0].props.onClick();
  tree = harness.render(props);
  elements(tree, (item) => item.type === 'button' && item.props.children === '작업 열기')[0].props.onClick();
  assert.deepEqual(opened.at(-1), ['Project 0', 'archive', true]);
});

test('manual stop comes from public execution control; a failed detail read is unknown, then stale stop evidence clears', async () => {
  let detailFailure = false; let situation = 'resumable';
  const harness = overviewHarness({ request: async (method, params) => {
    if (method === 'runs.list') return [summary('stop', { execution_situation: situation, attention_reasons: situation === 'resumable' ? ['resume'] : [] })];
    assert.equal(method, 'runs.get'); assert.equal(params.runId, 'stop');
    if (detailFailure) throw new Error('control query failed');
    return { id: 'stop', execution_control: { stop_phase: 'stopped', action: 'resume' } };
  } });
  const props = { projects: projects.slice(0, 1), active: emptyActive, onOpen: () => {}, onRegister: () => {} };
  harness.render(props); harness.flushEffects(); await new Promise(setImmediate);
  let cards = projectWork(props.projects, harness.slots[0], emptyActive);
  assert.equal(cards[0].groups[0].bucket, 'waiting'); assert.match(cards[0].groups[0].reason, /중지됨.*재개 가능/);
  const refresh = async () => { const tree = harness.render(props);
    elements(tree, (item) => item.type === 'button' && String(item.props.children).includes('현황 새로고침'))[0].props.onClick();
    await new Promise(setImmediate); };
  detailFailure = true; await refresh();
  cards = projectWork(props.projects, harness.slots[0], emptyActive);
  assert.equal(cards[0].unknown, true); assert.equal(cards[0].groups[0].bucket, 'attention');
  assert.match(harness.slots[0]['Project 0'].controlErrors.stop, /control query failed/);
  detailFailure = false; situation = 'ready'; await refresh();
  cards = projectWork(props.projects, harness.slots[0], emptyActive);
  assert.equal(cards[0].unknown, false); assert.doesNotMatch(cards[0].groups[0].reason, /중지됨/);
});

test('late project results cannot replace a newer registry snapshot', async () => {
  const pending = [];
  const harness = overviewHarness({ request: () => new Promise((resolve) => pending.push(resolve)) });
  const props = { active: emptyActive, onOpen: () => {}, onRegister: () => {} };
  harness.render({ ...props, projects: projects.slice(0, 1) });
  const cleanup = harness.flushEffects();
  cleanup();
  harness.render({ ...props, projects: projects.slice(1, 2) });
  harness.flushEffects();
  pending[1]([summary('current')]); await new Promise(setImmediate);
  pending[0]([summary('old')]); await new Promise(setImmediate);
  assert.deepEqual(Object.keys(harness.slots[0]), ['Project 1']);
  assert.equal(harness.slots[0]['Project 1'].groups[0].id, 'current');
});

test('opening during the first lookup expands its first real bucket and preserves deliberately collapsed buckets', async () => {
  let reply;
  const harness = overviewHarness({ request: () => new Promise((resolve) => { reply = resolve; }) });
  const props = { projects: projects.slice(0, 1), active: emptyActive, onOpen: () => {}, onRegister: () => {} };
  let tree = harness.render(props); harness.flushEffects();
  elements(tree, (item) => item.props?.className === 'project-work-card')[0].props.onClick();
  assert.equal(harness.slots[2]['Project 0'], undefined);
  reply([summary('attention', { stage: 'failed' })]); await new Promise(setImmediate);
  tree = harness.render(props);
  let toggle = elements(tree, (item) => item.props?.className === 'project-work-bucket__toggle')[0];
  assert.equal(toggle.props['aria-expanded'], true);
  toggle.props.onClick(); tree = harness.render(props);
  toggle = elements(tree, (item) => item.props?.className === 'project-work-bucket__toggle')[0];
  assert.equal(toggle.props['aria-expanded'], false);
  elements(tree, (item) => item.props?.className === 'project-work-card')[0].props.onClick(); tree = harness.render(props);
  assert.equal(elements(tree, (item) => item.props?.className === 'project-work-bucket__toggle')[0].props['aria-expanded'], false);
});

test('native Task dialog Escape closes only the surface and restores focus; children and requests are retained', () => {
  const file = join(output, 'renderer/src/WorkDialog.js');
  const localRequire = createRequire(file);
  let closed = 0; let shown = 0; let focused = 0; let prevented = 0;
  class Element { constructor() { this.isConnected = true; } focus() { focused++; } }
  const origin = new Element();
  const dialog = { showModal: () => shown++, close: () => closed++ };
  const effects = []; let index = 0;
  const refs = [{ current: dialog }, { current: null }];
  const exported = {};
  runInNewContext(readFileSync(file, 'utf8'), { exports: exported, HTMLElement: Element, document: { activeElement: origin },
    require(name) { if (name !== 'react') return localRequire(name);
      return { useRef: () => refs[index++], useEffect: (effect) => effects.push(effect) }; } });
  const draft = { text: 'keep this draft', busy: true };
  let viewClosed = 0;
  const tree = exported.WorkDialog({ title: 'Task 3', children: draft, onClose: () => viewClosed++ });
  const cleanup = effects[0]();
  assert.equal(shown, 1);
  tree.props.onCancel({ preventDefault: () => prevented++ });
  assert.equal(viewClosed, 1); assert.equal(prevented, 1);
  elements(tree, (item) => item.type === 'button' && item.props.children === '닫기')[0].props.onClick();
  assert.equal(viewClosed, 2);
  assert.equal(draft.text, 'keep this draft'); assert.equal(draft.busy, true);
  cleanup(); assert.equal(closed, 1); assert.equal(focused, 1);
});

function appCallback(name, context) {
  const source = readFileSync(join(output, 'renderer/src/App.js'), 'utf8');
  const match = source.match(new RegExp(`^    const ${name} = [\\s\\S]*?(?=^    (?:const|let|return) )`, 'm'));
  assert.ok(match);
  context.setWorkDetailsOpen ??= () => {};
  context.setRepairTarget ??= () => {};
  context.failedTaskQuestionDrafts_1 ??= require(join(output, 'renderer/src/failedTaskQuestionDrafts.js'));
  context.failedQuestionDrafts ??= { current: new context.failedTaskQuestionDrafts_1.FailedTaskQuestionDrafts() };
  context.nextExecutionProfileDirty ??= false;
  context.busyAction ??= '';
  context.executionAction ??= '';
  context.taskProfileOptions ??= {};
  context.taskDrafts ??= [];
  context.openTaskPlanning ??= () => assert.fail('unexpected chat navigation');
  context.taskProfileComparison_1 ??= require(join(output, 'renderer/src/taskProfileComparison.js'));
  context.chatTaskRecovery_1 ??= require(join(output, 'renderer/src/chatTaskRecovery.js'));
  context.chatExecutionControl_1 ??= require(join(output, 'renderer/src/chatExecutionControl.js'));
  context.taskPlanningRequestsRef ??= { current: {} };
  context.planningPreviewRequest_1 ??= require(join(output, 'renderer/src/planningPreviewRequest.js'));
  context.react_1 = { useCallback: (callback) => callback };
  context.TaskStatusOverview_1 = require(join(output, 'renderer/src/TaskStatusOverview.js'));
  context.taskContinuation_1 = { canContinueTaskRetry };
  context.runExecutionControl_1 = { runRequestKey: context.runRequestKey, runContextMatches: context.runContextMatches,
    isRunStageMismatchError: context.isRunStageMismatchError };
  runInNewContext(`${match[0]}\nthis.tested = ${name};`, context); return context.tested;
}

test('completed-result action opens the full group result, closes task detail and focuses its destination without execution', () => {
  const calls=[];const forbidden=()=>assert.fail('result navigation must not execute or open another action');
  const context={selectedRun:{id:'completed',stage:'pushed',waiting_prompt:null},
    focusWorkbenchTarget:id=>calls.push(['focus',id]),setSideInspectorOpen:value=>calls.push(['detail',value]),
    setResultFocusTaskId:id=>calls.push(['resultTask',id]),setWorkbenchView:view=>calls.push(['view',view]),
    invokeWaitingAction:forbidden,openApplySummary:forbidden,openLinkedTaskDetail:forbidden,openTaskLog:forbidden,
    refreshSelectedRunStatus:forbidden,requestRunAction:forbidden,savePlan:forbidden,setCurrentTaskContentView:forbidden,setSelectedTaskId:forbidden};
  appCallback('invokeNextAction',context)({kind:'result'});
  assert.deepEqual(calls,[['detail',false],['resultTask',''],['view','results'],['focus','results-workbench-title']]);
});

test('planning and auxiliary lock errors never propose clearing an unrelated execution lock', async () => {
  const calls = [];
  const recover = appCallback('recoverStaleRunLock', {
    runLockConflictOperation: appComponents.runLockConflictOperation,
    rawErrorMessage: (error) => error.message,
    window: { orchestrator: { request: (...args) => calls.push(args), approve: (...args) => calls.push(args) } },
  });
  for (const operation of ['planning-chat', 'planning-preview', 'effort-policy', 'execution-control', 'usage',
    'revision-proposal', 'revision-request', 'unknown']) {
    assert.equal(await recover('project', 'group', new Error(`run group is already locked (operation=${operation}, pid=123)`)), 'not-stale');
  }
  assert.equal(await recover('project', 'group', new Error('run other-group is already locked (operation=execute, pid=123)')), 'not-stale');
  assert.equal(await recover('project', 'group', new Error('run group is already locked')), 'not-stale');
  assert.deepEqual(calls, []);
});

test('execution lock recovery requires a fresh stale owner matching the error target and operation', async () => {
  for (const [lock, approval, expected] of [
    [{ state: 'active' }, true, 'not-stale'], [{ state: 'unverifiable' }, true, 'not-stale'],
    [{ state: 'malformed' }, true, 'not-stale'], [{ state: 'unlocked' }, true, 'not-stale'],
    [{ state: 'stale', operation: 'verify' }, true, 'not-stale'],
    [{ state: 'stale', run_id: 'other-group' }, true, 'not-stale'],
    [{ state: 'stale' }, true, 'recovered'], [{ state: 'stale' }, null, 'cancelled'],
  ]) {
    const calls = [];
    const recover = appCallback('recoverStaleRunLock', {
      runLockConflictOperation: appComponents.runLockConflictOperation, rawErrorMessage: (error) => error.message,
      window: { orchestrator: {
        request: async (method, params) => { calls.push([method, params.projectName, params.runId]); return { run_id: 'group', operation: 'execute', ...lock }; },
        approve: async (method, params) => { calls.push([method, params.projectName, params.runId]); return approval; },
      } },
    });
    assert.equal(await recover('project', 'group', new Error('run group is already locked (operation=execute, pid=123)')), expected);
    assert.deepEqual(calls, expected === 'not-stale' ? [['locks.get', 'project', 'group']]
      : [['locks.get', 'project', 'group'], ['locks.clear', 'project', 'group']]);
  }
});

test('planning lock banners preserve the exact error in closed details and distinguish policy saves', () => {
  for (const operation of ['planning-chat', 'planning-preview', 'effort-policy']) {
    const message = `Error invoking remote method: run group is already locked (operation=${operation}, pid=123, host=example)`;
    const tree = appComponents.ApplicationErrorBanner({ message });
    const details = elements(tree, (item) => item.type === 'details');
    assert.equal(details.length, 1); assert.ok(!details[0].props.open);
    assert.match(renderToStaticMarkup(details[0]), new RegExp(`operation=${operation}`));
    const copy = elements(tree, (item) => item.type === 'p').map((item) => renderToStaticMarkup(item)).join('');
    assert.match(copy, operation === 'effort-policy' ? /AI 설정 저장 잠금/ : /(Planning AI 대화|변경 미리보기) 잠금/);
    assert.match(copy, /작업 실행 잠금과는 별개/);
  }
});

test('new work restores the chosen registered project draft and clears old group navigation without creating or running it', () => {
  const state = { home: 'overview', run: 'old-group', view: 'tasks', inspector: true, picking: true, notices: [] };
  const restored = []; const selected = []; const focused = [];
  const drafts = { 'Project 0': '원래 프로젝트 초안', 'Project 1': '선택 프로젝트 초안' };
  const context = { projectsRef: { current: [{ name: 'Project 0', planning_source_dir: 'Docs/A' }, { name: 'Project 1', planning_source_dir: 'Docs/B' }] },
    pendingGlobalGroupRef: { current: { projectName: 'Project 0', runId: 'old-group' } }, pendingNotificationRef: { current: {} }, pendingAttentionRef: { current: {} },
    newWorkProjectRef: { current: '' }, selectedContextRef: { current: { projectName: 'Project 0', runId: 'old-group' } },
    runDetailRequestRef: { current: 2 }, archiveScopeRef: { current: 'archived' },
    selectProject: (name) => selected.push(name), restorePlanningDraft: (name, path) => restored.push([name, path, drafts[name]]),
    setSelectedRunId: (id) => { state.run = id; }, setSelectedRun: () => {}, setSelectedRunProjectName: () => {}, setSelectedTaskIds: () => {},
    setArchiveScope: (scope) => { state.scope = scope; }, setChoosingNewWorkProject: (picking) => { state.picking = picking; },
    setHomeView: (home) => { state.home = home; }, setSideInspectorOpen: (open) => { state.inspector = open; },
    setWorkbenchView: (view) => { state.view = view; }, setNotice: (notice) => state.notices.push(notice),
    window: { requestAnimationFrame: (fn) => fn() }, document: { querySelector: (selector) => ({ focus: () => focused.push(selector) }) } };
  const start = appCallback('startProjectWork', context);
  start('missing');
  assert.equal(state.home, 'overview'); assert.equal(state.run, 'old-group'); assert.equal(selected.length, 0);
  assert.match(state.notices[0], /등록 목록에 없습니다/);
  start('Project 1');
  assert.deepEqual(selected, ['Project 1']);
  assert.deepEqual(restored, [['Project 1', 'Docs/B', '선택 프로젝트 초안']]);
  assert.equal(state.home, 'work'); assert.equal(state.view, 'planning'); assert.equal(state.run, '');
  assert.equal(state.inspector, false); assert.equal(state.picking, false); assert.equal(state.scope, 'active');
  assert.equal(context.selectedContextRef.current.projectName, 'Project 1'); assert.equal(context.selectedContextRef.current.runId, '');
  assert.equal(context.newWorkProjectRef.current, 'Project 1'); assert.equal(context.pendingGlobalGroupRef.current, undefined);
  assert.deepEqual(drafts, { 'Project 0': '원래 프로젝트 초안', 'Project 1': '선택 프로젝트 초안' });
  assert.deepEqual(focused, ['#planning-sidebar textarea']);
});

test('project selection navigation preserves the old work and focuses the project cards for either selection intent', () => {
  const state = {}; const focus = [];
  const context = { setChoosingNewWorkProject: (value) => { state.picking = value; }, setHomeView: (value) => { state.home = value; },
    setSideInspectorOpen: (value) => { state.inspector = value; }, window: { requestAnimationFrame: (fn) => fn() },
    document: { getElementById: (id) => ({ focus: () => focus.push(id) }) } };
  const open = appCallback('openProjectSelection', context);
  open(true); assert.equal(state.picking, true); assert.equal(state.home, 'overview'); assert.equal(state.inspector, false);
  open(); assert.equal(state.picking, false);
  assert.deepEqual(focus, ['chat-home-title', 'chat-home-title']);
});

test('a late group list updates the cache without replacing new planning; normal group selection and list errors stay visible', async () => {
  for (const scenario of ['new-planning', 'normal-selection', 'failed-query']) {
    let resolveList; let rejectList; let selectedRunId = ''; const errors = [];
    const context = { newWorkProjectRef: { current: '' }, selectedContextRef: { current: { projectName: 'Project 1', runId: 'old' } },
      archiveScopeRef: { current: 'active' }, runListRequestSequenceRef: { current: 0 }, runListRequestRef: { current: {} },
      runSummaryCacheRef: { current: {} }, authoritativeArchivesRef: { current: {} }, archiveRefreshFailureRef: { current: {} },
      pendingAttentionRef: { current: undefined }, pendingGlobalGroupRef: { current: undefined }, pendingNotificationRef: { current: undefined },
      setSelectedRun: () => {}, setLoading: () => {}, setError: (message) => errors.push(message), setRunSummaryCache: () => {},
      setRunListRefreshRetry: () => {}, setNotice: () => {}, errorMessage: (error) => error.message,
      setSelectedRunId: (value) => { selectedRunId = typeof value === 'function' ? value(selectedRunId) : value; },
      loadActiveGroups: () => {}, loadAttentionItems: () => {},
      runArchiveCache_1: require(join(output, 'renderer/src/runArchiveCache.js')),
      window: { orchestrator: { request: (method) => {
        assert.equal(method, 'runs.list'); return new Promise((resolve, reject) => { resolveList = resolve; rejectList = reject; });
      } } } };
    const request = appCallback('loadRuns', context)({ projectName: 'Project 1', scope: 'active', preferredRun: 'old' });
    if (scenario !== 'normal-selection') context.newWorkProjectRef.current = 'Project 1';
    context.selectedContextRef.current.runId = '';
    if (scenario === 'failed-query') rejectList(new Error('그룹 목록 조회 실패'));
    else resolveList([summary('old')]);
    await request;
    assert.equal(selectedRunId, scenario === 'normal-selection' ? 'old' : '');
    if (scenario === 'failed-query') assert.equal(errors.at(-1), '그룹 목록 조회 실패');
    else assert.equal(context.runSummaryCacheRef.current['Project 1'].active[0].id, 'old');
  }
});

test('actual App retry callback resumes only explicit successful current retry, with a fresh read before resume', async () => {
  for (const scenario of ['explicit', 'retry-only', 'stopped']) {
    const { before, latest } = retryStates();
    const current = scenario === 'stopped' ? { ...latest, execution_control: { ...latest.execution_control, stop_phase: 'stopped' } } : latest;
    const calls = []; const notices = [];
    const context = { selectedProjectName: 'Project 0', selectedRun: before, taskProfiles: {},
      selectedContextRef: { current: { projectName: 'Project 0', runId: 'run' } }, executionRequestSequenceRef: { current: 0 },
      liveRunActionMethods: new Set(['tasks.retry', 'runs.resume']), runRequestKey: () => 'scope',
      canContinueTaskRetry, profileOverrides: () => ({}), recoverStaleRunLock: async () => 'not-stale',
      replaceRun: () => {}, runContextMatches: () => true, isRunStageMismatchError: () => false,
      rawErrorMessage: (error) => String(error), errorMessage: (error) => String(error),
      setExecutionRequests: () => {}, setBusyAction: () => {}, setNotice: (text) => notices.push(text),
      setError: (text) => { if (text) assert.fail(text); },
      window: { setInterval: () => 1, clearInterval: () => {}, orchestrator: { request: async (method) => { calls.push(method); return current; } } } };
    await appCallback('requestRunAction', context)('tasks.retry', 'fix', scenario !== 'retry-only');
    assert.equal(calls.filter((method) => method === 'tasks.retry').length, 1);
    assert.equal(calls.includes('runs.resume'), scenario === 'explicit');
    if (scenario === 'explicit') assert.equal(calls[calls.indexOf('runs.resume') - 1], 'runs.get');
    if (scenario === 'stopped') assert.match(notices.at(-1), /남은 작업을 시작하지 않았습니다/);
  }
});

test('actual execution callbacks reject unsaved next-model edits before issuing any request', async () => {
  for (const method of ['runs.execute', 'runs.resume', 'tasks.execute', 'tasks.retry']) {
    const errors = [];
    const context = { selectedProjectName: 'project', selectedRun: { id: 'group' }, nextExecutionProfileDirty: true,
      taskProfiles: {}, recoverStaleRunLock() {}, replaceRun() {}, setError: value => errors.push(value) };
    await appCallback('requestRunAction', context)(method, 'task');
    assert.equal(errors.length, 1); assert.match(errors[0], /모델 변경을 저장하거나 취소/);
  }
});

test('planned execution rejects unavailable task models before any backend request', async () => {
  for (const method of ['runs.execute', 'tasks.execute']) {
    const calls = [], notices = [];
    const task = { id: 'task', status: 'pending', provider_id: 'claude', agent_id: 'claude', model: 'retired' };
    const context = { selectedProjectName: 'project', selectedRun: { id: 'group', stage: 'planned', tasks: [task] },
      taskProfiles: { task: { agentId: 'claude', model: 'retired', reasoningEffort: '' } }, taskProfileOptions: { task: [] },
      recoverStaleRunLock() {}, replaceRun() {}, setNotice: value => notices.push(value), setWorkbenchView: value => calls.push(value),
      setWorkDetailsOpen: value => calls.push(value), window: { orchestrator: { request: () => assert.fail('unavailable models cannot execute') } } };
    await appCallback('requestRunAction', context)(method, method === 'tasks.execute' ? 'task' : undefined);
    assert.match(notices[0], /실행 AI를 먼저 확인/); assert.deepEqual(calls, ['tasks', true]);
  }
});

test('execution entry points also reject stale clicks while Task planning is in progress', async () => {
  for (const method of ['runs.execute', 'runs.resume', 'tasks.execute', 'tasks.retry']) {
    const notices = [];
    const context = { selectedProjectName: 'project', selectedRun: { id: 'group' }, taskProfiles: {},
      taskPlanningRequestsRef: { current: { request: { projectName: 'project', runId: 'group', taskId: 'task' } } },
      recoverStaleRunLock() {}, replaceRun() {}, setNotice: value => notices.push(value),
      window: { orchestrator: { request: () => assert.fail('must not start execution') } } };
    await appCallback('requestRunAction', context)(method, method.startsWith('tasks.') ? 'task' : undefined);
    assert.match(notices[0], /현재 Task 수정 중/);
  }
});

test('actual planning chat holds its captured Task until success or failure and then restores its actions', async () => {
  for (const fail of [false, true]) {
    let finish, reject;
    const errors = [], calls = [];
    const task = dialogTask({ id: 'task' });
    const run = workbenchRun({ tasks: [task], planning_messages: [], planning_provider_id: 'codex' });
    const context = { selectedProjectName: 'project', selectedRun: run, selectedPlanningProfile: undefined,
      selectedContextRef: { current: { projectName: 'project', runId: run.id } }, taskDrafts: [task],
      planningMessage: '실패 원인을 확인해서 Task 수정해줘', planningReasoning: '', planningProfileManual: false, planDirty: false,
      taskPlanningRequestsRef: { current: {} }, setTaskPlanningRequests() {}, crypto: require('node:crypto').webcrypto,
      directionChangeDrafts: { read: () => ({ text: '' }), edit() {} }, failedQuestionDrafts: { current: { diagnostic: () => '', release() {} } },
      failedTaskQuestionKey: () => '', planningMessageProfileParams: () => ({}), runContextMatches: () => true,
      planningRequestDrafts_1: require(join(output, 'renderer/src/planningRequestDrafts.js')),
      recoverStaleRunLock: async () => 'not-stale', replaceRun() {}, editedPlanningProfileContext: { current: '' },
      setPlanningProfileManual() {}, setPlanningMessage() {}, setPendingPlanningMessage() {}, setBusyAction() {},
      setError: value => { if (value) errors.push(value); }, setNotice() {}, setPlanningStartElapsed() {}, setPlanningPreparationMessage() {},
      errorMessage: error => error.message,
      window: { setInterval: () => 1, clearInterval() {}, orchestrator: { request(method) {
        calls.push(method);
        if (method === 'runs.sendPlanningMessage') return new Promise((resolve, no) => { finish = resolve; reject = no; });
        if (method === 'runs.getPlanningPreview') return Promise.resolve(null);
        assert.equal(method, 'runs.get'); return Promise.resolve(run);
      } } } };
    context.beginTaskPlanning = appCallback('beginTaskPlanning', context);
    const pending = appCallback('sendPlanningMessage', context)(undefined, task.id);
    await new Promise(setImmediate);
    const { taskPlanningInProgress } = context.planningPreviewRequest_1;
    assert.equal(taskPlanningInProgress(context.taskPlanningRequestsRef.current, 'project', run.id, task.id), true,
      JSON.stringify({ requests: context.taskPlanningRequestsRef.current, calls, errors }));
    context.selectedContextRef.current = { projectName: 'other', runId: 'other' };
    if (fail) reject(new Error('model unavailable')); else finish(run);
    await pending;
    assert.equal(Object.keys(context.taskPlanningRequestsRef.current).length, 0);
    assert.equal(calls.filter(method => method === 'runs.sendPlanningMessage').length, 1);
    assert.equal(errors.length, fail ? 1 : 0);
  }
});

test('chat recovery dispatches once, reports progress immediately and preserves failed or newer drafts', async () => {
  for (const projectChat of [false, true])
  for (const scenario of ['success', 'failed', 'edited', 'switched', 'button', 'button-failed', ...(projectChat ? ['scope-apply'] : [])]) {
    const control = require(join(output, 'renderer/src/runExecutionControl.js'));
    const { DirectionChangeDrafts } = require(join(output, 'renderer/src/directionChangeDrafts.js'));
    const task = dialogTask({id:'task',status:'failed',last_attempt_id:'attempt',
      ...(scenario === 'scope-apply' ? {error:'task_scope_review_required: {"paths":["src/A.cs"]}'} : {})});
    const run = workbenchRun({id:'group',stage:'failed',failed_step:'agent_execution',active_step:null,
      plan_revision:3,planning_conversation_revision:2,tasks:[task],planning_messages:[],project_chat_available:projectChat});
    const buttonRequest = scenario.startsWith('button');
    const draftText = buttonRequest ? '작성 중인 별도 질문' : scenario === 'scope-apply' ? '반영해줘' : '고쳐서 계속해줘';
    const submittedText = buttonRequest ? '고쳐서 계속해줘' : draftText;
    const drafts = new DirectionChangeDrafts(); drafts.edit('project','group',draftText);
    drafts.edit('other','other-group','other draft');
    const calls=[],errors=[];let resolveContext,resolveWork,rejectWork,execution={},pending;
    const context = {selectedProjectName:'project',selectedRun:run,taskDrafts:[task],planningMessage:draftText,
      planningReasoning:'',planningProfileManual:false,selectedPlanningProfile:undefined,planDirty:false,
      directionChangeDrafts:drafts,beginTaskPlanning:()=>assert.fail('must not ask read-only AI before execution'),
      chatRecoveryPendingRef:{current:new Set()},executionRequestSequenceRef:{current:0},
      selectedContextRef:{current:{projectName:'project',runId:'group'}},
      runRequestKey:control.runRequestKey,runContextMatches:control.runContextMatches,crypto:require('node:crypto').webcrypto,
      setPlanningMessage:value=>drafts.edit('project','group',value),
      setPendingPlanningMessage:value=>{pending=typeof value==='function'?value(pending):value;},
      setExecutionRequests:fn=>{execution=fn(execution);},setError:v=>{if(v)errors.push(v);},setNotice(){},replaceRun(){},
      errorMessage:e=>e.message,recoverStaleRunLock:async()=>assert.fail('no hidden repeat'),
      window:{setInterval:()=>1,clearInterval(){},orchestrator:{request:async(method,params)=>{
        calls.push([method,params]);
        if(method==='runs.controlChat')return new Promise((resolve,reject)=>{resolveWork=resolve;rejectWork=reject;});
        assert.equal(method,'runs.get');return run;
      }}},
    };
    const send=appCallback('sendPlanningMessage',context);
    const submit=()=>buttonRequest?send('고쳐서 계속해줘','task'):send();
    const operation=submit();
    assert.equal(Object.values(execution)[0].method,projectChat?'runs.controlChat':'tasks.repairFromChat');
    assert.equal(Object.values(execution)[0].chatPhase,projectChat?'thinking':'repairing');
    assert.equal(pending.text,submittedText);assert.equal(drafts.read('project','group').text,buttonRequest?draftText:'');
    await submit();await new Promise(setImmediate);
    assert.equal(calls.filter(([method])=>method==='runs.controlChat').length,1,'rapid duplicate cannot start a second context check or retry');
    if(scenario==='switched')context.selectedContextRef.current={projectName:'other',runId:'other-group'};
    await new Promise(setImmediate);
    {
      assert.equal(calls.filter(([m])=>m==='runs.controlChat').length,1);
      if(['success','button','switched','scope-apply'].includes(scenario))resolveWork({...run,planning_messages:[{role:'user',text:submittedText}]});
      else {if(scenario==='edited')drafts.edit('project','group','newer text');rejectWork(new Error('failure changed'));}
    }
    await operation;
    assert.equal(Object.keys(execution).length,0);assert.equal(context.chatRecoveryPendingRef.current.size,0);
    assert.equal(pending,undefined);
    assert.equal(drafts.read('project','group').text,buttonRequest?draftText:['success','switched','scope-apply'].includes(scenario)?'':scenario==='edited'?'newer text':'고쳐서 계속해줘');
    assert.equal(drafts.read('other','other-group').text,'other draft');
    assert.equal(errors.length,['failed','edited','button-failed'].includes(scenario)?1:0);
    assert.ok(calls.every(([m])=>['runs.controlChat','runs.get'].includes(m)));
  }
});

test('chat command failures use their confirmed conversation reply once and keep unrecorded failures visible', async () => {
  for (const scenario of ['recorded', 'ack-only', 'unrelated-error', 'old-error', 'later-user', 'refresh-failed', 'wrong-run', 'switched', 'poll-in-flight']) {
    const command = '고쳐서 계속해줘';
    const detail = 'policy_plan_review_required: selected effort mode differs from the approved plan';
    const error = `Error invoking remote method 'orchestrator:request': PythonBridgeRequestError: application_error: ${detail}`;
    const user = { role: 'user', text: command };
    const reply = { role: 'assistant', text: `복구를 진행하지 못했습니다. ${detail}` };
    const acknowledgement = { role: 'assistant', text: '중지·복구 요청을 접수했습니다.' };
    const task = dialogTask({ id: 'task', status: 'failed', last_attempt_id: 'attempt' });
    const run = workbenchRun({ id: 'group', stage: 'failed', failed_step: 'agent_execution', active_step: null,
      tasks: [task], planning_messages: scenario === 'old-error' ? [user, reply] : [] });
    const messages = [...run.planning_messages, user, acknowledgement];
    if (scenario === 'later-user') messages.push({ role: 'user', text: '다른 명령' });
    if (!['ack-only', 'old-error'].includes(scenario)) messages.push(scenario === 'unrelated-error'
      ? { ...reply, text: '복구를 진행하지 못했습니다. 다른 오류' } : reply);
    const latest = { ...run, id: scenario === 'wrong-run' ? 'other-group' : run.id, planning_messages: messages };
    const { DirectionChangeDrafts } = require(join(output, 'renderer/src/directionChangeDrafts.js'));
    const drafts = new DirectionChangeDrafts(); drafts.edit('project', run.id, command);
    const errors = [], observed = [], calls = [];
    let interval, rejectWork, resolvePoll, execution = {}, pending;
    const control = require(join(output, 'renderer/src/runExecutionControl.js'));
    const context = {
      selectedProjectName: 'project', selectedRun: run, taskDrafts: [task], planningMessage: command, planDirty: false,
      planningReasoning: '', planningProfileManual: false, selectedPlanningProfile: undefined,
      beginTaskPlanning: () => assert.fail('execution control does not call the planning AI'),
      recoverStaleRunLock: async () => assert.fail('the failed command must not be repeated'),
      directionChangeDrafts: drafts, chatRecoveryPendingRef: { current: new Set() }, executionRequestSequenceRef: { current: 0 },
      selectedContextRef: { current: { projectName: 'project', runId: run.id } },
      runRequestKey: control.runRequestKey, runContextMatches: control.runContextMatches, crypto: require('node:crypto').webcrypto,
      setPlanningMessage: value => drafts.edit('project', run.id, value),
      setPendingPlanningMessage: value => { pending = typeof value === 'function' ? value(pending) : value; },
      setExecutionRequests: fn => { execution = fn(execution); }, setError: value => { if (value) errors.push(value); },
      setNotice() {}, replaceRun: (project, updated) => observed.push(updated), errorMessage: cause => cause.message,
      window: { setInterval: callback => { interval = callback; return 1; }, clearInterval() {}, orchestrator: {
        request(method) {
          calls.push(method);
          if (method === 'runs.controlChat') return new Promise((resolve, reject) => { rejectWork = reject; });
          assert.equal(method, 'runs.get');
          if (scenario === 'refresh-failed') return Promise.reject(new Error('refresh unavailable'));
          if (scenario === 'poll-in-flight' && !resolvePoll) return new Promise(resolve => { resolvePoll = resolve; });
          return Promise.resolve(latest);
        },
      } },
    };
    const operation = appCallback('sendPlanningMessage', context)();
    if (scenario === 'poll-in-flight') { interval(); await new Promise(setImmediate); }
    if (scenario === 'switched') context.selectedContextRef.current = { projectName: 'other', runId: 'other-group' };
    rejectWork(new Error(error));
    await operation;
    if (resolvePoll) { resolvePoll(run); await new Promise(setImmediate); }
    const duplicateHandled = ['recorded', 'poll-in-flight', 'switched'].includes(scenario);
    assert.equal(errors.length, duplicateHandled ? 0 : 1, scenario);
    if (errors.length) assert.equal(errors[0], error);
    if (!['refresh-failed', 'wrong-run'].includes(scenario)) assert.equal(observed.at(-1), latest, scenario);
    else assert.equal(observed.length, 0, scenario);
    assert.equal(latest.stage, 'failed');
    assert.equal(calls.filter(method => method === 'runs.controlChat').length, 1);
    assert.equal(Object.keys(execution).length, 0);
    assert.equal(pending, undefined);
  }
});

test('actual Task open and close callbacks retain drafts and never issue execution or AI cancellation', () => {
  const selection = []; const surfaces = []; const views = [];
  const drafts = { repair: 'keep repair', direction: 'keep direction', plan: 'keep plan', aiPending: true };
  const context = { setSelectedTaskId: (id) => selection.push(id), setInspectorTab: () => {},
    setSideInspectorOpen: (open) => surfaces.push(open), setCurrentTaskContentView: (view) => views.push(view),
    sideInspectorOpen: false, workbenchLayout: 'wide', selectedRun: undefined, selectedTaskId: '',
    selectedProjectName: '', busyAction: '', executionAction: '', emptyManualTasksRef: { current: {} },
    emptyTaskValidationMessage: '',
    discardUntouchedTask: () => assert.fail('an existing task does not need blank-draft cancellation') };
  appCallback('openTaskDetail', context)('fix');
  appCallback('closeInspector', context)();
  assert.deepEqual(selection, ['fix']); assert.deepEqual(surfaces, [true, false]);
  assert.deepEqual(views, ['list', 'list']);
  assert.deepEqual(drafts, { repair: 'keep repair', direction: 'keep direction', plan: 'keep plan', aiPending: true });
});

test('actual Task-card and linked-task callbacks open chat after planning without opening the status popup', () => {
  for (const name of ['openTaskDetail','openLinkedTaskDetail']) {
    for (const status of ['failed','running','completed','pending','stopped']) {
      const calls=[];
      const context={selectedRun:{stage:'executing',tasks:[{id:'fix',status}]},taskDrafts:[],
        openTaskPlanning:id=>calls.push(['chat',id]),setSelectedTaskId:()=>assert.fail('chat owns the target'),
        setInspectorTab:()=>assert.fail('no status popup'),setSideInspectorOpen:()=>assert.fail('no status popup'),
        setCurrentTaskContentView:()=>assert.fail('no detail navigation'),sideInspectorOpen:false,workbenchLayout:'wide'};
      appCallback(name,context)('fix');
      assert.deepEqual(calls,[['chat','fix']],`${name}/${status}`);
    }
  }
});

test('actual close callback only requests blank-draft cancellation in the original idle context', () => {
  for (const changes of [{}, { busyAction: 'runs.updatePlan' }, { executionAction: 'runs.execute' }, { selectedTaskId: 'renamed' }]) {
    const calls = []; const blank = { id: 'task-3', title: '' };
    const context = { selectedProjectName: 'project', selectedRun: { id: 'A' }, selectedTaskId: 'task-3',
      busyAction: '', executionAction: '', emptyManualTasksRef: { current: { 'project\0A\0task-3': blank } },
      emptyTaskValidationMessage: '',
      discardUntouchedTask: (...args) => calls.push(args), setSideInspectorOpen: () => {}, setCurrentTaskContentView: () => {},
      ...changes };
    appCallback('closeInspector', context)();
    assert.deepEqual(calls, Object.keys(changes).length ? [] : [['project', 'A', blank]]);
  }
});

test('discarding a blank task clears only its obsolete local validation message', () => {
  const localError = '제목 없는 작업 (task-3) · 제목 입력이 필요합니다. 초안은 유지됩니다.';
  for (const initialError of [localError, 'provider failure', 'another task validation']) {
    let error = initialError;
    const context = { selectedProjectName: 'project', selectedRun: { id: 'A' }, selectedTaskId: 'task-3',
      busyAction: '', executionAction: '', emptyManualTasksRef: { current: { 'project\0A\0task-3': { id:'task-3' } } },
      emptyTaskValidationMessage: localError, setError: update => { error = update(error); },
      discardUntouchedTask: () => {}, setSideInspectorOpen: () => {}, setCurrentTaskContentView: () => {} };
    appCallback('closeInspector', context)();
    assert.equal(error, initialError === localError ? '' : initialError);
  }
});

test('Task questions prepare a named composer draft while preserving other drafts and avoiding AI requests', () => {
  for (const status of ['failed', 'pending', 'running', 'stopped', 'completed']) {
    const calls = []; const drafts = { repair: 'keep repair', plan: 'keep plan', ai: 'keep composer' };
    const context = { selectedProjectName: 'Sample Project A', selectedRun: { id: 'group', tasks: [{ id: 'chosen', title: '선택한 작업', status }] }, taskDrafts: [],
      directionChangeDrafts: { read: () => ({ text: drafts.ai }), edit: (_project, _run, text) => { drafts.ai = text; } },
      setRepairTarget: (target) => calls.push(['target', target && { ...target }]), setSelectedTaskId: (id) => calls.push(['task', id]),
      setSideInspectorOpen: (value) => calls.push(['popup', value]), setHomeView: (value) => calls.push(['home', value]),
      setWorkbenchView: (value) => calls.push(['view', value]), window: { requestAnimationFrame: (fn) => fn() },
      setPlanningChatOpenRequest: (update) => calls.push(['chat', update(0)]),
      document: { getElementById: (id) => ({ focus: () => calls.push(['focus', id]) }) } };
    const navigate = appCallback('openTaskPlanning', context);
    navigate('missing'); assert.deepEqual(calls, [], 'unknown Tasks cannot change the planning target');
    navigate('chosen');
    assert.deepEqual(calls, [['target', { projectName: 'Sample Project A', runId: 'group', taskId: 'chosen' }],
      ['task', 'chosen'], ['popup', false], ['home', 'work'], ['chat', 1]]);
    assert.equal(drafts.repair, 'keep repair'); assert.equal(drafts.plan, 'keep plan');
    assert.ok(drafts.ai.startsWith('keep composer\n\n')); assert.match(drafts.ai, /선택한 작업/);
    assert.match(drafts.ai, status === 'failed' ? /문제와 해결 방법을 설명/ : /현재 상태를 설명/);
    const prepared = drafts.ai;
    const source = context.failedTaskQuestionDrafts_1.failedTaskQuestionKey('Sample Project A', context.selectedRun, context.selectedRun.tasks[0]);
    context.failedQuestionDrafts.current.cacheDiagnostic('Sample Project A', 'group', source, '원본 진단 자료');
    navigate('chosen');
    assert.equal(drafts.ai, prepared);
    assert.equal(context.failedQuestionDrafts.current.diagnostic('Sample Project A', 'group', source), '원본 진단 자료');
  }
});

test('new and edited draft cards open questions without saving, duplicate draft text or stale saved task targeting', () => {
  const calls = []; const draft = { text: '이미 작성 중인 질문' };
  const context = { selectedProjectName: 'project', selectedRun: { id: 'group', stage: 'planned', tasks: [{ id: 'edited', title: '저장 제목' }] },
    directionChangeDrafts: { read: () => draft, edit: (_project, _run, text) => { draft.text = text; } },
    taskDrafts: [{ id: 'new', title: '새 작업', status: 'pending' }, { id: 'edited', title: '현재 편집 제목', status: 'pending' }],
    setRepairTarget: (target) => calls.push(['target', { ...target }]), setSelectedTaskId: (id) => calls.push(['task', id]),
    setSideInspectorOpen: (open) => calls.push(['popup', open]), setHomeView: (view) => calls.push(['home', view]),
    setPlanningChatOpenRequest: (update) => calls.push(['chat', update(0)]),
    setPlanningMessage: () => assert.fail('question selection must preserve existing input'),
    window: { orchestrator: { request: () => assert.fail('question selection must not request AI or save') } } };
  const navigate = appCallback('openTaskPlanning', context);
  navigate('new'); navigate('new'); navigate('edited');
  assert.deepEqual(calls.filter((entry) => entry[0] === 'task').map((entry) => entry[1]), ['new', 'new', 'edited']);
  assert.deepEqual(calls.filter((entry) => entry[0] === 'target').map((entry) => entry[1].taskId), ['new', 'new', 'edited']);
  assert.ok(calls.filter((entry) => entry[0] === 'popup').every((entry) => entry[1] === false));
  assert.ok(draft.text.startsWith('이미 작성 중인 질문\n\n'));
  assert.equal(draft.text.split('현재 편집 제목').length - 1, 1);
  assert.doesNotMatch(draft.text, /저장 제목|새 작업/);
  assert.equal(context.TaskStatusOverview_1.selectedTaskForDetails(context.selectedRun, context.taskDrafts, 'edited').title, '현재 편집 제목');
});

function dialogTask(changes = {}) {
  return { ...workbenchRun().tasks[0], status: 'pending', readiness: 'ready', error: '', acceptance_criteria: ['intended behavior'],
    progress_phase: '', progress_detail: '', progress_updated_at: '', dependencies: [], verify_commands: [], ...changes };
}

test('Task modification disables card retry and help while detail navigation and other cards remain available', () => {
  const task = dialogTask({ id: 'editing', status: 'failed' });
  const other = dialogTask({ id: 'other', status: 'failed' });
  const calls = [];
  const render = (planningTaskIds, busy = false) => TaskFlow({ run: workbenchRun({ tasks: [task, other] }), selectedTaskId: other.id, busy,
    planningTaskIds, retryAllowed: true, onOpen: id => calls.push(['open', id]),
    onRetry: id => calls.push(['retry', id]), onPlanning: id => calls.push(['help', id]) });
  const tree = render([task.id]);
  const cards = elements(tree, n => n.type === 'li' && n.props.className === 'task-flow-card-group');
  assert.match(renderToStaticMarkup(cards[0]), /현재 Task 수정 중/);
  assert.equal(elements(cards[0], n => n.props.role === 'status').length, 1);
  assert.equal(task.status, 'failed');
  const buttons = elements(cards[0], n => n.type === 'button');
  const retry = buttons.find(n => n.props.className?.includes('task-flow-card__retry'));
  assert.equal(retry.props.children, '현재 Task 수정 중');
  assert.match(retry.props.title, /수정이 끝나면/);
  assert.ok(!buttons[0].props.disabled); buttons[0].props.onClick();
  for (const button of buttons.slice(1)) { assert.equal(button.props.disabled, true); button.props.onClick(); }
  assert.deepEqual(calls, [['open', 'editing']]);
  const otherButtons = elements(cards[1], n => n.type === 'button');
  assert.equal(otherButtons.find(n => n.props.className?.includes('task-flow-card__retry')).props.children, '현재 계획 재실행');
  assert.ok(otherButtons.every(b => !b.props.disabled));
  otherButtons.at(-1).props.onClick(); assert.deepEqual(calls.at(-1), ['help', 'other']);
  const finished = elements(render([]), n => n.type === 'li' && n.props.className === 'task-flow-card-group')[0];
  assert.doesNotMatch(renderToStaticMarkup(finished), /현재 Task 수정 중/);
  assert.ok(elements(finished, n => n.type === 'button').every(b => !b.props.disabled));
  assert.equal(elements(finished, n => n.props.className?.includes('task-flow-card__retry'))[0].props.children, '현재 계획 재실행');
  const busyRetry = elements(render([], true), n => n.props.className?.includes('task-flow-card__retry'))[0];
  assert.equal(busyRetry.props.disabled, true); assert.equal(busyRetry.props.children, '현재 계획 재실행');
});

test('Task planning requests keep their original scope and release only their own request', () => {
  const { taskPlanningInProgress } = require(join(output, 'renderer/src/planningPreviewRequest.js'));
  const context = { taskPlanningRequestsRef: { current: {} }, setTaskPlanningRequests: next => { context.requests = next; },
    crypto: require('node:crypto').webcrypto };
  const begin = appCallback('beginTaskPlanning', context);
  const finishFirst = begin({ projectName: 'project', runId: 'group', taskId: 'editing' });
  const finishSecond = begin({ projectName: 'project', runId: 'group', taskId: 'editing' });
  const finishOther = begin({ projectName: 'other', runId: 'group', taskId: 'editing' });
  assert.equal(taskPlanningInProgress(context.requests, 'project', 'group', 'other-task'), false);
  assert.equal(taskPlanningInProgress(context.requests, 'project', 'other-group', 'editing'), false);
  finishFirst(); finishFirst();
  assert.equal(taskPlanningInProgress(context.requests, 'project', 'group', 'editing'), true);
  finishSecond();
  assert.equal(taskPlanningInProgress(context.requests, 'project', 'group', 'editing'), false);
  assert.equal(taskPlanningInProgress(context.requests, 'other', 'group', 'editing'), true);
  const finishGroup = begin({ projectName: 'project', runId: 'group' });
  assert.equal(taskPlanningInProgress(context.requests, 'project', 'group', 'any-task'), true);
  finishGroup(); finishOther(); assert.equal(Object.keys(context.requests).length, 0);
});

test('Task dialog also disables help and execution while the targeted plan is being modified', () => {
  for (const status of ['failed', 'pending']) {
    const calls = [];
    const tree = TaskStatusOverview({ task: dialogTask({ status }), run: workbenchRun({
      execution_control: { situation: 'ready', action: 'execute' }, plan_revision: 1, plan_approved_revision: 1 }),
      planning: true, busy: false, planDirty: false, onPlanning: () => calls.push('help'), onRun: () => calls.push('run'),
      onResult: () => {}, onStop: () => {}, onRefresh: () => {}, onOpenTask: () => {} });
    assert.match(renderToStaticMarkup(tree), /현재 Task 수정 중/);
    for (const button of elements(tree, n => n.type === 'button')) { assert.equal(button.props.disabled, true); button.props.onClick(); }
    assert.deepEqual(calls, []);
  }
});
function taskOverview(task, control, changes = {}) {
  const calls = [];
  const tree = TaskStatusOverview({ task, run: workbenchRun({ stage: 'executing', execution_control: control, tasks: [task], ...changes.run }),
    planDirty: Boolean(changes.planDirty), busy: Boolean(changes.busy), requestError: changes.requestError,
    onPlanning: () => calls.push('planning'), onResult: () => calls.push('result'), onStop: () => calls.push('stop'),
    onRun: (method) => calls.push(method), onRefresh: () => calls.push('refresh'), onOpenTask: (id) => calls.push(id) });
  return { tree, calls, markup: renderToStaticMarkup(tree), buttons: elements(tree, (item) => item.type === 'button') };
}

test('Task dialog guides each state with one clear next action without running anything on render', () => {
  const cases = [
    [dialogTask({ status: 'failed', failed_action: 'verify', error: 'raw technical failure' }), { situation: 'resumable', action: 'resume' }, 'failed', '동작 확인을 통과하지 못했습니다', 'planning'],
    [dialogTask({ status: 'failed', failed_action: 'review' }), { situation: 'resumable', action: 'resume' }, 'failed', '내용 점검을 통과하지 못했습니다', 'planning'],
    [dialogTask({ status: 'completed' }), { situation: 'running', action: 'none', stop_phase: 'stopped' }, 'completed', '이 작업을 마쳤습니다', 'result'],
    [dialogTask({ status: 'merged' }), { situation: 'tasks_complete', action: 'none' }, 'completed', '이 작업을 마쳤습니다', 'result'],
    [dialogTask({ status: 'waiting' }), { situation: 'resumable', action: 'resume' }, 'waiting', '작업 결과를 확인해 주세요', 'result'],
    [dialogTask({ status: 'stopped' }), { situation: 'resumable', action: 'resume' }, 'stopped', '이어서 진행할 준비가 필요합니다', 'runs.resume'],
    [dialogTask({ status: 'running' }), { situation: 'resumable', action: 'resume' }, 'stopped', '이어서 진행할 준비가 필요합니다', 'runs.resume'],
    [dialogTask({ status: 'running' }), { situation: 'status_unknown', action: 'none' }, 'unknown', '현재 실행 여부를 확인해야 합니다', 'refresh'],
    [dialogTask(), { situation: 'ready', action: 'execute' }, 'ready', '작업을 시작할 수 있습니다', 'runs.execute'],
  ];
  for (const [task, control, state, title, action] of cases) {
    const view = taskOverview(task, control);
    assert.equal(view.tree.props['data-state'], state);
    assert.ok(view.markup.includes(state === 'completed' ? '작업 완료' : title));
    assert.deepEqual(view.calls, []);
    assert.equal(view.buttons.length, action === 'planning' ? 1 : 2);
    assert.equal(view.buttons.filter((button) => button.props.children === (state === 'failed' ? 'AI 도움 요청' : 'AI 질문')).length, 1);
    view.buttons[0].props.onClick(); assert.deepEqual(view.calls, [action]);
    if (state === 'failed' && task.error) assert.ok(view.markup.includes(task.error));
    else assert.doesNotMatch(view.markup, /raw technical failure|exit code|attempt_id/);
    if (state === 'completed') assert.doesNotMatch(view.markup, /<h3>|이 작업을 마쳤습니다/);
  }
});

test('failure dialog shows the exact current error and help without old diagnostic noise', () => {
  const raw = 'current failure <unsafe>\n' + 'long-error-path/'.repeat(150);
  const task = dialogTask({status: 'failed', error: '', failed_action: 'verify', last_attempt_id: 'current',
    action_results: [{status: 'failed', action: 'verify', attempt_id: 'old', error: 'previous failure', worker_response: 'old success text'},
      {status: 'failed', action: 'verify', attempt_id: 'current', error: raw, worker_response: 'current response'}]});
  const view = taskOverview(task, {situation: 'resumable', action: 'resume'}, {busy: true});
  const pres = elements(view.tree, n => n.type === 'pre');
  assert.equal(pres.length, 1); assert.equal(pres[0].props.children, raw);
  assert.match(view.markup, /동작 확인을 통과하지 못했습니다/);
  assert.match(view.markup, /오류 원문|current failure|long-error-path/);
  assert.doesNotMatch(view.markup, /previous failure|old success text/);
  assert.equal(view.buttons[0].props.children, 'AI 도움 요청'); assert.ok(!view.buttons[0].props.disabled);
  assert.deepEqual(view.calls, []); view.buttons[0].props.onClick(); assert.deepEqual(view.calls, ['planning']);
  const record = TaskTechnicalRecord({task});
  assert.ok(elements(record, n => n.type === 'pre').some(n => n.props.children === raw));
  assert.match(renderToStaticMarkup(record), /&lt;unsafe&gt;/);
  assert.doesNotMatch(renderToStaticMarkup(record), /previous failure|old success text/);
  const stale = taskOverview({...task, last_attempt_id: 'new', action_results: task.action_results.slice(0,1)}, undefined);
  assert.match(stale.markup, /원인을 특정하지 못했습니다/); assert.doesNotMatch(stale.markup, /previous failure/);
});

test('active retry hides previous failure and stale command details while showing only current observed activity', () => {
  const task = dialogTask({ status: 'running', active_action: 'execute', last_attempt_id: 'new',
    last_attempt_started_at: new Date(Date.now() - 20000).toISOString(), progress_phase: 'reading_documents',
    progress_detail: 'Get-Content secret-source.cs exit code 0', progress_updated_at: new Date(Date.now() - 10000).toISOString(),
    action_results: [{ action: 'verify', status: 'failed', attempt_id: 'old', error: 'old failure', worker_response: 'old response' },
      { action: 'execute', status: 'running', attempt_id: 'new', started_at: new Date(Date.now() - 20000).toISOString() }] });
  const control = { situation: 'running', action: 'none', can_stop: true, execution_id: 'execution', active_task_id: task.id };
  const view = taskOverview(task, control, { busy: true });
  assert.equal(view.tree.props['data-state'], 'running');
  assert.match(view.markup, /요청한 기능을 만들고 있습니다|기존 코드와 설명을 살펴보고 있습니다/);
  assert.match(view.markup, /마지막 활동 변화/); assert.doesNotMatch(view.markup, /old failure|old response|Get-Content|secret-source|검증.*실패/);
  assert.equal(view.buttons[0].props.children, '작업 중지'); assert.equal(view.buttons[0].props.disabled, false);
  view.buttons[0].props.onClick(); assert.deepEqual(view.calls, ['stop']);
  const stale = taskOverview({ ...task, progress_updated_at: '2020-01-01T00:00:00Z' }, control);
  assert.match(stale.markup, /활동 보고 대기/); assert.doesNotMatch(stale.markup, /마지막 활동 변화/);
});

test('stop, resume and start stay guarded by backend permissions, current stop phase, busy work and plan review', () => {
  const running = dialogTask({ status: 'running' });
  for (const control of [{ situation: 'running', can_stop: false }, { situation: 'running', can_stop: true, execution_id: '' }]) {
    assert.deepEqual(taskOverview(running, control).buttons.map((button) => button.props.children), ['AI 질문']);
  }
  const stopping = taskOverview(running, { situation: 'running', can_stop: true, execution_id: 'x', stop_phase: 'stopping', active_task_id: running.id });
  assert.equal(stopping.tree.props['data-state'], 'stopping'); assert.deepEqual(stopping.buttons.map((button) => button.props.children), ['AI 질문']);
  assert.match(stopping.markup, /중지 요청됨.*멈추는지 확인 중/);
  assert.equal(taskOverview(running, { situation: 'resumable', action: 'none' }).buttons[0].props.children, '상태 다시 확인');
  assert.equal(taskOverview(running, { situation: 'resumable', action: 'resume' }, { busy: true }).buttons[0].props.disabled, true);
  assert.equal(taskOverview(running, { situation: 'resumable', action: 'resume' }, { planDirty: true }).buttons[0].props.disabled, true);
  assert.equal(taskOverview(dialogTask(), { situation: 'ready', action: 'execute' }, { busy: true }).buttons[0].props.disabled, true);
  const planned = taskOverview(dialogTask(), { situation: 'ready', action: 'execute' }, { run: { plan_approved_revision: 0 } });
  assert.equal(planned.tree.props['data-state'], 'planned'); planned.buttons[0].props.onClick(); assert.deepEqual(planned.calls, ['planning']);
  assert.equal(taskOverview(dialogTask(), undefined).tree.props['data-state'], 'unknown');
});

test('dependency waiting exposes named prerequisite navigation without granting execution or silently losing missing tasks', () => {
  const task = dialogTask({ blocked_by: ['first', 'missing'], readiness: 'blocked' });
  const view = taskOverview(task, { situation: 'resumable', action: 'resume' }, { run: { tasks: [task, dialogTask({ id: 'first', title: '먼저 할 작업' })] } });
  assert.equal(view.tree.props['data-state'], 'waiting'); assert.match(view.markup, /먼저 할 작업 · 상태 보기/);
  assert.match(view.markup, /missing · 작업 정보를 찾지 못했습니다/);
  assert.equal(view.buttons.length, 2); view.buttons[0].props.onClick(); assert.deepEqual(view.calls, ['first']);
  assert.deepEqual(taskOverview(dialogTask(), { situation: 'running', action: 'none' }).buttons.map((button) => button.props.children), ['AI 질문']);
  assert.equal(taskDialogPresentation(dialogTask({ status: 'cancelled' }), workbenchRun(), false).action, 'none');
});

test('a request error stays distinct from task status with its exact cause in a collapsed disclosure', () => {
  const error = "Error invoking remote method 'orchestrator:request': original failure";
  const view = taskOverview(dialogTask({ status: 'running', active_action: 'execute' }), { situation: 'running' }, { requestError: error });
  assert.equal(view.tree.props['data-state'], 'running');
  const notice = elements(view.tree, (item) => item.props.role === 'alert')[0];
  assert.match(renderToStaticMarkup(elements(notice, (item) => item.type === 'p')[0]), /마지막 요청을 처리하지 못했습니다/);
  const disclosure = elements(notice, (item) => item.type === 'details')[0];
  assert.ok(!disclosure.props.open);
  assert.equal(elements(disclosure, (item) => item.type === 'pre')[0].props.children, error);
  const record = TaskTechnicalRecord({task: dialogTask(), requestError:error});
  assert.equal(elements(record, (item) => item.type === 'pre')[0].props.children, error);
});

test('log and event popup actions keep the list visible and focus the requested records at every layout', () => {
  for (const workbenchLayout of ['wide', 'medium', 'compact', 'single']) {
    for (const [callback, tab] of [['openTaskLog', 'log'], ['openTaskEvents', 'events']]) {
      const selection = []; const tabs = []; const surfaces = []; const views = []; const focus = [];
      const context = { setSelectedTaskId: (id) => selection.push(id), setInspectorTab: (value) => tabs.push(value),
        setSideInspectorOpen: (value) => surfaces.push(value), setCurrentTaskContentView: (value) => views.push(value),
        workbenchLayout, selectedRun: undefined, window: { requestAnimationFrame: (fn) => fn() },
        document: { getElementById: (id) => { focus.push(id); return {
          focus: (options) => { assert.equal(options.preventScroll, true); focus.push('focus'); },
          scrollIntoView: (options) => { assert.equal(options.block, 'nearest'); focus.push('scroll'); },
        }; } } };
      appCallback(callback, context)('chosen');
      assert.deepEqual(selection, ['chosen']); assert.deepEqual(tabs, [tab]);
      assert.deepEqual(surfaces, [true]); assert.deepEqual(views, ['list']);
      assert.deepEqual(focus, [`side-inspector-tab-${tab}`, 'focus', 'scroll']);
    }
  }
});

test('explicit failed-task log requests open the records tab instead of the removed status popup', () => {
  const calls = [];
  const context = {selectedRun: {tasks: [{id: 'failed', status: 'failed'}]}, workbenchLayout: 'wide',
    setSelectedTaskId: id => calls.push(['selected', id]), setInspectorTab: tab => calls.push(['tab', tab]),
    setSideInspectorOpen: value => calls.push(['open', value]), setCurrentTaskContentView: value => calls.push(['view', value]),
    window: {requestAnimationFrame: callback => callback(), orchestrator: {request: () => assert.fail('opening must not fetch logs or execute')}},
    document: {getElementById: id => {calls.push(['focusTarget', id]); return {focus: options => calls.push(['focus', {...options}]),
      scrollIntoView: options => calls.push(['scroll', {...options}])};}}};
  appCallback('openTaskLog', context)('failed');
  assert.deepEqual(calls, [['selected','failed'], ['tab','log'], ['open',true], ['view','list'],
    ['focusTarget','side-inspector-tab-log'], ['focus',{preventScroll:true}], ['scroll',{block:'nearest'}]]);
});


test('project removal guards only the target project requests, shared restart and duplicate removal', () => {
  const reason = appComponents.projectRemovalReason;
  const requests = {[JSON.stringify(['running-other', 'run'])]: {id: 1, method: 'runs.execute'}};
  assert.equal(reason('idle', requests, '', '', ''), '');
  assert.equal(reason('idle', requests, 'runs.sendPlanningMessage', 'running-other', ''), '');
  assert.match(reason('running-other', requests, '', '', ''), /이 프로젝트의 실행 요청/);
  assert.match(reason('idle', requests, 'runs.sendPlanningMessage', 'idle', ''), /이 프로젝트의 요청/);
  assert.match(reason('idle', requests, '', '', 'another'), /등록 해제 결과/);
  assert.match(reason('idle', requests, 'system.restartBackend', 'other', ''), /실행 엔진 재시작/);
  assert.match(reason('', requests, '', '', ''), /먼저 선택/);
  assert.equal(reason('running', requests, '', '', ''), '', 'similar project prefixes are distinct');
});

function removalHarness(outcome) {
  const calls = [], states = [], notices = [], errors = [];
  const requests = {[JSON.stringify(['other', 'run'])]: {id: 1, method: 'runs.execute'}};
  let settle;
  const context = {react_1: {useCallback: callback => callback}, selectedProjectName: 'idle', executionRequests: requests,
    busyAction: 'runs.sendPlanningMessage', busyProjectRef: {current: 'other'}, removingProjectRef: {current: ''},
    projectRemovalReason: appComponents.projectRemovalReason,
    setRemovingProjectName: value => states.push(value),
    loadProjects: async () => calls.push('refresh registry'), setNotice: value => notices.push(value),
    setError: value => errors.push(value), errorMessage: error => error.message,
    window: {orchestrator: {approve: (method, params) => {calls.push([method, params]); return new Promise((resolve, reject) => {settle = () => outcome instanceof Error ? reject(outcome) : resolve(outcome);});}}}};
  const source = readFileSync(appFile, 'utf8');
  const callback = source.match(/^    const removeProject = [\s\S]*?(?=^    const choosePath =)/m);
  assert.ok(callback);
  runInNewContext(`${callback[0]}\nthis.remove = removeProject;`, context);
  return {context, calls, states, notices, errors, settle: () => settle()};
}

test('unregister confirmation captures its target and leaves other project execution requests intact', async () => {
  const fixture = removalHarness({name: 'idle'});
  const before = JSON.stringify(fixture.context.executionRequests);
  const request = fixture.context.remove();
  fixture.context.selectedProjectName = 'other';
  await fixture.context.remove();
  assert.equal(fixture.calls.length, 1, 'duplicate confirmation cannot start after selection changes');
  assert.equal(fixture.calls[0][0], 'projects.remove'); assert.equal(fixture.calls[0][1].projectName, 'idle');
  fixture.settle(); await request;
  assert.equal(JSON.stringify(fixture.context.executionRequests), before);
  assert.deepEqual(fixture.states, ['idle', '']); assert.match(fixture.notices[0], /idle 프로젝트/);
  assert.deepEqual(fixture.errors, []); assert.equal(fixture.context.removingProjectRef.current, '');
});

test('unregister cancellation and failure preserve registry and execution state and release the request guard', async () => {
  for (const outcome of [null, new Error('등록 해제 실패 원문')]) {
    const fixture = removalHarness(outcome); const before = JSON.stringify(fixture.context.executionRequests);
    const request = fixture.context.remove(); fixture.settle(); await request;
    assert.equal(fixture.calls.length, 1, 'cancellation and failure do not refresh a changed registry');
    assert.equal(JSON.stringify(fixture.context.executionRequests), before); assert.deepEqual(fixture.notices, []);
    assert.deepEqual(fixture.states, ['idle', '']); assert.equal(fixture.context.removingProjectRef.current, '');
    assert.deepEqual(fixture.errors, outcome ? ['등록 해제 실패 원문'] : []);
  }
});


test('Planning AI boundary supports clamped drag and keyboard sizing without executing actions', () => {
  const resizer = {};
  runInNewContext(`${readFileSync(appFile, 'utf8')}\nexports.PaneResizer = PaneResizer;`, {exports: resizer, require: id => id === 'react' ? {...appRequire(id), useRef: value => ({current: value})} : appRequire(id)});
  const values = []; const tree = resizer.PaneResizer({label: 'Planning AI 너비', variant: 'planning', direction: -1,
    value: 400, min: 320, max: 500, defaultValue: 400, onChange: value => values.push(value)});
  assert.equal(tree.props.role, 'separator'); assert.equal(tree.props['aria-orientation'], 'vertical');
  assert.equal(tree.props.tabIndex, 0); assert.equal(tree.props['aria-valuenow'], 400); assert.deepEqual(values, []);
  for (const key of ['ArrowLeft','ArrowRight','Home','End']) tree.props.onKeyDown({key, preventDefault() {}});
  assert.deepEqual(values, [416,384,320,500]);
  const target = {setPointerCapture() {}, hasPointerCapture: () => true, releasePointerCapture() {}};
  tree.props.onPointerDown({clientX: 800, pointerId: 1, currentTarget: target});
  tree.props.onPointerMove({clientX: 100, pointerId: 1, currentTarget: target});
  tree.props.onPointerUp({pointerId: 1, currentTarget: target});
  assert.equal(values.at(-1), 500); tree.props.onDoubleClick(); assert.equal(values.at(-1), 400);
});
