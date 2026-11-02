const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');
const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'preload-rpc-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output, 'desktop/main/preload.ts', 'desktop/renderer/src/recoveryLock.ts',
    'desktop/renderer/src/runDeletion.ts', 'desktop/renderer/src/chatTaskRecovery.ts'],
    { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

function bridge(respond = async () => ({ id: 'run' })) {
  let api;
  const calls = [];
  const listeners = new Map();
  runInNewContext(readFileSync(join(output, 'main/preload.js'), 'utf8'), {
    exports: {},
    require(name) {
      assert.equal(name, 'electron');
      return {
        contextBridge: { exposeInMainWorld(name, value) { assert.equal(name, 'orchestrator'); api = value; } },
        ipcRenderer: {
          invoke(...args) { calls.push(args); return respond(...args); },
          on(channel, listener) { listeners.set(channel, listener); },
          removeListener(channel, listener) { if (listeners.get(channel) === listener) listeners.delete(channel); },
        },
      };
    },
  });
  return { api, calls, listeners };
}

test('Codex API key login uses a fixed channel and explicit arguments', async () => {
  const { api, calls } = bridge();
  await api.connectCodexApiKey('sk-fixture-only', 'key-request');
  assert.deepEqual(calls, [['orchestrator:codex-auth-api-key', 'sk-fixture-only', 'key-request']]);
});

test('message reservation uses fixed channels and forwards only explicit API arguments', async () => {
  const { api, calls } = bridge();
  const input = { id: 'message', projectName: 'A', runId: 'one', text: '다음 질문', profile: {} };
  const change = { id: 'message', projectName: 'A', runId: 'one', revision: 1, action: 'cancel' };
  await api.queuePlanningMessage(input); await api.changeQueuedPlanningMessage(change);
  assert.deepEqual(calls, [['orchestrator:queue-planning-message', input], ['orchestrator:change-queued-planning-message', change]]);
});

test('notification IPC uses fixed channels and subscriptions can be removed', async () => {
  const { api, calls, listeners } = bridge();
  const changed = [];
  const opened = [];
  const removeChanged = api.onNotificationsChanged((snapshot) => changed.push(snapshot));
  const removeOpened = api.onNotificationOpen((notification) => opened.push(notification));
  listeners.get('orchestrator:notifications-changed')({}, { unread_count: 2 });
  listeners.get('orchestrator:notification-open')({}, { event_id: 'event' });
  assert.equal(changed[0].unread_count, 2);
  assert.equal(opened[0].event_id, 'event');
  await api.listNotifications();
  await api.listNotifications('["notifications.list","A","repo"]');
  await api.markNotificationRead('event');
  await api.markAllNotificationsRead();
  await api.dismissNotification('event');
  await api.dismissNotifications('read');
  await api.updateNotificationSettings({ enabled: true, completion: false, failure: true, attention_required: true });
  assert.deepEqual(calls, [
    ['orchestrator:notifications-list'],
    ['orchestrator:notifications-list', '["notifications.list","A","repo"]'],
    ['orchestrator:notifications-mark-read', 'event'],
    ['orchestrator:notifications-mark-all-read'],
    ['orchestrator:notifications-dismiss', 'event'],
    ['orchestrator:notifications-dismiss-many', 'read'],
    ['orchestrator:notifications-settings', { enabled: true, completion: false, failure: true, attention_required: true }],
  ]);
  removeChanged();
  removeOpened();
  assert.equal(listeners.size, 0);
});

test('Codex authentication uses fixed IPC channels and removable menu subscription', async () => {
  const { api, calls, listeners } = bridge();
  let opened = 0;
  const removeOpen = api.onOpenCodexAuth(() => { opened += 1; });
  listeners.get('orchestrator:open-codex-auth')();
  assert.equal(opened, 1);
  await api.codexAuthStatus();
  await api.startCodexAuth('browser', 'request-1');
  await api.getCodexAuth('attempt-1');
  await api.cancelCodexAuth('attempt-1');
  await api.reopenCodexAuth('attempt-1');
  await api.copyCodexDeviceCode('attempt-1');
  assert.deepEqual(calls, [
    ['orchestrator:codex-auth-status'],
    ['orchestrator:codex-auth-start', 'browser', 'request-1'],
    ['orchestrator:codex-auth-get', 'attempt-1'],
    ['orchestrator:codex-auth-cancel', 'attempt-1'],
    ['orchestrator:codex-auth-reopen', 'attempt-1'],
    ['orchestrator:codex-auth-copy-code', 'attempt-1'],
  ]);
  removeOpen();
  assert.equal(listeners.has('orchestrator:open-codex-auth'), false);
});

test('attention inbox reaches the read-only request channel without a selected project', async () => {
  const { api, calls } = bridge();
  await api.request('runs.attentionItems');
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [['orchestrator:request', 'runs.attentionItems', {}]]);
});

