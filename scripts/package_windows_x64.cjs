const { execFileSync, spawnSync } = require('node:child_process');
const { closeSync, cpSync, existsSync, mkdirSync, openSync, readFileSync, readSync, renameSync, writeFileSync } = require('node:fs');
const { join, resolve } = require('node:path');
const { createHash } = require('node:crypto');
const { copyPublicNotices } = require('./third_party_notices.cjs');

const root = resolve(__dirname, '..');
const productName = 'AI Work Orchestrator';

function run(command, args, environment = process.env) {
  const completed = spawnSync(command, args, { cwd: root, stdio: 'inherit', env: environment, windowsHide: true, shell: false });
  if (completed.error) throw completed.error;
  if (completed.status !== 0) throw new Error(`${command} failed with exit code ${completed.status}`);
}

function peArchitecture(file) {
  const descriptor = openSync(file, 'r');
  try {
    const dos = Buffer.alloc(64);
    if (readSync(descriptor, dos, 0, dos.length, 0) !== dos.length || dos.toString('ascii', 0, 2) !== 'MZ') {
      throw new Error(`Invalid Windows executable: ${file}`);
    }
    const header = Buffer.alloc(6);
    if (readSync(descriptor, header, 0, header.length, dos.readUInt32LE(60)) !== header.length
      || header.readUInt32LE(0) !== 0x00004550) throw new Error(`Invalid PE header: ${file}`);
    const architecture = { 0x8664: 'x64', 0x014c: 'x86', 0xaa64: 'arm64' }[header.readUInt16LE(4)];
    if (!architecture) throw new Error(`Unsupported Windows executable architecture: ${file}`);
    return architecture;
  } finally { closeSync(descriptor); }
}

function requireX64(file) {
  const architecture = peArchitecture(file);
  if (architecture !== 'x64') throw new Error(`x64 executable required, got ${architecture}: ${file}`);
}

function requireNewOutput(directory) {
  if (existsSync(directory)) throw new Error(`기존 또는 실패 빌드를 덮어쓰지 않습니다. 경로를 확인하고 별도로 보관하세요: ${directory}`);
}

function verifyPackage(directory, version) {
  const app = join(directory, 'resources', 'app');
  const required = [
    join(directory, `${productName}.exe`), join(directory, 'LICENSE'), join(directory, 'LICENSES.chromium.html'),
    join(app, 'package.json'), join(app, 'dist-electron', 'main', 'main.js'),
    join(app, 'dist-electron', 'main', 'preload.js'), join(app, 'dist', 'renderer', 'index.html'),
    join(app, 'licenses', 'APP-LICENSE.txt'), join(app, 'licenses', 'THIRD_PARTY_NOTICES.md'),
    join(app, 'licenses', 'codex', 'LICENSE'), join(app, 'licenses', 'npm-licenses.json'),
    join(app, 'licenses', 'npm', 'node_modules', '@fontsource-variable', 'geist', 'LICENSE'),
    join(app, 'licenses', 'npm', 'node_modules', '@fontsource-variable', 'jetbrains-mono', 'LICENSE'),
    join(directory, 'resources', 'backend', 'ai-orchestrator-backend.exe'),
    join(directory, 'resources', 'backend', '_internal', 'codex_cli_bin', 'bin', 'codex.exe'),
    join(directory, 'resources', 'backend', '_internal', 'codex_cli_bin', 'bin', 'codex-code-mode-host.exe'),
    join(directory, 'resources', 'backend', '_internal', 'codex_cli_bin', 'codex-package.json'),
    join(directory, 'resources', 'backend', '_internal', 'codex_cli_bin', 'codex-resources', 'codex-command-runner.exe'),
    join(directory, 'resources', 'backend', '_internal', 'codex_cli_bin', 'codex-resources', 'codex-windows-sandbox-setup.exe'),
  ];
  for (const file of required) if (!existsSync(file)) throw new Error(`Portable package is missing: ${file}`);
  const packaged = JSON.parse(readFileSync(join(app, 'package.json'), 'utf8'));
  if (packaged.version !== version || packaged.main !== 'dist-electron/main/main.js') {
    throw new Error('Portable product version or main entry does not match the build');
  }
  for (const file of required.filter((file) => file.endsWith('.exe'))) requireX64(file);
}

