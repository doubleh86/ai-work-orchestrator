const { execFileSync } = require('node:child_process');
const { existsSync } = require('node:fs');
const { resolve } = require('node:path');

function architectureProblems({ host, node, electron, python }) {
  if (host !== 'arm64') return [];
  const problems = [];
  if (node !== 'arm64') return [`현재 Node.js가 ${node}입니다. arm64 Node.js로 npm install과 빌드를 실행하세요.`];
  if (!electron.includes('arm64')) problems.push('Electron 실행 파일에 arm64 아키텍처가 없습니다. arm64 Node.js에서 npm install을 다시 실행하세요.');
  if (python !== 'arm64') problems.push(`Python backend가 ${python}입니다. arm64 Python 3.11+로 별도 가상환경을 만들고 AI_ORCHESTRATOR_PYTHON을 지정하세요.`);
  return problems;
}

function selectedPython(root, environment = process.env) {
  const configured = environment.AI_ORCHESTRATOR_PYTHON?.trim();
  if (configured) return configured;
  const venv = resolve(root, '.venv', 'bin', 'python');
  return existsSync(venv) ? venv : 'python';
}

function macHostArchitecture(run = execFileSync) {
  try {
    if (run('arch', ['-arm64', '/usr/bin/uname', '-m'], { encoding: 'utf8' }).trim() === 'arm64') return 'arm64';
  } catch {
    // Intel Macs cannot run the arm64 slice; use their normal architecture below.
  }
  return run('uname', ['-m'], { encoding: 'utf8' }).trim();
}

function inspectMacArchitecture(root, python = selectedPython(root)) {
  if (process.platform !== 'darwin') return { host: 'other', node: process.arch, electron: [], python: 'not-checked' };
  const host = macHostArchitecture();
  if (host !== 'arm64') return { host, node: process.arch, electron: [], python: 'not-checked' };
  if (process.arch !== 'arm64') return { host, node: process.arch, electron: [], python: 'not-checked' };
  const electronBinary = resolve(root, 'node_modules', 'electron', 'dist', 'Electron.app', 'Contents', 'MacOS', 'Electron');
  const electron = execFileSync('lipo', ['-archs', electronBinary], { encoding: 'utf8' }).trim().split(/\s+/u);
  const pythonArchitecture = execFileSync(python, ['-c', 'import platform; print(platform.machine())'], { encoding: 'utf8' }).trim();
  return { host, node: process.arch, electron, python: pythonArchitecture };
}

function checkMacArchitecture(root, python) {
  const found = inspectMacArchitecture(root, python);
  const problems = architectureProblems(found);
  if (problems.length) throw new Error(problems.join('\n'));
  return found;
}

if (require.main === module) {
  try {
    const found = checkMacArchitecture(resolve(__dirname, '..'));
    if (found.host === 'arm64') process.stdout.write('macOS arm64 Node.js·Electron·Python 확인 완료\n');
  } catch (error) {
    process.stderr.write(`macOS arm64 실행 검사 실패: ${error.message}\n`);
    process.exitCode = 1;
  }
}

module.exports = { architectureProblems, checkMacArchitecture, inspectMacArchitecture, macHostArchitecture, selectedPython };