test('recovery preview reaches request IPC with its selected group', async () => {
  const { api, calls } = bridge();
  const params = { projectName: 'project', runId: 'failed' };
  await api.request('runs.recoveryPlan', params);
  assert.deepEqual(calls, [['orchestrator:request', 'runs.recoveryPlan', params]]);
});

test('recovery application requires the approval channel', async () => {
  const { api, calls } = bridge();
  const params = { projectName: 'project', runId: 'failed', fingerprint: 'reviewed', sourceIds: ['source'] };
  await assert.rejects(api.request('runs.applyRecovery', params), /Unsupported RPC method/);
  assert.equal(calls.length, 0);
  await api.approve('runs.applyRecovery', params);
  assert.deepEqual(calls, [['orchestrator:approved-request', 'runs.applyRecovery', params]]);
});

test('unknown requests remain blocked before IPC', async () => {
  const { api, calls } = bridge();
  await assert.rejects(api.request('runs.unknown'), /Unsupported RPC method/);
  assert.equal(calls.length, 0);
});


const { describeRecoveryError } = require(join(output, 'renderer/src/recoveryLock.js'));
const { runDeletionBlockMessage, runDeletionMissingMessage, runDeletionNeedsBackendRestart, runMissingMessage } = require(join(output, 'renderer/src/runDeletion.js'));

test('run deletion blocks active work before approval', () => {
  assert.match(runDeletionBlockMessage({ state: 'active' }), /작업이 실행 중/);
  for (const state of ['unlocked', 'stale', 'unverifiable', 'malformed']) {
    assert.equal(runDeletionBlockMessage({ state }), '');
  }
});

test('AI revision proposal uses request IPC without approval', async () => {
  const { api, calls } = bridge();
  const params = { projectName: 'project', runId: 'result', proposalId: 'proposal', text: '문구 수정' };
  await api.request('runs.proposeResultRevision', params);
  assert.deepEqual(calls, [['orchestrator:request', 'runs.proposeResultRevision', params]]);
});

test('cross-project active group lookup reaches request IPC without a selected project', async () => {
  const { api, calls } = bridge();
  await api.request('runs.activeGroups');
  assert.deepEqual(calls[0].slice(0, 2), ['orchestrator:request', 'runs.activeGroups']);
  assert.equal(JSON.stringify(calls[0][2]), '{}');
});

test('direction change request reaches request IPC with a stable request ID', async () => {
  const { api, calls } = bridge();
  const params = { projectName: 'project', runId: 'executing', requestId: 'direction-1', text: '다음 작업을 먼저' };
  await api.request('runs.requestDirectionChange', params);
  assert.deepEqual(calls, [['orchestrator:request', 'runs.requestDirectionChange', params]]);
});

test('Windows worktree sharing failure offers backend restart without masking other errors', () => {
  assert.equal(runDeletionNeedsBackendRestart(new Error('작업공간이 다른 프로그램에서 사용 중입니다: C:\\work [WinError 32]')), true);
  assert.equal(runDeletionNeedsBackendRestart(new Error('worktree has uncommitted changes')), false);
});

test('run archive preview is read-only and archive cleanup requires approval', async () => {
  const { api, calls } = bridge();
  const preview = { projectName: 'project', runId: 'complete' };
  const archive = { ...preview, expectedRevision: 'revision', fingerprint: 'fingerprint', requestId: 'request-1' };
  await api.request('runs.archivePlan', preview);
  await assert.rejects(api.request('runs.archive', archive), /Unsupported RPC method/);
  await api.approve('runs.archive', archive);
  await api.approve('runs.retryArchiveCleanup', { ...preview, fingerprint: 'fingerprint', requestId: 'request-2' });
  await api.openArchiveFolder('project', 'complete');
  assert.deepEqual(calls.map((call) => call.slice(0, 2)), [
    ['orchestrator:request', 'runs.archivePlan'],
    ['orchestrator:approved-request', 'runs.archive'],
    ['orchestrator:approved-request', 'runs.retryArchiveCleanup'],
    ['orchestrator:open-archive-folder', 'project'],
  ]);
  assert.equal(calls.at(-1)[2], 'complete');
});