function main() {
  if (process.platform !== 'win32' || process.arch !== 'x64') throw new Error('Windows x64 Node.js에서만 portable ZIP을 빌드할 수 있습니다.');
  const sourcePackage = require(join(root, 'package.json'));
  const version = sourcePackage.version;
  if (!/^\d+\.\d+\.\d+$/u.test(version)) throw new Error('Portable build requires a stable three-part product version');
  const output = join(root, 'build', 'windows-x64', version);
  requireNewOutput(output);
  const python = process.env.AI_ORCHESTRATOR_PYTHON?.trim() || join(root, '.venv', 'Scripts', 'python.exe');
  const details = JSON.parse(execFileSync(python, ['-c', [
    'import json,sys,importlib.metadata as m,PyInstaller,ai_orchestrator',
    'from codex_cli_bin import bundled_codex_path',
    'print(json.dumps(dict(python=sys.executable,product_version=ai_orchestrator.__version__,',
    'sdk_version=m.version("openai-codex"),codex=str(bundled_codex_path()),packager_version=PyInstaller.__version__)))',
  ].join('\n')], { cwd: root, encoding: 'utf8', windowsHide: true }));
  if (details.product_version !== version) throw new Error('Python backend and desktop product versions differ');
  if (details.packager_version !== '6.22.3') throw new Error('빌드 환경에 pyinstaller==6.22.3을 설치하세요.');
  const electron = join(root, 'node_modules', 'electron', 'dist');
  requireX64(join(electron, 'electron.exe')); requireX64(details.python); requireX64(details.codex);
  const sourceCommit = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8', windowsHide: true }).trim();
  run('git', ['diff', '--quiet', 'HEAD', '--', 'desktop', 'src', 'scripts', 'package.json', 'package-lock.json', 'pyproject.toml']);
  const npm = process.env.npm_execpath;
  if (!npm || !existsSync(npm)) throw new Error('npm run package:win-x64로 실행하세요.');
  run(process.execPath, [npm, 'run', 'build']);
  mkdirSync(join(root, 'build', 'windows-x64'), { recursive: true });
  mkdirSync(output);
  const stage = join(output, `${productName}.staging`);
  const final = join(output, productName);
  const backendDist = join(output, 'backend-dist');
  const config = join(output, 'pyinstaller-config');
  mkdirSync(config);
  run(python, [
    '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--noupx', '--name', 'ai-orchestrator-backend',
    '--paths', join(root, 'src'), '--collect-all', 'openai_codex', '--collect-all', 'codex_cli_bin',
    '--recursive-copy-metadata', 'openai-codex', '--copy-metadata', 'ai-work-orchestrator',
    '--distpath', backendDist, '--workpath', join(output, 'pyinstaller-work'), '--specpath', output,
    join(root, 'scripts', 'desktop_backend.py'),
  ], { ...process.env, PYINSTALLER_CONFIG_DIR: config });
  cpSync(electron, stage, { recursive: true, errorOnExist: true, force: false });
  renameSync(join(stage, 'electron.exe'), join(stage, `${productName}.exe`));
  const app = join(stage, 'resources', 'app');
  mkdirSync(app, { recursive: true });
  cpSync(join(root, 'dist-electron'), join(app, 'dist-electron'), { recursive: true });
  cpSync(join(root, 'dist', 'renderer'), join(app, 'dist', 'renderer'), { recursive: true });
  writeFileSync(join(app, 'package.json'), JSON.stringify({ name: sourcePackage.name, version, main: sourcePackage.main }, null, 2) + '\n', 'utf8');
  copyPublicNotices(root, join(app, 'licenses'));
  cpSync(join(backendDist, 'ai-orchestrator-backend'), join(stage, 'resources', 'backend'), { recursive: true });
  const info = { product: productName, version, platform: 'win32', architecture: 'x64', source_commit: sourceCommit,
    codex_sdk: details.sdk_version, pyinstaller: details.packager_version, electron: require(join(root, 'node_modules', 'electron', 'package.json')).version };
  writeFileSync(join(stage, 'build-info.json'), JSON.stringify(info, null, 2) + '\n', 'utf8');
  writeFileSync(join(stage, '사용 안내.txt'), [
    `${productName} v${version} · Windows x64 portable`, '',
    'ZIP 전체를 쓰기 가능한 로컬 폴더에 압축 해제하고 AI Work Orchestrator.exe를 실행하세요.',
    'Python, Node.js, 별도 Codex CLI 설치는 필요하지 않습니다. Codex 로그인은 앱의 AI 연결에서 직접 진행하세요.',
    'Git for Windows는 설치하고 PATH에 등록해야 합니다. 대상 프로젝트의 .NET 등 빌드 도구도 별도로 준비하세요.',
    '사용자 설정·프로젝트 목록·인증은 기존 사용자 설정 위치에 저장합니다. 실행 폴더에 인증을 넣지 않습니다.',
    '실행 파일과 resources 폴더를 함께 유지하세요. 기존 작업 폴더 위에 덮어쓰지 말고 새 버전 폴더로 교체하세요.',
    '이 빌드는 서명되지 않았습니다. Windows가 실행 안내를 표시할 수 있습니다.',
    '앱을 닫고 폴더를 지우면 실행 파일이 제거됩니다. 등록된 프로젝트·사용자 기록은 자동으로 삭제되지 않습니다.', '',
  ].join('\r\n'), 'utf8');
  verifyPackage(stage, version);
  renameSync(stage, final);
  const zip = join(output, `ai-work-orchestrator-v${version}-win-x64.zip`);
  run(python, ['-c', [
    'import sys,zipfile', 'from pathlib import Path', 'source=Path(sys.argv[1]); target=Path(sys.argv[2])',
    'with zipfile.ZipFile(target,"x",compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:',
    '    for path in sorted(source.rglob("*")):',
    '        if path.is_file(): archive.write(path,path.relative_to(source.parent))',
    'with zipfile.ZipFile(target) as archive:', '    bad=archive.testzip()',
    '    if bad: raise RuntimeError("Invalid ZIP entry: "+bad)',
  ].join('\n'), final, zip]);
  const digest = createHash('sha256').update(readFileSync(zip)).digest('hex');
  writeFileSync(`${zip}.sha256`, `${digest}  ${zip.split(/[\\/]/u).at(-1)}\n`, 'utf8');
  process.stdout.write(`Windows portable 빌드 완료: ${zip}\nSHA256: ${digest}\n`);
}

if (require.main === module) {
  try { main(); }
  catch (error) { process.stderr.write(`Windows portable 빌드 실패: ${error.message}\n`); process.exitCode = 1; }
}

module.exports = { peArchitecture, requireNewOutput, verifyPackage };
