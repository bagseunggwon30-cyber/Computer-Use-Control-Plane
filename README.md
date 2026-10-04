# CUCP — Computer Use Control Plane

> **Python + C# 이전 브랜치:** Pi 없이 stdio MCP 또는 JSONL로 연결합니다. [공통 설치·권한·프로토콜](docs/host-neutral-setup.md), [워크플로·작업·폼](docs/workflow-migration.md), [이전 범위와 남은 기능](docs/migration-matrix.md), [검증된 이전 현황과 남은 검증](docs/migration-checkpoint-report.md)을 참고하세요. 이 브랜치의 기능은 정확히 같은 커밋에서 빌드한 실행 파일과 함께 사용해야 합니다.

## AI 호스트 공통 시작점

Windows 소스 개발 환경에서 Python 3.10+와 .NET 8 SDK를 준비한 뒤 저장소 루트에서 실행합니다:

```text
python pcucp-next/packaging/publish_native.py
python -m pip install -e pcucp-next/python
cucp mcp
```

MCP를 지원하는 로컬 AI 호스트에 연결하거나 `cucp serve`의 JSONL을 자체 도구 호출에 연결합니다. 기본 읽기 전용이며, 사용자가 허용한 세션만 실행 인자 `--allow-live-control`로 조작을 켭니다. Pi는 선택적인 어댑터입니다. 도구 연결 기능이 없는 채팅 앱까지 자동으로 연결되는 것은 아닙니다.


CUCP는 Computer Use가 없는 AI 호스트에 Windows 관찰·입력 기능을 연결하는 실행 엔진입니다.
**Python MCP/JSONL 본체 + C# Windows 제어부 + 선택적 TypeScript Pi 어댑터**를 사용합니다.
모델·API 키·대화 관리는 호스트가 담당합니다. 앱별 확장 개발은 종료하고 범용 코어에 집중합니다.

## 기존 0.4.0 포터블 · 선택적 Pi 어댑터

[GitHub Actions의 CUCP core](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/workflows/core.yml)
에서 해당 커밋의 성공한 `windows-portable` 작업이 올린 **CUCP-0.4.0-win-x64** 아티팩트를 받습니다.
안의 ZIP을 풀고 폴더 전체를 유지하세요. CUCP용 Python·Node.js·.NET의 별도 설치가 필요 없습니다.
아티팩트 이름의 0.4.0만으로 새 기능 포함 여부를 판단하지 마세요. 실행한 커밋과 배포 manifest의 git_commit을 확인하고, 이 브랜치의 변경은 같은 커밋의 성공한 CI 아티팩트로 사용하세요. 모델은 포함하지 않으며, 아래 Pi 예제를 선택할 때만 Pi 설치가 필요합니다.

```text
.\CUCP.exe doctor --json
pi --extension .\integrations\pi\src\index.ts
```

Pi에서 `/computer status`로 확인하고 사람이 `/computer on`을 실행하면 입력을 허용합니다.
`/computer off`는 CUCP 입력을 끕니다. `cucp_windows` → `cucp_observe` → `cucp_action` 순으로 사용합니다.
실행 파일은 CLI/JSONL 엔진이며 별도의 채팅 GUI는 없습니다.

- [포터블 사용 설명](pcucp-next/packaging/PORTABLE.md)
- [배포 구조와 빌드·검증](docs/portable-distribution.md)
- [소스 개발과 Windows 준비](pcucp-next/README.md)
- [Pi 연결 계약](integrations/pi/README.md)
- [개발 방향](docs/core-modernization.md)

## 구현 범위

| 기능 | 실행 위치 |
| --- | --- |
| JSONL 세션·명령 검증·관찰 ID·배치·시간 제한·창 대기 | Python |
| 창 목록·화면 캡처·UIA 트리·OCR·권한 진단 | C# |
| 포커스·클릭·더블클릭·Unicode 입력·단축키·스크롤 | C# + Python 검증/후속 관찰 |
| 공통 도구 스키마·이미지 전달·취소·세션 종료 | Python MCP/JSONL + 선택적 Pi TypeScript 어댑터 |
| 명시적 EXE 실행·관찰 대상의 정상 종료 요청 | Python 정책 + C# 프로세스/창 제어 |
| UIA Invoke/Value/Toggle/Selection/ExpandCollapse/Scroll | C# 패턴 + 관찰 참조 검증 |
| 64단계 선언형 워크플로·작업·폼·조건 대기·세션 기록 | Python |
| 메모리 내 창 OCR·텍스트 검색/결합·화면 차이 분석 | C# 캡처/OCR + Python 분석 |
| 선택적 루프백 CDP·DOM 탐색·입력·ProseMirror | Python, 시작 시 명시적으로 승인한 엔드포인트만 |
| 포터블 빌드·실행 진단 | Python |

`wait-window`는 제목과 선택 PID로 최대 10초 대기하고 여러 창이 맞으면 선택을 요구합니다.
더블클릭은 `click`에 `count: 2`를 전달합니다. 좌표·키·텍스트 입력에는 최신 관찰 ID가 필요하며 각 입력 후 새 화면을 반환합니다.
앱 실행·종료는 별도 수명 계약을 따르며 후속 `windows`/`observe`가 필요합니다.
성공 응답은 입력 전달과 후속 관찰을 뜻하며, 파일 저장 같은 최종 목표 달성을 자동 입증하지 않습니다.
짧은 배치는 최대 12단계, 선언형 워크플로는 최대 64단계/60초이며 첫 실패에서 중단합니다. 실패한 입력을 자동 재시도하지 않습니다. 폼은 각 필드마다 다시 관찰하고 정확히 하나의 UIA 대상만 허용합니다.

