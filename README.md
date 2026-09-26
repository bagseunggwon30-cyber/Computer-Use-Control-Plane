# CUCP — Computer Use Control Plane

CUCP는 Computer Use가 없는 AI 호스트에 Windows 관찰·입력 기능을 연결하는 실행 엔진입니다.
**Python 본체 + C# Windows 제어부 + 최소 TypeScript Pi 연결부**를 사용합니다.
모델·API 키·대화 관리는 호스트가 담당합니다. 앱별 확장 개발은 종료하고 범용 코어에 집중합니다.

## 시작하기

[GitHub Actions의 CUCP core](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/workflows/core.yml)
에서 해당 커밋의 성공한 `windows-portable` 작업이 올린 **CUCP-0.4.0-win-x64** 아티팩트를 받습니다.
안의 ZIP을 풀고 폴더 전체를 유지하세요. CUCP용 Python·Node.js·.NET의 별도 설치가 필요 없습니다.
Pi와 모델은 포함하지 않으며, Pi는 이미 사용하는 호스트의 설치 요건을 따릅니다.

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
| 도구 등록·이미지 전달·취소·세션 종료 | Pi TypeScript 연결부 |
| 포터블 빌드·실행 진단 | Python |

`wait-window`는 제목과 선택 PID로 최대 10초 대기하고 여러 창이 맞으면 선택을 요구합니다.
더블클릭은 `click`에 `count: 2`를 전달합니다. 입력에는 최신 관찰 ID가 필요하며 각 조작 후 새 화면을 반환합니다.
성공 응답은 입력 전달과 후속 관찰을 뜻하며, 파일 저장 같은 최종 목표 달성을 자동 입증하지 않습니다.
배치는 최대 12단계이며 첫 실패에서 중단합니다. 실패한 입력을 자동 재시도하지 않습니다.

다른 호스트는 `CUCP.exe serve`를 자식 프로세스로 실행하여 UTF-8 JSONL을 주고받습니다.
사람이 입력을 허용한 세션에만 `--allow-live-control` 시작 인자를 붙입니다.
기본 실행 경로에서 PowerShell·Node 서버·`dotnet run`·자동 빌드를 호출하지 않습니다.

## 검증과 제한

자동 검증은 Python/TypeScript 동작 테스트, C# 입력 ABI·좌표·권한·프로토콜 검사,
Windows 빌드, 실제 실행 파일을 다른 한글/공백 경로로 옮긴 후의 시작·통신 검사를 포함합니다.
**실제 데스크톱 앱 조작, IME, 혼합 DPI, 관리자 앱 입력은 별도 수동 검증이 필요합니다.**
`doctor` 통과가 GUI 호환성 통과를 의미하지 않습니다.

관리자 앱 입력은 사람이 호스트를 관리자 권한으로 시작하고 UAC를 승인하는 방식입니다.
현재는 Pi 전체와 도구가 함께 승격되며 분리된 권한 브로커는 없습니다.
SYSTEM/PPL·UAC 보안 데스크톱·로그인 화면 제어는 지원하지 않습니다.
드래그·UIA 요소 참조 실행·이벤트 기반 관찰은 후속 개발 범위입니다.
현재 배포는 Windows x64 미리보기이며 코드 서명·설치기·자동 업데이트가 없습니다.

## 기존 PowerShell 코드

`scripts/`, 기존 `install.ps1`, Codex 플러그인/스킬 및 앱별 매크로는 **레거시 호환 소스**입니다.
새 배포본에 포함하지 않으며, 새 Pi 도구가 자동으로 호출하지 않습니다.
기존 설치기는 레거시를 설치하므로 새 코어는 위 포터블 안내를 사용하세요.
소스 개발자가 필요할 때만 `python -m pcucp_cli legacy -- ...`로 명시적으로 호출할 수 있습니다.

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
