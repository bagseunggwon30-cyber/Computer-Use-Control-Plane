# Python 중심 CUCP 배포 — 0.4.0

## 구성

| 역할 | 구현 | 사용자 별도 설치 |
| --- | --- | --- |
| 세션·JSONL·관찰 ID·명령 검증·배치·창 대기 | Python → PyInstaller onedir `CUCP.exe` | 없음 |
| Windows 캡처·UIA·OCR·입력·권한 진단 | C# → .NET self-contained `native/` | 없음 |
| Pi 도구 등록·이미지 전달·취소 | 작은 TypeScript 확장 | 기존 Pi 호스트 필요 |
| 기존 앱별 매크로 | 소스 저장소의 PowerShell 호환 경로 | 배포본에 포함하지 않음 |

사용자는 폴더를 풀어 `CUCP.exe doctor --json`으로 실행 환경을 확인한 뒤
`pi --extension .\integrations\pi\src\index.ts`로 연결한다. CUCP 전용 Node 서버는 없다.
다른 호스트는 `CUCP.exe serve`를 직접 실행하고 JSONL 계약을 사용한다.

one-folder 배포를 사용해 실행마다 단일 파일을 임시 경로에 풀지 않으며,
`CUCP.exe`·`_internal`·`native`를 함께 유지한다. 설치기·자동 업데이트·코드 서명은 아직 없다.
ARM64 네이티브 worker 게시 옵션은 기존 개발 경로에 남지만, 완성 배포본은 이번에 검증하는 x64만 제공한다.

## 개발자 빌드

Windows x64, Python 3.12 x64, .NET 8 SDK가 필요하다. 다음은 빌드 머신 요건이며 배포 사용자 요건이 아니다.

```text
python -m pip install -r pcucp-next/packaging/requirements-build.txt
python pcucp-next/packaging/build_portable.py
```

`dist/CUCP-0.4.0-win-x64/`와 ZIP, ZIP SHA-256을 생성한다. 이전 결과를 덮어쓰지 않는다.
다시 빌드하려면 다른 `--output` 폴더를 지정한다. 빌더는 PowerShell을 호출하지 않는다.
빌드 후 다른 경로로 복사한 바이너리의 실행 검증이 실패하면 배포 파일을 확정하지 않는다.
`manifest.json`에 소스 커밋·Python·PyInstaller·SDK 버전이 기록되고 `licenses/`와 파일별 체크섬이 포함된다.

## 실행 경로

- Pi: `CUCP_EXECUTABLE` 절대 경로 → 루트의 `CUCP.exe` → 유효한 소스 체크아웃의 Python 순서다.
  명시한 실행 파일이 없거나 실패하면 다른 실행기로 자동 재시도하지 않는다.
- Portable native: `CUCP_NATIVE_HOST` 명시 경로 또는 실행 파일 옆 `native/PcuCp.NativeHost.exe`다.
  `CUCP_ROOT`, 현재 디렉터리, PyInstaller 내부 추출 경로는 기본 native 탐색에 사용하지 않는다.
- 소스 개발: 기존 `CUCP_ROOT`, `CUCP_PYTHON`, `pcucp-next/bin/native` 경로를 지원한다.
- `doctor`는 native `version`만 실행한다. 런타임 시작과 버전 일치는 확인하지만 실제 GUI 성공을 선언하지 않는다.

## 이번에 추가한 범용 기능

- `wait-window`: 제목 부분 문자열과 선택 PID로 최대 10초 대기한다. 여러 창이면 후보와
  `ambiguous_target`을 반환한다. 선택·포커스·입력을 자동 실행하지 않는다. 관찰 ID는 새로 받아야 한다.
- `click`의 `count: 2`: 좌표·PID·포커스·권한 확인 후 하나의 native 호출에서 더블클릭하고 새 화면을 반환한다.
  관찰 만료, 부분 입력 실패, 자동 재시도 금지 계약을 유지한다.

## 검증 범위

`core.yml`의 `windows-portable` 작업은 실제 Windows 배포본을 빌드하고 다음을 확인한다.

- 한글·공백이 있는 다른 폴더로 이동, 무관한 작업 디렉터리에서 실행
- 자식 PATH에 Python·Node·dotnet 없이 Python EXE와 자체 런타임을 가진 native EXE 시작
- UTF-8 JSONL, 기본 입력 차단, 허용 세션에서도 관찰 없는 입력 차단
- 동일 native PID의 연속 응답, 소스 전용 legacy 명령 제외
- Pi 연결부가 패키징된 엔진으로 권한 전환과 요청/응답 수행
- 전체 폴더 체크섬, PowerShell 스크립트 배포 제외

이 검사는 초기화와 프로토콜 검증이다. 실제 앱 더블클릭, UIA 공급자,
IME, 혼합 DPI/다중 모니터, 관리자 앱 제어는 사용자 Windows 데스크톱에서 검증해야 한다.
GitHub 언어 비율에는 여전히 보존 중인 레거시 소스가 포함된다. 레거시 전체 포팅이나 삭제를 완료했다는 뜻은 아니다.

## 공식 배포 문서

- [PyInstaller usage](https://pyinstaller.org/en/stable/usage.html)
- [PyInstaller runtime paths](https://pyinstaller.org/en/stable/runtime-information.html)
- [.NET publish](https://learn.microsoft.com/en-us/dotnet/core/tools/dotnet-publish)
