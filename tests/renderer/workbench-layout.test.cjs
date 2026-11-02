const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'workbench-layout-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/workbenchLayout.ts'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const {
  expectedWideTaskContentWidth,
  mobileWorkbenchPane,
  inspectorPanelId,
  resolveWorkbenchLayout,
  sideInspectorVisible,
  taskSelectionOpensDetail,
} = require(join(output, 'workbenchLayout.js'));

test('viewport bands choose single, compact, and medium layouts', () => {
  const panes = { groupPaneWidth: 296, inspectorWidth: 360 };
  assert.equal(resolveWorkbenchLayout({ ...panes, viewportWidth: 639 }), 'single');
  assert.equal(resolveWorkbenchLayout({ ...panes, viewportWidth: 640 }), 'compact');
  assert.equal(resolveWorkbenchLayout({ ...panes, viewportWidth: 959 }), 'compact');
  assert.equal(resolveWorkbenchLayout({ ...panes, viewportWidth: 960 }), 'medium');
});

test('wide layout accounts for saved pane widths and uses hysteresis', () => {
  const panes = { groupPaneWidth: 296, inspectorWidth: 360 };
  assert.equal(expectedWideTaskContentWidth({ ...panes, viewportWidth: 1420 }), 708);
  for (const viewportWidth of [1420, 1422, 1439, 1440]) {
    assert.equal(resolveWorkbenchLayout({ ...panes, viewportWidth }), 'wide');
  }

  assert.equal(resolveWorkbenchLayout({ ...panes, viewportWidth: 1415, previous: 'medium' }), 'medium');
  assert.equal(resolveWorkbenchLayout({ ...panes, viewportWidth: 1416, previous: 'medium' }), 'wide');
  assert.equal(resolveWorkbenchLayout({ ...panes, viewportWidth: 1392, previous: 'wide' }), 'wide');
  assert.equal(resolveWorkbenchLayout({ ...panes, viewportWidth: 1391, previous: 'wide' }), 'medium');

  const widePanes = { viewportWidth: 1440, groupPaneWidth: 320, inspectorWidth: 372 };
  assert.equal(expectedWideTaskContentWidth(widePanes), 692);
  assert.equal(resolveWorkbenchLayout({ ...widePanes, previous: 'wide' }), 'wide');
  assert.equal(resolveWorkbenchLayout({ ...widePanes, previous: 'medium' }), 'medium');
});

test('task selection only replaces the list in one-pane layouts', () => {
  assert.equal(taskSelectionOpensDetail('wide'), false);
  assert.equal(taskSelectionOpensDetail('medium'), false);
  assert.equal(taskSelectionOpensDetail('compact'), true);
  assert.equal(taskSelectionOpensDetail('single'), true);
});

test('manual collapse stays hidden across layout changes and ordinary selection', () => {
  for (const layout of ['wide', 'medium', 'compact', 'single', 'medium', 'wide']) {
    assert.equal(sideInspectorVisible(layout, false), false);
    assert.equal(taskSelectionOpensDetail(layout, false), false);
  }
  assert.equal(sideInspectorVisible('wide', true), true);
  assert.equal(sideInspectorVisible('medium', true), false);
  assert.equal(taskSelectionOpensDetail('compact', true), true);
  assert.equal(inspectorPanelId('wide'), 'side-inspector');
  assert.equal(inspectorPanelId('medium'), 'task-inspector');
});

test('compact navigation shows groups explicitly without blocking new planning', () => {
  assert.equal(mobileWorkbenchPane({ layout: 'compact', groupsRequested: false, hasRun: false, workbenchView: 'tasks' }), 'groups');
  assert.equal(mobileWorkbenchPane({ layout: 'single', groupsRequested: true, hasRun: true, workbenchView: 'tasks' }), 'groups');
  assert.equal(mobileWorkbenchPane({ layout: 'compact', groupsRequested: false, hasRun: false, workbenchView: 'planning' }), 'workbench');
  assert.equal(mobileWorkbenchPane({ layout: 'medium', groupsRequested: true, hasRun: true, workbenchView: 'tasks' }), 'workbench');
});
