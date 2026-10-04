# PCUCP Next — 범용 Computer Use 실행 코어

> **범용 호스트 연결 · 로컬 개선안:** Pi 없이도 stdio MCP 또는 JSONL로 연결할 수 있습니다. [호스트 공통 설치·권한·프로토콜](../docs/host-neutral-setup.md), [Python/C# 이전 범위와 남은 기능](../docs/migration-matrix.md)을 참고하세요. 새 MCP·앱 수명 기능은 소스 변경이며 기존 배포 ZIP에는 아직 없습니다.

Computer Use가 없는 AI 호스트에 **로컬 Windows 관찰·입력 기능**을 연결합니다. 모델 선택, API 자격 증명과 대화 관리는 호스트가 담당합니다. CUCP는 별도 LLM을 호출하지 않습니다.

이번 구현은 **상주 Python JSONL 세션 + 세션 동안 재사용하는 C# 네이티브 프로세스**입니다. C#은 첫 네이티브 요청 때 시작됩니다. 별도 관리자 브로커와 UIA 참조 캐시는 후속 단계입니다. 기존 PowerShell 명령을 모두 이전한 버전은 아니며, 신규 Pi 도구는 레거시 실행기로 자동 우회하지 않습니다.

개발 범위와 후속 단계는 [개발 방향](../docs/core-modernization.md), 선택적 Pi 어댑터 계약은 [Pi 연결 안내](../integrations/pi/README.md)를 참고하세요.

상주 실행기의 오류 처리와 검증은 [상주 세션 계약](../docs/resident-native-session.md)을 참고하세요.

## 구성과 현재 기능

| 구성 | 역할 |
| --- | --- |
| `python/pcucp_cli` | 세션, 관찰 ID, 명령 분류, 순차 실행, 배치 중단, 시간 제한, 오류 전달 |
| `dotnet/PcuCp.NativeHost` | Win32/UIA, 화면 캡처, 입력, HWND/PID·포커스·좌표·권한 검사 |
| `../integrations/pi` | Pi 도구 등록, 실제 이미지 결과, Python 프로세스 수명과 취소 처리 |
| `powershell` | 게시·실행 준비와 선택적 관리자 실행 |
| `../scripts/cucp.ps1` | 기존 PowerShell 기능의 별도 호환 경로 |

범용 MCP 실행은 `python -u -m pcucp_cli mcp`, 기존 JSONL 실행은 `python -u -m pcucp_cli serve`입니다. 두 방식 모두 기본 읽기 전용이며 Pi는 필요하지 않습니다. Python 모듈 설치 또는 PYTHONPATH 설정, C# 네이티브 게시 준비는 [호스트 공통 설치](../docs/host-neutral-setup.md)를 따릅니다.

새 세션 명령은 `app-launch`, `app-close`, `windows`, `observe`, `screenshot`, `uia-tree`, `privileges`, `capabilities`, `history`, `focus`, `click`, `type`, `key`, `scroll`, `batch`입니다. `find-label`, `ocr-image`, `ocr-find-text`, `task-plan` 등의 기존 Python CLI도 남아 있습니다. 이 CLI 전체가 Pi 도구로 노출되는 것은 아닙니다.

- `observe`는 지정 창의 화면 이미지와 제한된 UIA 트리를 수집합니다. UIA 결과는 관찰 데이터이며, 지속되는 요소 참조로 직접 실행하는 기능은 아직 없습니다.
- `click`은 `count: 2`로 더블클릭을 지원합니다. `wait-window`는 제목과 선택 PID로 최대 10초 대기하며 다중 후보는 오류와 함께 반환합니다.
- `click`, `type`, `key`, `scroll`은 최신 `observation_id`를 요구합니다. `focus`는 명시적인 `hwnd`와 `pid`를 요구합니다.
- 각 조작 이후 새 화면을 수집합니다. 이는 후속 관찰이며, 입력값 저장·파일 저장 같은 작업 목표를 자동으로 입증하지 않습니다.
- 배치는 최대 12단계이며 첫 실패에서 중단합니다. 미실행 단계는 `skipped`로 반환합니다.
- 드래그, 지속 키 누르기, 확대 영역 관찰, UIA 요소 참조 실행, 이벤트 기반 화면 감시는 이번 구현 범위에 없습니다.

## 설치 없는 포터블 실행 (0.4.0)

새 사용자 배포는 [포터블 안내](packaging/PORTABLE.md)를 따릅니다. Windows x64 ZIP에는
Python 인터프리터와 C#/.NET 런타임이 함께 들어가며 CUCP용 Node 서버가 없습니다.
폴더 전체를 유지하고 `CUCP.exe doctor --json`으로 시작을 확인하세요.
Pi는 기존 호스트를 사용하며 `pi --extension .\integrations\pi\src\index.ts`로 연결합니다.

빌드·CI·체크섬·검증 범위는 [배포 문서](../docs/portable-distribution.md)에 있습니다.
배포본에서는 `legacy` 명령을 제공하지 않습니다. 다음 준비 절차는 **소스 개발자용**입니다.

## Windows 소스 개발 준비

저장소 루트에서 실행합니다. Windows 대화형 데스크톱, Python 3.10 이상, 최초 게시용 .NET 8 SDK가 필요합니다. Pi 어댑터에는 Node.js 22.19 이상과 Pi가 필요합니다. 개발 의존성은 `@earendil-works/pi-coding-agent` / `@earendil-works/pi-ai` **0.87.1**에 맞춰져 있습니다.

```powershell
$cucpRoot = (Get-Location).Path
python .\pcucp-next\packaging\publish_native.py
$env:CUCP_NATIVE_HOST = Join-Path $cucpRoot 'pcucp-next\bin\native\PcuCp.NativeHost.exe'
$env:PYTHONPATH = Join-Path $cucpRoot 'pcucp-next\python'
python -m pcucp_cli windows --json
```

게시 스크립트의 기본 대상은 `win-x64`입니다. ARM64 Windows에서는 `-Runtime win-arm64`를 사용합니다. 게시 결과는 self-contained이며, Python `serve`에서는 같은 네이티브 프로세스를 재사용합니다. 개별 관찰 CLI는 일회 실행을 유지합니다. 정상 실행 경로에서 `dotnet run`이나 재빌드를 호출하지 않습니다.

`CUCP_NATIVE_HOST`는 절대 실행 파일 경로로 지정합니다. 설정하지 않으면 `pcucp-next/bin/native/PcuCp.NativeHost.exe`를 찾습니다. 직접 게시한 DLL 경로도 지원하지만 이 경우 해당 런타임의 `dotnet` 실행 파일이 필요합니다.

## Pi에서 시작

가장 간단한 실행은 저장소 루트에서 다음과 같습니다.

```powershell
python .\pcucp-next\packaging\start_pi.py
```

Python 경로를 별도로 지정하려면 `-PythonExe 'C:\path\to\python.exe'`를 사용합니다. Pi 실행 파일을 선택하려면 `-PiExecutable`을 사용합니다. 첫 실행기는 임의 Pi 인자를 전달하지 않습니다.

직접 Pi에 확장을 로드할 수도 있습니다.

```powershell
pi --extension .\integrations\pi\src\index.ts
```

로컬 패키지로 등록하려면 다음을 한 번 실행합니다. 저장소 전체를 유지해야 하며 `index.ts`만 복사하면 안 됩니다.

```powershell
pi install .\integrations\pi
```

확장은 자체 위치에서 포터블 폴더 또는 저장소를 찾습니다. `CUCP_EXECUTABLE`은 별도 위치의 CUCP.exe 절대 경로를 선택합니다. 명시한 실행 파일 실패 시 Python으로 자동 전환하지 않습니다. 필요하면 `CUCP_ROOT`로 다른 저장소 루트를, `CUCP_PYTHON`으로 Python 실행 파일 경로 하나를 지정합니다. 확장이 Python의 `PYTHONPATH`를 준비하므로 Pi 사용 시 직접 설정할 필요는 없습니다.

Pi 세션에서 조작은 기본적으로 꺼져 있습니다.

```text
/computer status
/computer on
/computer off
```

사용자가 `/computer on`을 실행한 뒤 `cucp_windows` → `cucp_observe` → `cucp_action` 순으로 사용할 수 있습니다. 모드 변경은 엔진을 재시작하고 기존 관찰 ID를 무효화합니다. 모델의 도구 인자로 조작 권한을 켤 수는 없습니다. 화면 이해에는 Pi에 연결한 모델의 이미지 입력 지원이 필요합니다.

## 관리자 창과 권한

관리자 권한으로 실행된 일반 앱을 다룰 때는 사람이 선택적으로 다음 실행 방식을 사용할 수 있습니다.

```powershell
python .\pcucp-next\packaging\start_pi.py --elevated
```

Windows UAC 승인은 사람이 처리합니다. 현재 방식은 **Pi와 로드된 확장·도구 전체를 관리자 권한으로 시작**합니다. 좁은 권한의 CUCP 브로커만 승격하는 구조는 아직 구현하지 않았습니다. 관리자 모드에서도 `/computer on`은 별도로 필요합니다.

`cucp_privileges`에 대상 `pid`를 전달하면 현재 네이티브 프로세스와 대상의 무결성 수준을 비교할 수 있습니다. 비교 통과는 입력 수용 보장이 아닙니다. SYSTEM·보호 프로세스(PPL)보다 높은 보편적 조작 권한, UAC 보안 데스크톱 조작, 로그인 화면 제어를 제공하지 않습니다. `/computer off`는 CUCP 도구의 제어이며 Pi의 bash나 다른 확장을 격리하는 OS 샌드박스가 아닙니다.

## 직접 연결하는 호스트의 JSONL 진입점

```powershell
python -u -m pcucp_cli serve
```

호스트가 실제 조작을 허용한 세션만 `serve --allow-live-control`로 시작합니다. 한 줄에 요청 JSON 하나를 쓰고, 같은 ID의 응답 한 줄을 읽습니다. 로그를 프로토콜 stdout에 섞지 않습니다.

```json
{"schema":"cucp.request/v1","id":"caps-1","command":"capabilities","args":{}}
```

`cucp.response/v1`에는 `id`, `command`, `status`, `data`, `errors`, `duration_ms`가 들어갑니다. 요청 인자와 좌표 의미, 실패 처리 예시는 [개발 방향의 계약 설명](../docs/core-modernization.md#현재-연결-계약)을 참고하세요.

## 검증

현재 통과 항목과 남은 검증은 [검증 기록](../docs/core-validation.md)에 구분해 두었습니다.

다음은 저장소 루트 기준의 검증 명령입니다.

```powershell
$env:PYTHONPATH = Join-Path (Get-Location).Path 'pcucp-next/python'
python -m unittest discover -s tests/python -v
powershell -NoProfile -Command "Invoke-Pester .\tests\cucp.LegacyRegression.Tests.ps1"
dotnet run --project .\pcucp-next\dotnet\PcuCp.NativeHost.ContractTests\PcuCp.NativeHost.ContractTests.csproj
```

Pi 어댑터 검증은 `integrations/pi`에서 실행합니다.

```powershell
npm ci --ignore-scripts
npm run typecheck
npm test
npm run test:engine
```

이번 개발 환경에서 확인한 범위는 다음과 같습니다.

| 검증 | 상태 |
| --- | --- |
| Python 계약·네이티브 전송 테스트 | 통과 |
| Pi 실제 패키지 타입 검사·Node 프로세스 테스트·Python 엔진 연결 | 통과 |
| C# 전체 소스, 실제 .NET 8/WPF/Windows SDK 참조를 사용한 Roslyn 컴파일 | 경고를 오류로 처리하여 통과 |
| 네이티브 ABI·좌표 계산·인자 계약 검사 | 통과 |
| Windows CI .NET 빌드·상주 네이티브 전송 | 빌드 및 전송 검사 12개 통과 |
| 레거시 Pester 5 회귀 검사 | Windows CI에서 14개 통과 |
| Windows self-contained publish·포터블 시작·Pi EXE 연결 | `windows-portable` CI에서 검증 |
| 실제 Windows GUI 조작 | 미검증 |

로컬 Linux 환경의 MSBuild 제한은 남아 있지만 [Windows CI](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/36216294498)에서 표준 .NET 빌드와 실제 네이티브 프로세스 통신을 확인했습니다. 0.4.0 게시 검증은 별도 `windows-portable` 작업이 담당합니다. 실행 파일 시작 검사는 GUI 입력 검증을 대신하지 않습니다. Python·Node의 모의/프로세스 통합 검증 또한 실제 Windows GUI 작동의 증거와 구분합니다. **이번 개발 환경에서는 Windows 화면 캡처·실제 입력·한글 IME·UAC·다중 모니터를 실행 검증하지 못했습니다.** 기존 `pcucp-next.Fast.Tests.ps1`은 일부 Windows 기능을 다루는 별도 테스트이며 새 계약 전체의 합격 기준을 대신하지 않습니다.

Local stage two additionally supplies observation-bound `uia-find`, `uia-invoke`,
`uia-set-value`, bounded `drag`, and a native parent-liveness watchdog. See the
[host-neutral contracts and limitations](../docs/host-neutral-setup.md#observation-bound-uia-and-input-additions-local-stage-two).
Rebuild native and Python together; existing 0.4.0 downloads lack these additions.