test('Planning conversation apply reaches request IPC with fixed revisions', async () => {
  const { api, calls } = bridge();
  const params = {
    projectName: 'project', runId: 'run', requestId: 'apply-1',
    expectedRevision: 3, conversationRevision: 7,
  };
  await api.request('runs.applyPlanningConversation', params);
  assert.deepEqual(calls, [['orchestrator:request', 'runs.applyPlanningConversation', params]]);
});

test('Planning preview and confirmed application use only allowlisted request IPC', async () => {
  const { api, calls } = bridge();
  await api.request('runs.getPlanningPreview', { projectName: 'project', runId: 'run' });
  await api.request('runs.previewPlanningApply', { projectName: 'project', runId: 'run', requestId: 'preview-1' });
  await api.request('runs.applyPlanningPreview', {
    projectName: 'project', runId: 'run', previewId: 'preview-1',
    fingerprint: 'before', candidateDigest: 'candidate',
  });
  assert.deepEqual(calls.map((call) => call[1]), [
    'runs.getPlanningPreview', 'runs.previewPlanningApply', 'runs.applyPlanningPreview',
  ]);
  assert.ok(calls.every((call) => call[0] === 'orchestrator:request'));
});

test('technology stack confirmation reaches request IPC with its revision', async () => {
  const { api, calls } = bridge();
  const params = {
    projectName: 'project', runId: 'run', optionId: 'electron-typescript', expectedRevision: 2,
  };
  await api.request('runs.confirmTechStack', params);
  assert.deepEqual(calls, [['orchestrator:request', 'runs.confirmTechStack', params]]);
});

test('bootstrap instruction choice reaches request IPC with revision and digest', async () => {
  const { api, calls } = bridge();
  const params = {
    projectName: 'project', runId: 'run', create: false, expectedRevision: 2, expectedDigest: 'digest-2',
  };
  await api.request('runs.configureBootstrapInstructions', params);
  assert.deepEqual(calls, [['orchestrator:request', 'runs.configureBootstrapInstructions', params]]);
});

test('execution stop and verification repair use the request channel', async () => {
  const { api, calls } = bridge();
  const stop = { projectName: 'project', runId: 'run', requestId: 'request', executionId: 'execution', scope: 'task' };
  await api.request('runs.requestStop', stop);
  await api.request('runs.verifyAndRepair', { projectName: 'project', runId: 'run', requestId: 'repair' });
  assert.deepEqual(calls.map((call) => call.slice(0, 2)), [
    ['orchestrator:request', 'runs.requestStop'],
    ['orchestrator:request', 'runs.verifyAndRepair'],
  ]);
});

test('recovery operation status reads use the non-approved request channel', async () => {
  const { api, calls } = bridge();
  const params = { projectName: 'project', runId: 'failed', requestId: 'request' };
  await api.request('operations.get', params);
  await api.request('operations.latest', { projectName: 'project', runId: 'failed', kind: 'recovery_preview' });
  assert.deepEqual(calls.map((call) => call.slice(0, 2)), [
    ['orchestrator:request', 'operations.get'],
    ['orchestrator:request', 'operations.latest'],
  ]);
});

test('conflict candidate uses request IPC and application uses approval IPC', async () => {
  const { api, calls } = bridge();
  const params = { projectName: 'project', runId: 'failed', conflictId: 'conflict', fingerprint: 'fingerprint', requestId: 'request' };
  await api.request('runs.integrationConflict', params);
  await api.request('runs.prepareConflictResolution', params);
  await assert.rejects(api.request('runs.applyConflictResolution', params), /Unsupported RPC method/);
  await api.approve('runs.applyConflictResolution', params);
  assert.deepEqual(calls.map((call) => call.slice(0, 2)), [
    ['orchestrator:request', 'runs.integrationConflict'],
    ['orchestrator:request', 'runs.prepareConflictResolution'],
    ['orchestrator:approved-request', 'runs.applyConflictResolution'],
  ]);
});

test('project workspace location reaches read-only request IPC', async () => {
  const { api, calls } = bridge();
  const params = { projectName: 'project' };
  await api.request('projects.workspaceLocation', params);
  assert.deepEqual(calls, [['orchestrator:request', 'projects.workspaceLocation', params]]);
});

test('project deployment capability reaches read-only request IPC', async () => {
  const { api, calls } = bridge();
  const params = { projectName: 'project' };
  await api.request('projects.capabilities', params);
  assert.deepEqual(calls, [['orchestrator:request', 'projects.capabilities', params]]);
});

