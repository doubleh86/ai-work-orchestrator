const { execFileSync, spawnSync } = require('node:child_process');
const { closeSync, cpSync, existsSync, mkdirSync, openSync, readFileSync, readdirSync, readSync, renameSync, rmSync, writeFileSync } = require('node:fs');
const { basename, join, resolve } = require('node:path');
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
  ];
  for (const file of required) if (!existsSync(file)) throw new Error(`Portable package is missing: ${file}`);
  if (existsSync(join(directory, 'resources', 'backend', '_internal', 'codex_cli_bin'))) {
    throw new Error('Portable package must use the Codex CLI installed on the work PC');
  }
  const packaged = JSON.parse(readFileSync(join(app, 'package.json'), 'utf8'));
  if (packaged.version !== version || packaged.main !== 'dist-electron/main/main.js') {
    throw new Error('Portable product version or main entry does not match the build');
  }
  for (const file of required.filter((file) => file.endsWith('.exe'))) requireX64(file);
}

function writeArchive(python, directory, zip) {
  run(python, ['-c', [
    'import sys,zipfile', 'from pathlib import Path', 'source=Path(sys.argv[1]); target=Path(sys.argv[2])',
    'with zipfile.ZipFile(target,"x",compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:',
    '    for path in sorted(source.rglob("*")):',
    '        if path.is_file(): archive.write(path,path.relative_to(source.parent))',
    'with zipfile.ZipFile(target) as archive:', '    bad=archive.testzip()',
    '    if bad: raise RuntimeError("Invalid ZIP entry: "+bad)',
  ].join('\n'), directory, zip]);
  const digest = createHash('sha256').update(readFileSync(zip)).digest('hex');
  writeFileSync(`${zip}.sha256`, `${digest}  ${basename(zip)}\n`, 'utf8');
  process.stdout.write(`Windows ZIP 빌드 완료: ${zip}\nSHA256: ${digest}\n`);
}

function writeMcpPackage(directory, backend, notices, info) {
  cpSync(backend, directory, { recursive: true, errorOnExist: true, force: false });
  mkdirSync(join(directory, 'licenses', 'codex'), { recursive: true });
  for (const file of ['APP-LICENSE.txt', 'THIRD_PARTY_NOTICES.md', 'codex/LICENSE']) {
    cpSync(join(notices, file), join(directory, 'licenses', file));
  }
  writeFileSync(join(directory, 'build-info.json'), JSON.stringify(info, null, 2) + '\n', 'utf8');
  writeFileSync(join(directory, 'MCP 사용 안내.txt'), [
    `${productName} MCP v${info.version} · Windows x64`, '',
    '1. ZIP 전체를 로컬 폴더에 풀고 실행 파일과 _internal 폴더를 함께 유지하세요.',
    '2. Codex의 ~/.codex/config.toml에 아래 블록을 넣으세요. 같은 이름이 있으면 그 블록을 교체하세요.',
    '   command에는 압축을 푼 실행 파일의 전체 경로를 넣으세요. 경로 구분자로 /를 쓰면 됩니다.', '',
    '[mcp_servers.orchestrator]', 'command = "C:/MCP/ai-orchestrator-backend.exe"', 'args = ["mcp"]', '',
    '3. Codex를 다시 열고 “오케스트레이터에 등록된 프로젝트 보여줘”라고 요청하세요.', '',
    '같은 Windows 사용자로 실행하면 오케스트레이터 앱과 같은 등록 프로젝트를 조회합니다.',
    '프로젝트가 비어 있으면 먼저 오케스트레이터 앱에 프로젝트를 등록하세요.',
    '기획서 연결, 작업 복구, 로컬 Main 반영이 필요하면 args = ["mcp", "--allow-write"]로 바꾸세요.',
    '오래 걸리는 복구는 같은 블록에 tool_timeout_sec = 3600을 추가하세요.',
    '다른 작업 PC에서는 그 PC에 ZIP을 풀고, 앱과 같은 사용자 계정의 사설망 SSH로 실행하세요.',
    'MCP 실행에 Python 설치나 소스 다운로드는 필요하지 않습니다. Git과 작업별 빌드 도구는 별도로 준비하세요.', '',
    'AI 작업이 필요하면 작업 PC에 해당 실행기를 설치하세요. 조회는 설치 없이 사용할 수 있습니다.',
    'Codex CLI 설치: https://learn.chatgpt.com/docs/codex/cli',
    'Claude Code 설치: https://code.claude.com/docs/en/setup', '',
  ].join('\r\n'), 'utf8');
}