MCP 호스트는 위 소스 설치 후 `cucp mcp`를, 자체 브리지는 `cucp serve`를 자식 프로세스로 실행합니다.
기존 포터블의 `CUCP.exe serve`도 UTF-8 JSONL 연결을 지원합니다.
사람이 입력을 허용한 세션에만 `--allow-live-control` 시작 인자를 붙입니다.
기본 실행 경로에서 PowerShell·Node 서버·`dotnet run`·자동 빌드를 호출하지 않습니다.

## 검증과 제한

자동 검증은 Python/TypeScript 동작 테스트, C# 입력 ABI·좌표·권한·프로토콜 검사,
Windows 빌드, 실제 실행 파일을 다른 한글/공백 경로로 옮긴 후의 시작·통신 검사를 포함합니다.
**실제 데스크톱 앱 조작, IME, 혼합 DPI, 관리자 앱 입력은 별도 수동 검증이 필요합니다.**
`doctor` 통과가 GUI 호환성 통과를 의미하지 않습니다.

관리자 앱 입력은 사람이 호스트를 관리자 권한으로 시작하고 UAC를 승인하는 방식입니다.
CUCP는 시작한 부모 프로세스의 권한을 이어받으며 분리된 권한 브로커는 없습니다.
호스트 전체를 승격하면 그 호스트의 다른 도구도 함께 승격될 수 있습니다. 선택적 `python pcucp-next/packaging/start_pi.py --elevated`를 쓰는 경우에는 Pi 전체가 이 범위에 해당합니다.
SYSTEM/PPL·UAC 보안 데스크톱·로그인 화면 제어는 지원하지 않습니다.
같은 창의 제한된 드래그와 관찰에 묶인 UIA 패턴 실행은 구현되어 있습니다. 실제 IME 조합·클립보드 워크플로·이벤트 기반 관찰·CDP의 나머지 앱별 호환성·선택적 비전 통합의 전체 이전은 아직 진행 중입니다.
현재 배포는 Windows x64 미리보기이며 코드 서명·설치기·자동 업데이트가 없습니다.

## 기존 PowerShell 코드

`scripts/`, Codex 플러그인/스킬 및 앱별 매크로는 **레거시 호환 소스**입니다. 설치는 `python install.py`를 사용합니다. 기본 설치 대상은 기존 매크로를 제공하는 레거시 백엔드이며, 아직 PowerShell 래퍼가 필요합니다.
새 배포본에 포함하지 않으며, MCP/JSONL 코어와 Pi 어댑터는 이를 자동으로 호출하지 않습니다.
기존 설치기는 레거시를 설치합니다. 새 MCP 변경은 위 소스 안내를, 기존 배포 버전은 0.4.0 포터블 안내를 사용하세요.
소스 개발자가 필요할 때만 `python -m pcucp_cli legacy -- ...`로 명시적으로 호출할 수 있습니다. 기존 래퍼의 네이티브 호출과 보조 서버도 이제 Python/C#을 사용하므로, 새 소스 체크아웃에서는 Python 3.10+와 .NET 8 SDK를 준비하고 **같은 커밋에서 아래 구성 요소를 사전 빌드**한 뒤 설치하세요. Framework 구성 요소의 실행에는 Windows의 .NET Framework 4.8이 필요합니다.

```text
python pcucp-next/packaging/publish_native.py
python pcucp-next/packaging/publish_legacy_interop.py
python pcucp-next/packaging/publish_legacy_images.py
python pcucp-next/packaging/publish_legacy_desktop.py
python pcucp-next/packaging/publish_legacy_syntax.py
python pcucp-next/packaging/publish_legacy_helper.py
python install.py
```

이 단계는 Win32 호환 DLL, OCR·이미지 DLL, 네이티브 실행 파일, 읽기 전용 문법 파서와 보조 서버 패키지를 고정된 소스 경로에 게시합니다. 기존 Node CLI가 필요한 명령은 계속 `CUCP_CLI_PATH`로 원본 `cli.mjs`를 지정해야 합니다. 설치기는 이 구성 요소를 자동으로 빌드하지 않으며, 실행 중 C# 코드를 컴파일하거나 누락 DLL을 내려받는 대체 경로도 없습니다.

GitHub 언어 비율에는 보존 중인 레거시 코드가 계속 포함됩니다. 언어 비율을 바꾸려고
통계에서 숨기거나 미이전 기능을 삭제하지 않았습니다. 전체 레거시 기능 포팅은 완료되지 않았습니다.
이후 범용 기능의 대체와 Windows 회귀 검증을 거쳐 레거시 정리를 진행합니다.

## 개발자 검증

```text
python -m unittest discover -s tests/python -v
```

Pi 연결부는 `integrations/pi`에서 `npm ci --ignore-scripts`, `npm run typecheck`,
`npm test`, `npm run test:engine`으로 확인합니다. 배포본 빌드는 [빌드 안내](docs/portable-distribution.md)를 따릅니다.

MIT License. [LICENSE](LICENSE)