test('code style profile and preview are read-only while save requires approval IPC', async () => {
  const { api, calls } = bridge();
  const project = { projectName: 'project' };
  const preference = { mode: 'repository_only', fallback_by_language: {}, custom_instruction_paths: [] };
  await api.request('projects.codeStyleProfile', project);
  await api.request('projects.previewCodeStylePreference', { ...project, preference });
  await assert.rejects(api.request('projects.updateCodeStylePreference', { ...project, preference, expectedRevision: 0 }), /Unsupported RPC method/);
  await api.approve('projects.updateCodeStylePreference', { ...project, preference, expectedRevision: 0 });
  assert.deepEqual(calls.map((call) => call.slice(0, 2)), [
    ['orchestrator:request', 'projects.codeStyleProfile'],
    ['orchestrator:request', 'projects.previewCodeStylePreference'],
    ['orchestrator:approved-request', 'projects.updateCodeStylePreference'],
  ]);
});

test('repository maturity inspection reaches read-only request IPC', async () => {
  const { api, calls } = bridge();
  const params = { projectName: 'project' };
  await api.request('planning.inspectRepositoryMaturity', params);
  assert.deepEqual(calls, [['orchestrator:request', 'planning.inspectRepositoryMaturity', params]]);
});

test('bootstrap preview reaches read-only request IPC', async () => {
  const { api, calls } = bridge();
  const params = { projectName: 'project', runId: 'run' };
  await api.request('planning.previewBootstrap', params);
  assert.deepEqual(calls, [['orchestrator:request', 'planning.previewBootstrap', params]]);
});

test('feature plan retry reaches request IPC', async () => {
  const { api, calls } = bridge();
  const params = { projectName: 'project', runId: 'run' };
  await api.request('planning.generateFeaturePlan', params);
  assert.deepEqual(calls, [['orchestrator:request', 'planning.generateFeaturePlan', params]]);
});

test('Main change previews use request IPC and mutations require approval IPC', async () => {
  const { api, calls } = bridge();
  const preview = { projectName: 'project' };
  const mutation = {
    projectName: 'project', snapshotId: 'snapshot',
    selections: [{ path: 'src/app.ts', mode: 'whole' }], message: 'selected change',
  };
  await api.request('projects.mainChanges', preview);
  await api.request('projects.mainChangeDiff', { ...preview, snapshotId: 'snapshot', path: 'src/app.ts', mode: 'whole' });
  await api.request('projects.refreshMainRemote', preview);
  await assert.rejects(api.request('projects.commitMainChanges', mutation), /Unsupported RPC method/);
  await api.approve('projects.commitMainChanges', mutation);
  await api.approve('projects.commitAndPushMainChanges', mutation);
  await api.approve('projects.pushMainCommits', { ...preview, snapshotId: 'snapshot' });
  assert.deepEqual(calls.map((call) => call.slice(0, 2)), [
    ['orchestrator:request', 'projects.mainChanges'],
    ['orchestrator:request', 'projects.mainChangeDiff'],
    ['orchestrator:request', 'projects.refreshMainRemote'],
    ['orchestrator:approved-request', 'projects.commitMainChanges'],
    ['orchestrator:approved-request', 'projects.commitAndPushMainChanges'],
    ['orchestrator:approved-request', 'projects.pushMainCommits'],
  ]);
});

test('Git project preparation separates inspection from approved mutations', async () => {
  const { api, calls } = bridge();
  const repo = 'C:/project';
  await api.request('projects.inspectGitReadiness', { repo });
  await api.request('projects.previewGitInitialization', { repo });
  await api.request('projects.previewInitialCommit', { repo });
  await assert.rejects(api.request('projects.initializeGit', { repo, expectedKind: 'not_initialized' }), /Unsupported RPC method/);
  await assert.rejects(api.request('projects.createInitialCommit', { repo }), /Unsupported RPC method/);
  await api.approve('projects.initializeGit', { repo, expectedKind: 'not_initialized' });
  await api.approve('projects.createInitialCommit', {
    repo, snapshotId: 'snapshot', selectedPaths: ['README.md'], message: 'Initial commit',
  });
  assert.deepEqual(calls.map((call) => call.slice(0, 2)), [
    ['orchestrator:request', 'projects.inspectGitReadiness'],
    ['orchestrator:request', 'projects.previewGitInitialization'],
    ['orchestrator:request', 'projects.previewInitialCommit'],
    ['orchestrator:approved-request', 'projects.initializeGit'],
    ['orchestrator:approved-request', 'projects.createInitialCommit'],
  ]);
});

