const { test } = require('node:test');
const assert = require('node:assert/strict');
const { architectureProblems, macHostArchitecture, selectedPython } = require('../../scripts/macos_architecture.cjs');

test('Apple Silicon is detected even when the current Node process runs through Rosetta', () => {
  const calls = [];
  const host = macHostArchitecture((command) => {
    calls.push(command);
    return 'arm64\n';
  });
  assert.equal(host, 'arm64');
  assert.deepEqual(calls, ['arch']);
});

test('Intel Mac detection falls back when no arm64 executable can run', () => {
  const host = macHostArchitecture((command) => {
    if (command === 'arch') throw new Error('unsupported architecture');
    return 'x86_64\n';
  });
  assert.equal(host, 'x86_64');
});

test('Apple Silicon requires both Electron and Python to contain arm64 code', () => {
  assert.deepEqual(architectureProblems({ host: 'arm64', node: 'arm64', electron: ['arm64'], python: 'arm64' }), []);
  const problems = architectureProblems({ host: 'arm64', node: 'arm64', electron: ['x86_64'], python: 'x86_64' });
  assert.equal(problems.length, 2);
  assert.match(problems[0], /Electron/);
  assert.match(problems[1], /Python backend/);
  assert.deepEqual(architectureProblems({ host: 'arm64', node: 'x64', electron: [], python: 'not-checked' }).length, 1);
});

test('Intel and other hosts do not require arm64 binaries', () => {
  assert.deepEqual(architectureProblems({ host: 'x86_64', node: 'x64', electron: ['x86_64'], python: 'x86_64' }), []);
  assert.deepEqual(architectureProblems({ host: 'other', node: 'x64', electron: [], python: 'not-checked' }), []);
});

test('explicit backend Python takes priority over checkout environment', () => {
  assert.equal(selectedPython('/checkout', { AI_ORCHESTRATOR_PYTHON: ' /native/python ' }), '/native/python');
});
