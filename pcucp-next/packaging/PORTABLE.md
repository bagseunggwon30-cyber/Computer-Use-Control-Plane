# CUCP portable 0.4.0 — Windows x64

압축을 풀고 폴더 전체를 유지하세요. CUCP용 Python, Node.js, .NET을 별도로 설치할 필요가 없습니다.
`CUCP.exe`, `_internal/`, `native/`, `integrations/`를 함께 보관하세요.
Pi 자체와 AI 모델은 포함하지 않습니다. Windows 10 2004 이상/Windows 11 x64가 대상입니다.

## 실행 확인

터미널에서 압축을 푼 폴더로 이동한 뒤 실행합니다. cmd와 PowerShell 모두 가능합니다.

```text
.\CUCP.exe version --json
.\CUCP.exe doctor --json
```

`doctor`는 두 런타임의 시작 여부와 버전을 확인하며 GUI 입력을 보내지 않습니다.
정상 결과가 실제 앱 입력·캡처·관리자 창 호환성까지 보장하지는 않습니다.
이 프로그램은 호스트가 실행하는 CLI/JSONL 엔진이며 별도의 채팅 GUI는 없습니다.

## Pi 연결

이미 사용하는 Pi에서 다음 확장을 로드하세요. 확장이 같은 폴더의 CUCP.exe를 자동으로 찾습니다.

```text
pi --extension .\integrations\pi\src\index.ts
```

Pi에서 `/computer status`로 확인하고, 실제 입력이 필요할 때 사람이 `/computer on`을 실행합니다.
`/computer off`는 CUCP 입력을 끕니다. `cucp_windows` → `cucp_observe` → `cucp_action` 순으로 사용합니다.
창 대기는 `cucp_wait_window`, 더블클릭은 `click`의 `count: 2`입니다.
연결부는 Pi의 실행 환경을 사용하며 CUCP용 Node 서버를 별도로 시작하지 않습니다.

확장을 다른 위치에 설치했다면 호스트 환경의 `CUCP_EXECUTABLE`에 `CUCP.exe` 절대 경로를 지정하세요.
실행 파일 경로에 인자를 섞지 마세요. 명시한 경로가 잘못되면 Python으로 자동 전환하지 않습니다.

## 다른 호스트에 탑재

실행 파일과 인자를 구분하여 `CUCP.exe serve`를 자식 프로세스로 실행하세요.
stdin/stdout으로 UTF-8 JSONL 요청/응답을 주고받습니다. 예:

```json
{"schema":"cucp.request/v1","id":"check-1","command":"capabilities","args":{}}
```

사람이 입력을 허용한 세션에만 시작 인자 `--allow-live-control`을 추가합니다.
타임아웃·취소 후 입력을 자동 재시도하지 마세요. 프로세스를 종료하고 새 관찰부터 시작하세요.

## 권한과 현재 제한

일반 관리자 앱을 제어하려면 호스트를 사람이 관리자 권한으로 시작하고 UAC를 승인해야 합니다.
현재는 Pi 전체와 그 도구가 함께 승격됩니다. 분리된 권한 브로커는 아직 없습니다.
SYSTEM/PPL·UAC 보안 데스크톱·로그인 화면 조작은 지원하지 않습니다.
실제 GUI, 혼합 DPI/다중 모니터, IME, 관리자 앱 입력 검증은 별도로 필요합니다.

기존 PowerShell 스크립트, 앱별 매크로, 개발 SDK, Pi 및 모델은 이 배포본에 포함하지 않습니다.
레거시와 기능이 모두 동일하지는 않습니다. 드래그·UIA 요소 직접 실행 등은 후속 개발 범위입니다.
이 미리보기 배포본은 코드 서명이 없습니다. `SHA256SUMS.txt`와 ZIP 옆의 체크섬을 제공하지만
체크섬은 배포자의 서명을 대신하지 않습니다. `licenses/`는 함께 배포해야 합니다.
