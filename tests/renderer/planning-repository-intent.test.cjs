const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');

const root = resolve(__dirname, '../..');
const tempRoot = join(root, '.tmp');
mkdirSync(tempRoot, { recursive: true });
const output = mkdtempSync(join(tempRoot, 'planning-repository-intent-'));
const cleanup = () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); };
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  execFileSync(process.execPath, [resolve(dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig',
    '--strict', '--target', 'ES2022', '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/App.tsx', 'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);
const draftModule = require(join(output, 'renderer/src/planningRequestDrafts.js'));
const app = readFileSync(join(output, 'renderer/src/App.js'), 'utf8');
function callback(name) {
  const match = app.match(new RegExp(`^    const ${name} = [\\s\\S]*?(?=^    (?:const|let|return) )`, 'm'));
  assert.ok(match, `App callback ${name} must exist`);
  return `${match[0]}\nthis.${name} = ${name};`;
}

function host(kind = 'docs_only', savedIntent = '') {
  const drafts = new draftModule.PlanningRequestDrafts();
  drafts.update('empty', { request: '기획서 없이 새 앱 만들기', repositoryIntent: savedIntent });
  const state = { intent: savedIntent, request: '', error: '', capabilities: undefined, profileKey: '' };
  const requests = [];
  const context = {
    react_1: { useCallback: (fn) => fn }, planningRequestDrafts_1: draftModule,
    planningStart_1: require(join(output, 'renderer/src/planningStart.js')), planningStartPendingRef: { current: false },
    planningPreparationsRef: { current: new Set() }, selectedChatDraftRef: { current: { projectName:'empty',id:'' } },
    setChatDraftSelection(projectName,id=''){context.selectedChatDraftRef.current={projectName,id};},
    planningRequestDrafts: { current: drafts }, selectedContextRef: { current: { projectName: 'empty', runId: '' } },
    projectCapabilitiesRequestRef: { current: 0 }, editedPlanningProfileContext: { current: '' },
    setRepositoryIntent: (value) => { state.intent = typeof value === 'function' ? value(state.intent) : value; },
    setPlanningRequest: (value) => { state.request = value; },
    setProjectCapabilities: (value) => { state.capabilities = value; },
    setPlanningProfileKey: (value) => { state.profileKey = typeof value === 'function' ? value(state.profileKey) : value; },
    setError: (value) => { state.error = value; }, errorMessage: (error) => error.message,
    setPlanningProfiles() {}, setProviderStatuses() {}, setTaskProfileOptions() {}, setPlanningPath() {}, setPlanningMode() {},
    setPlanningEffortMode() {}, setPlanningReasoning() {}, setPlanningProfileManual() {},
    setBusyAction() {}, setNotice() {}, setPlanningStartElapsed() {}, setPlanningPreparationMessage() {},
    setPlanningIndex() {}, setPlanningStartErrors() {}, replaceRun() {}, setSelectedRunId() {}, setWorkbenchView() {},
    loadProjects: async () => {}, loadRuns: async () => {}, archiveScopeRef: { current: 'active' },
    providerProfileKey: (profile) => profile?.model || '',
    selectedProjectName: 'empty', planningPath: '', planningMode: 'directed',
    planningRequest: '기획서 없이 새 앱 만들기', planningReasoning: '', planningEffortMode: 'balanced',
    planningProfileManual: false, selectedPlanningProfile: undefined, repositoryIntent: savedIntent,
    projectCapabilities: undefined,
    window: { setInterval: () => 1, clearInterval() {}, orchestrator: { request: async (method, params) => {
      requests.push({ method, params });
      if (method === 'projects.capabilities') return { repository_maturity: { kind } };
      if (method === 'providers.planning' || method === 'providers.status') return [];
      if (method === 'runs.list') return [];
      return { id: 'prepared' };
    } } },
  };
  for (const name of ['restorePlanningDraft', 'loadProjectCapabilities', 'startPlanning']) {
    runInNewContext(callback(name), context);
  }
  return { context, state, drafts, requests };
}

test('empty repository auto intent survives reopening the same project draft', async () => {
  const fixture = host();
  await fixture.context.loadProjectCapabilities('empty');
  assert.equal(fixture.state.intent, 'new_project');
  assert.equal(fixture.drafts.load('empty').repositoryIntent, 'new_project');
  fixture.context.restorePlanningDraft('empty', '');
  assert.equal(fixture.state.intent, 'new_project');
  assert.equal(fixture.state.request, '기획서 없이 새 앱 만들기');
});

test('empty repository corrects stale existing intent without losing the request or AI settings', async () => {
  const fixture = host('docs_only', 'existing_structure');
  fixture.drafts.update('empty', { profileManual: true, profileKey: 'chosen-model', effortMode: 'focused' });
  await fixture.context.loadProjectCapabilities('empty');
  fixture.context.restorePlanningDraft('empty', '');
  assert.equal(fixture.state.intent, 'new_project');
  assert.equal(fixture.drafts.load('empty').effortMode, 'focused');
  assert.equal(fixture.state.profileKey, 'chosen-model');
  assert.equal(fixture.state.request, '기획서 없이 새 앱 만들기');
});

test('planning request normalizes empty or stale intents to the greenfield gate without documents', async () => {
  for (const intent of ['', 'existing_structure', 'new_project']) {
    const fixture = host('docs_only', intent);
    fixture.context.projectCapabilities = { repository_maturity: { kind: 'docs_only' } };
    await fixture.context.startPlanning();
    assert.equal(fixture.state.error, '');
    const prepared = fixture.requests.find((item) => item.method === 'runs.preparePlanning');
    assert.equal(prepared.params.repositoryIntent, 'new_project');
    assert.equal(prepared.params.specPath, '');
    assert.equal(prepared.params.planningRequest, '기획서 없이 새 앱 만들기');
    assert.equal(fixture.requests.some((item) => item.method === 'planning.refreshIndex'), false);
    assert.equal(fixture.requests.some((item) => item.method === 'runs.runPlanning'), true);
  }
});

test('planning cannot submit while repository inspection is pending', async () => {
  const fixture = host();
  await fixture.context.startPlanning();
  assert.equal(fixture.requests.length, 0);
  assert.equal(fixture.drafts.load('empty').request, '기획서 없이 새 앱 만들기');
});

test('existing code defaults and explicit ambiguous choices remain intact', async () => {
  for (const [kind, intent, expected] of [
    ['existing_code', '', 'existing_structure'], ['existing_code', 'new_project', 'new_project'],
    ['ambiguous', '', ''], ['ambiguous', 'existing_structure', 'existing_structure'], ['ambiguous', 'new_project', 'new_project'],
  ]) {
    const fixture = host(kind, intent);
    await fixture.context.loadProjectCapabilities('empty');
    fixture.context.restorePlanningDraft('empty', '');
    assert.equal(fixture.state.intent, expected);
  }
});

test('late capability responses cannot modify another selected project or its drafts', async () => {
  const fixture = host();
  const pending = fixture.context.loadProjectCapabilities('empty');
  fixture.context.selectedContextRef.current = { projectName: 'other', runId: '' };
  fixture.drafts.update('other', { repositoryIntent: 'existing_structure', request: '다른 요청' });
  await pending;
  assert.equal(fixture.state.capabilities, undefined);
  assert.equal(fixture.drafts.load('empty').repositoryIntent, '');
  assert.equal(fixture.drafts.load('other').repositoryIntent, 'existing_structure');
  assert.equal(fixture.drafts.load('other').request, '다른 요청');
});

test('failed connection lookup removes old candidates with an explicit error and preserves the request draft', async () => {
  for (const current of [true, false]) {
    const fixture = host();
    const changes = [];
    fixture.context.setPlanningProfiles = value => changes.push(['planning', value.length]);
    fixture.context.setProviderStatuses = value => changes.push(['status', value.length]);
    fixture.context.setTaskProfileOptions = value => changes.push(['tasks', Object.keys(value).length]);
    fixture.context.window.orchestrator.request = async () => { throw Error('connection lookup failed'); };
    const pending = fixture.context.loadProjectCapabilities('empty');
    if (!current) fixture.context.selectedContextRef.current.projectName = 'other';
    assert.equal(await pending, false);
    assert.deepEqual(changes, current ? [['planning', 0], ['status', 0], ['tasks', 0]] : []);
    assert.equal(fixture.state.error, current ? 'connection lookup failed' : '');
    assert.equal(fixture.drafts.load('empty').request, '기획서 없이 새 앱 만들기');
  }
});

test('connection refresh preserves a conversation selection instead of silently switching providers', async () => {
  const fixture = host();
  fixture.context.selectedContextRef.current.runId = 'group';
  fixture.state.profileKey = 'claude-model';
  const connected = [{ model: 'codex-model', is_default: true, configured_model: 'codex-model' }];
  fixture.context.window.orchestrator.request = async method => {
    if (method === 'providers.planning') return connected;
    if (method === 'providers.status') return [];
    return { repository_maturity: { kind: 'existing_code' } };
  };
  assert.equal(await fixture.context.loadProjectCapabilities('empty'), true);
  assert.equal(fixture.state.profileKey, 'claude-model');
  assert.equal(fixture.drafts.load('empty').request, '기획서 없이 새 앱 만들기');
  connected.push({ model: 'claude-model' });
  await fixture.context.loadProjectCapabilities('empty');
  assert.equal(fixture.state.profileKey, 'claude-model');
});

test('failed execution candidate lookup clears only the current project and group candidates', async () => {
  const source = callback('loadTaskProfiles');
  for (const current of [true, false]) {
    const fixture = host();
    const options = [];
    fixture.context.selectedContextRef.current.runId = 'group';
    fixture.context.taskProfileRequestRef = { current: 0 };
    fixture.context.runExecutionControl_1 = require(join(output, 'renderer/src/runExecutionControl.js'));
    fixture.context.capabilityKey = value => JSON.stringify(value);
    fixture.context.runContextMatches = (a, b, c, d) => a === c && b === d;
    fixture.context.setTaskProfileOptions = value => options.push(value);
    fixture.context.window.orchestrator.request = async () => { throw Error('execution candidates failed'); };
    runInNewContext(source, fixture.context);
    const pending = fixture.context.loadTaskProfiles('empty', { id: 'group', tasks: [{ id: 'task', capabilities: ['general'] }] });
    if (!current) fixture.context.selectedContextRef.current.runId = 'other';
    await pending;
    assert.equal(options.length, current ? 1 : 0);
    if (current) assert.deepEqual(Object.keys(options[0]), []);
    assert.equal(fixture.state.error, current ? 'execution candidates failed' : '');
  }
});
