# 공개 소스와 릴리즈

이 저장소는 공개용 소스와 이후 공개 변경 이력을 관리한다.
이전 비공개 저장소의 commit·tag·제작 기록·사용자 자료는 포함하지 않는다.
현재 소스 공개와 바이너리 Release 발행은 별도의 작업이다.

## 다음 버전 공개

1. 개발 원본에서 변경과 필요한 검증을 마친다.
2. 이 공개 저장소의 기존 checkout에서 소스·테스트·공개 문서만 갱신한다.
   `.git`을 복사하거나 초기화하지 않으며 공개된 이전 commit을 유지한다.
3. 인증 파일, 사용자 기록·설정, 임시 폴더, 다른 프로젝트의 코드·운영 기록,
   실명·회사 이메일·OS 사용자명·실제 PC 경로를 제외한다.
4. 공개용 의존성 보안 수정, LICENSE와 제3자 고지를 유지한다.
   이전 원본의 package 파일로 수정된 공개 의존성을 되돌리지 않는다.
5. diff·파일 목록·문서 참조·인증정보 패턴과 공개용 author/committer를 검토한다.
   기존 비공개 이력·브랜치·태그를 public remote에 보내지 않는다.
6. 검증을 통과한 공개 변경을 기존 main 위에 새 commit으로 추가하고 main만 push한다.

## 검증과 빌드

```bash
npm ci
npm audit
npm run typecheck
node --test tests/renderer/*.test.cjs
npm run build
python -m compileall -q src
python -m pytest tests
```

Python 테스트에는 별도로 pytest가 필요하다. 테스트에는 실제 사용자 인증이나
등록 프로젝트를 사용하지 않는다. 외부 AI 호출·새 PC 로그인·OS별 실행 검증은
자동 단위 테스트 통과와 구분해 기록한다.

바이너리는 검증한 공개 commit에서 새로 빌드한다. 이전 비공개 배포 ZIP을 그대로
첨부하지 않는다. 제품 버전은 package.json, package-lock.json, pyproject.toml과
Python 공개 버전에서 일치시킨다. 같은 버전의 기존 산출물을 덮어쓰지 않는다.
라이선스·폰트 고지·인증 및 상태 제외·압축 무결성·포함 runtime·실제 실행을 확인하고
승인된 버전 tag와 GitHub Release에 ZIP·체크섬·검증 범위를 함께 올린다.

Windows 빌드는 `python -m pip install -e '.[windows-build,mcp]'`로 준비하고
`npm run package:win-x64`로 실행한다. 생성된 앱 ZIP, MCP 전용 ZIP, 각 SHA256을
함께 첨부한다. MCP ZIP은 전체를 푼 뒤 동봉한 `MCP 사용 안내.txt`로 연결한다.

이번 초기 소스 공개는 바이너리의 새 PC 실행이나 정식 릴리즈 검증을 뜻하지 않는다.