test('run deletion turns a missing backend run into refresh guidance', () => {
  assert.match(runDeletionMissingMessage(new Error('unknown run: run-1')), /목록을 새로고침/);
  assert.equal(runDeletionMissingMessage(new Error('run is locked')), '');
  assert.match(runMissingMessage(new Error("Error invoking remote method 'orchestrator:request': unknown run: run-1")), /목록을 새로고침/);
  assert.equal(runMissingMessage(new Error('network unavailable')), '');
});

test('recovery offers approved lock cleanup only for a confirmed stale lock', async () => {
  const cause = new Error('run failed is already locked (operation=recovery-preview)');
  for (const state of ['stale', 'active', 'unlocked', 'unverifiable', 'malformed']) {
    const calls = [];
    const result = await describeRecoveryError(cause, {
      async request(...args) { calls.push(args); return { state }; },
    }, 'project', 'failed');
    assert.deepEqual(calls, [['locks.get', { projectName: 'project', runId: 'failed' }]]);
    assert.equal(result.canClearLock, state === 'stale');
    assert.equal(result.details, String(cause));
    if (state === 'stale') assert.match(result.message, /잠금을 해제해 주세요/);
    if (state === 'active') assert.match(result.message, /작업이 끝난 뒤/);
  }
});

test('unverified lock failures retain diagnostics without offering cleanup', async () => {
  const result = await describeRecoveryError('is already locked', {
    async request() { throw new Error('backend unavailable'); },
  }, 'project', 'failed');
  assert.equal(result.canClearLock, false);
  assert.match(result.message, /상태 조회에 실패/);
  assert.match(result.details, /backend unavailable/);
  const unrelated = await describeRecoveryError('merge conflict', {
    async request() { assert.fail('Unrelated errors must not inspect locks'); },
  }, 'project', 'failed');
  assert.equal(unrelated.message, 'merge conflict');
  assert.equal(unrelated.canClearLock, false);
});

test('retry instructions and preview status are typed ordinary RPC requests', async () => {
  const { api, calls } = bridge();
  await api.request('runs.planningPreviewStatus', { projectName: 'project', runId: 'group' });
  await api.request('tasks.retryContext', { projectName: 'project', runId: 'group', taskId: 'task' });
  await api.request('tasks.saveRetryInstruction', { projectName: 'project', runId: 'group', taskId: 'task',
    text: 'fix', requestId: 'request', fingerprint: 'failure' });
  assert.equal(calls.length, 3);
  assert.ok(calls.every(([channel]) => channel === 'orchestrator:request'));
});

test('chat repair crosses the real preload allowlist with current failure and explicit request intact', async () => {
  const { recoverTaskFromChat } = require(join(output, 'renderer/src/chatTaskRecovery.js'));
  const task = { id: 'broken', status: 'failed', last_attempt_id: 'attempt-1' };
  const run = { id: 'group', stage: 'failed', plan_revision: 3, planning_conversation_revision: 7, tasks: [task] };
  const completed = { ...run, stage: 'ready_to_merge' };
  const { api, calls } = bridge(async (channel, method) => {
    assert.equal(channel, 'orchestrator:request');
    if (method === 'tasks.retryContext') return {
      task_id: task.id, can_save: true, fingerprint: 'failure', plan_revision: 3, attempt_id: 'attempt-1',
    };
    assert.equal(method, 'tasks.repairFromChat'); return completed;
  });
  const result = await recoverTaskFromChat({
    projectName: 'project', run, task, message: '고쳐서 계속해줘', requestId: 'explicit-repair',
    request: (method, params) => api.request(method, params), isCurrent: () => true,
  });
  assert.equal(result, completed);
  assert.deepEqual(calls, [
    ['orchestrator:request', 'tasks.retryContext', { projectName: 'project', runId: 'group', taskId: 'broken' }],
    ['orchestrator:request', 'tasks.repairFromChat', { projectName: 'project', runId: 'group', taskId: 'broken',
      requestId: 'explicit-repair', message: '고쳐서 계속해줘', fingerprint: 'failure', conversationRevision: 7 }],
  ]);
});

test('effort selection, comparison, reservation and plan application use allowed requests', async () => {
  const { api, calls } = bridge();
  for (const method of ['runs.previewEffortMode', 'runs.setEffortMode', 'runs.cancelEffortReservation', 'runs.applyEffortModeToPlan']) {
    await api.request(method, { projectName: 'project', runId: 'group' });
  }
  assert.equal(calls.length, 4);
  assert.ok(calls.every(([channel]) => channel === 'orchestrator:request'));
});
