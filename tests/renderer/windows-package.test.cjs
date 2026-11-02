const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } = require('node:fs');
const { join, dirname, resolve } = require('node:path');
const { tmpdir } = require('node:os');
const { peArchitecture, requireNewOutput, verifyPackage } = require('../../scripts/package_windows_x64.cjs');

function executable(machine = 0x8664) {
  const buffer = Buffer.alloc(256);
  buffer.write('MZ'); buffer.writeUInt32LE(128, 60); buffer.writeUInt32LE(0x00004550, 128); buffer.writeUInt16LE(machine, 132);
  return buffer;
}

function fixture(action) {
  const parent = resolve(tmpdir());
  const directory = mkdtempSync(join(parent, 'windows-package-'));
  try { action(directory); }
  finally { assert.equal(dirname(directory), parent); rmSync(directory, { recursive: true, force: true }); }
}

test('native PE headers distinguish x64 from incompatible binaries and reject corrupt input', () => fixture((directory) => {
  const file = join(directory, 'binary.exe');
  for (const [machine, architecture] of [[0x8664, 'x64'], [0x014c, 'x86'], [0xaa64, 'arm64']]) {
    writeFileSync(file, executable(machine)); assert.equal(peArchitecture(file), architecture);
  }
  writeFileSync(file, executable(0xffff)); assert.throws(() => peArchitecture(file), /Unsupported/);
  writeFileSync(file, 'invalid'); assert.throws(() => peArchitecture(file), /Invalid Windows executable/);
  const corrupt = executable(); corrupt.writeUInt32LE(2048, 60);
  writeFileSync(file, corrupt); assert.throws(() => peArchitecture(file), /Invalid PE header/);
}));

test('output protection preserves an existing successful or failed build', () => fixture((directory) => {
  const output = join(directory, '0.3.0');
  requireNewOutput(output);
  mkdirSync(output);
  assert.throws(() => requireNewOutput(output), /덮어쓰지/);
  const marker = join(output, 'receipt.txt'); writeFileSync(marker, 'keep');
  assert.throws(() => requireNewOutput(output), /덮어쓰지/);
  assert.equal(readFileSync(marker, 'utf8'), 'keep');
}));

test('portable verification requires the backend and Codex helpers and rejects wrong versions or architecture', () => fixture((directory) => {
  const required = [
    'AI Work Orchestrator.exe', 'LICENSE', 'LICENSES.chromium.html',
    'resources/app/dist-electron/main/main.js', 'resources/app/dist-electron/main/preload.js',
    'resources/app/dist/renderer/index.html', 'resources/backend/ai-orchestrator-backend.exe',
    'resources/app/licenses/APP-LICENSE.txt', 'resources/app/licenses/THIRD_PARTY_NOTICES.md',
    'resources/app/licenses/codex/LICENSE', 'resources/app/licenses/npm-licenses.json',
    'resources/app/licenses/npm/node_modules/@fontsource-variable/geist/LICENSE',
    'resources/app/licenses/npm/node_modules/@fontsource-variable/jetbrains-mono/LICENSE',
    'resources/backend/_internal/codex_cli_bin/bin/codex.exe',
    'resources/backend/_internal/codex_cli_bin/bin/codex-code-mode-host.exe',
    'resources/backend/_internal/codex_cli_bin/codex-package.json',
    'resources/backend/_internal/codex_cli_bin/codex-resources/codex-command-runner.exe',
    'resources/backend/_internal/codex_cli_bin/codex-resources/codex-windows-sandbox-setup.exe',
  ];
  for (const name of required) {
    const file = join(directory, name); mkdirSync(dirname(file), { recursive: true });
    writeFileSync(file, name.endsWith('.exe') ? executable() : 'fixture');
  }
  const metadata = join(directory, 'resources/app/package.json');
  writeFileSync(metadata, JSON.stringify({ version: '0.3.0', main: 'dist-electron/main/main.js' }));
  verifyPackage(directory, '0.3.0');
  assert.throws(() => verifyPackage(directory, '0.2.0'), /version or main entry/);
  const backend = join(directory, 'resources/backend/ai-orchestrator-backend.exe');
  writeFileSync(backend, executable(0xaa64)); assert.throws(() => verifyPackage(directory, '0.3.0'), /x64 executable required/);
  writeFileSync(backend, executable());
  const helper = join(directory, required.at(-1)); rmSync(helper);
  assert.throws(() => verifyPackage(directory, '0.3.0'), /missing.*sandbox-setup/);
}));