function main() {
  if (process.platform !== 'win32' || process.arch !== 'x64') throw new Error('Windows x64 Node.js에서만 portable ZIP을 빌드할 수 있습니다.');
  const args = process.argv.slice(2);
  if (args.length > 1 || (args.length === 1 && args[0] !== '--preview')) throw new Error('빌드 옵션은 --preview만 지원합니다.');
  const preview = args.length === 1;
  const sourcePackage = require(join(root, 'package.json'));
  const version = sourcePackage.version;
  if (!/^\d+\.\d+\.\d+$/u.test(version)) throw new Error('Portable build requires a stable three-part product version');
  const buildLabel = preview ? `${version}-preview-${Date.now()}` : version;
  const output = join(root, 'build', 'windows-x64', buildLabel);
  requireNewOutput(output);
  const python = process.env.AI_ORCHESTRATOR_PYTHON?.trim() || join(root, '.venv', 'Scripts', 'python.exe');
  const details = JSON.parse(execFileSync(python, ['-c', [
    'import json,sys,importlib.metadata as m,PyInstaller,ai_orchestrator',
    'print(json.dumps(dict(python=sys.executable,product_version=ai_orchestrator.__version__,',
    'sdk_version=m.version("openai-codex"),packager_version=PyInstaller.__version__,mcp_version=m.version("mcp"))))',
  ].join('\n')], { cwd: root, encoding: 'utf8', windowsHide: true }));
  if (details.product_version !== version) throw new Error('Python backend and desktop product versions differ');
  if (details.packager_version !== '6.22.3') throw new Error('빌드 환경에 pyinstaller==6.22.3을 설치하세요.');
  const electron = join(root, 'node_modules', 'electron', 'dist');
  requireX64(join(electron, 'electron.exe')); requireX64(details.python);
  const sourceCommit = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8', windowsHide: true }).trim();
  if (!preview) {
    const changes = execFileSync('git', ['status', '--porcelain', '--untracked-files=all', '--',
      'desktop', 'src', 'scripts', 'package.json', 'package-lock.json', 'pyproject.toml'], { cwd: root, encoding: 'utf8', windowsHide: true });
    if (changes.trim()) throw new Error('릴리즈 빌드에는 커밋된 제품 소스가 필요합니다. 로컬 검증에는 --preview를 사용하세요.');
  }
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
    '--paths', join(root, 'src'), '--collect-all', 'openai_codex', '--exclude-module', 'codex_cli_bin', '--collect-data', 'mcp',
    '--copy-metadata', 'openai-codex', '--recursive-copy-metadata', 'mcp', '--copy-metadata', 'ai-work-orchestrator',
    '--distpath', backendDist, '--workpath', join(output, 'pyinstaller-work'), '--specpath', output,
    join(root, 'scripts', 'desktop_backend.py'),
  ], { ...process.env, PYINSTALLER_CONFIG_DIR: config });
  const backend = join(backendDist, 'ai-orchestrator-backend');
  const internal = join(backend, '_internal');
  for (const name of readdirSync(internal)) {
    if (name.endsWith('.dist-info')) rmSync(join(internal, name, 'direct_url.json'), { force: true });
  }
  run(python, [join(root, 'scripts', 'smoke_packaged_mcp.py'), join(backend, 'ai-orchestrator-backend.exe')]);
  cpSync(electron, stage, { recursive: true, errorOnExist: true, force: false });
  renameSync(join(stage, 'electron.exe'), join(stage, `${productName}.exe`));
  const app = join(stage, 'resources', 'app');
  mkdirSync(app, { recursive: true });
  cpSync(join(root, 'dist-electron'), join(app, 'dist-electron'), { recursive: true });
  cpSync(join(root, 'dist', 'renderer'), join(app, 'dist', 'renderer'), { recursive: true });
  writeFileSync(join(app, 'package.json'), JSON.stringify({ name: sourcePackage.name, version, main: sourcePackage.main }, null, 2) + '\n', 'utf8');
  copyPublicNotices(root, join(app, 'licenses'));
  cpSync(backend, join(stage, 'resources', 'backend'), { recursive: true });
  const info = { product: productName, version, platform: 'win32', architecture: 'x64', source_commit: sourceCommit,
    source_tree: preview ? 'working-tree-preview' : 'committed', codex_sdk: details.sdk_version,
    mcp_sdk: details.mcp_version, pyinstaller: details.packager_version };
  const electronVersion = require(join(root, 'node_modules', 'electron', 'package.json')).version;
  writeFileSync(join(stage, 'build-info.json'), JSON.stringify({ ...info, electron: electronVersion }, null, 2) + '\n', 'utf8');
  writeFileSync(join(stage, '사용 안내.txt'), [
    `${productName} v${version} · Windows x64 portable`, '',
    'ZIP 전체를 쓰기 가능한 로컬 폴더에 압축 해제하고 AI Work Orchestrator.exe를 실행하세요.',
    '앱 자체를 실행하는 데 Python이나 Node.js 설치는 필요하지 않습니다.',
    'Codex로 작업하려면 Codex CLI를 설치한 뒤 앱의 AI 연결에서 로그인하세요. https://learn.chatgpt.com/docs/codex/cli',
    'Claude로 작업하려면 Claude Code CLI를 설치하세요. https://code.claude.com/docs/en/setup',
    '앱 설정에서 Codex에서 진행 상황 보기를 선택하면 조회 연결을 등록합니다.',
    'Git for Windows는 설치하고 PATH에 등록해야 합니다. 대상 프로젝트의 .NET 등 빌드 도구도 별도로 준비하세요.',
    '사용자 설정·프로젝트 목록·인증은 기존 사용자 설정 위치에 저장합니다. 실행 폴더에 인증을 넣지 않습니다.',
    '실행 파일과 resources 폴더를 함께 유지하세요. 기존 작업 폴더 위에 덮어쓰지 말고 새 버전 폴더로 교체하세요.',
    '이 빌드는 서명되지 않았습니다. Windows가 실행 안내를 표시할 수 있습니다.',
    '앱을 닫고 폴더를 지우면 실행 파일이 제거됩니다. 등록된 프로젝트·사용자 기록은 자동으로 삭제되지 않습니다.', '',
  ].join('\r\n'), 'utf8');
  verifyPackage(stage, version);
  renameSync(stage, final);
  const mcpDirectory = join(output, `${productName} MCP`);
  writeMcpPackage(mcpDirectory, backend, join(final, 'resources', 'app', 'licenses'), { ...info, product: `${productName} MCP` });
  writeArchive(python, final, join(output, `ai-work-orchestrator-v${buildLabel}-win-x64.zip`));
  writeArchive(python, mcpDirectory, join(output, `ai-work-orchestrator-mcp-v${buildLabel}-win-x64.zip`));
}

if (require.main === module) {
  try { main(); }
  catch (error) { process.stderr.write(`Windows portable 빌드 실패: ${error.message}\n`); process.exitCode = 1; }
}

module.exports = { peArchitecture, requireNewOutput, verifyPackage };
