# 상주 네이티브 실행기 — 0.3.0

Pi → Python `serve` → C# `serve` 구조로 한 세션 동안 네이티브 프로세스를 재사용한다. 첫 실제 네이티브 요청 전에는 C# 프로세스를 띄우지 않는다. `capabilities`만 조회할 때는 Windows 실행 파일이 없어도 동작한다. 별도 관리자 서비스나 UIA 요소 캐시는 이번 구현에 포함하지 않는다.

## 수명과 권한

- Python 세션이 자식 C# 프로세스 하나를 소유하고 요청을 순서대로 보낸다.
- C# 시작 인자 `serve --allow-live-control`이 세션 권한을 결정한다. 읽기 전용으로 시작한 프로세스는 요청에 같은 플래그를 넣어도 입력을 허용하지 않는다.
- 요청 ID는 연결마다 양수이며 단조 증가한다. 중복·역순 ID는 연결을 종료하고 실행하지 않는다.
- 새 관찰·입력은 같은 프로세스를 쓰지만 매번 HWND/PID·전경·좌표·권한을 다시 검사한다. 상주가 관찰 ID 유효기간을 늘리지 않는다.
- 시간초과·깨진 응답·프로세스 종료 뒤에는 해당 연결을 재사용하거나 자동 재생성하지 않는다. 입력의 실행 여부가 불확실할 수 있으므로 호스트는 재관찰해야 한다.
- Pi에서 `/computer off` 후 `/computer on`으로 Python 세션을 명시적으로 다시 시작한다. 권한 변경은 기존 관찰을 무효화한다.
- 정상 EOF, 취소, 세션 종료 때 자식 프로세스 트리를 종료한다. Windows Job Object를 이용한 부모 비정상 종료 추적은 아직 후속 작업이다.

통신은 부모가 전달한 stdin/stdout 파이프만 사용한다. 포트를 열거나 별도 네트워크 API를 만들지 않는다. 관리자 실행 방식은 기존과 동일하게 Pi 전체 승격이며, 이 변경으로 관리자 범위가 확장되지는 않는다.

## 네이티브 내부 프로토콜

```json
{"schema":"pcucp.native.request/v1","id":1,"command":"windows","args":[]}
```

```json
{"schema":"pcucp.native.response/v1","id":1,"command":"windows","exit_code":0,"payload":{"schema":"pcucp.observation/v1","status":"ok","kind":"windows","data":{"windows":[],"count":0},"errors":[]}}
```

기존 네이티브 응답을 `payload`에 보존한다. 이는 Pi가 보는 `cucp.response/v1`과 다른 내부 프로토콜이다. 한 줄은 UTF-8 JSON이며 요청 한도는 128 KiB, 응답 한도는 Python에서 32 MiB다. 표준 오류는 프로세스당 64 KiB로 제한한다. 잘못된 프레임·중복 필드·잘못된 UTF-8·권한 변경 요청은 연결을 끝낸다. EOF로 끝난 미완성 프레임은 실행하지 않는다.

`python -m pcucp_cli windows` 같은 개별 CLI와 네이티브 일회 실행은 그대로 유지한다. 상주 통신 실패 시 일회 실행으로 자동 전환하지 않는다.

## 검증

로컬 Linux 환경에서 Python 72개 테스트를 모두 통과했다. 이 중 실제 빌드한 C# 프로세스와 `version`을 두 번 교환해 PID가 유지되는지 검사하고, 읽기 전용 프로세스의 입력 요청이 OS 호출 전에 거부되는지 검사했다. 실제 데스크톱 입력은 실행하지 않았다.

추가 모의 프로세스 검사에는 요청 직렬화, 취소, 시간초과, 출력 크기 제한, 잘못된 응답, 부분 결과, 재전송·자동 재시작 금지가 포함된다. C# 전체 소스 컴파일과 12,199개 ABI·좌표·권한·프레임 계약 검사도 통과했다. 좌표 반복 검사가 포함된 수치이며 전체 작업 성공 횟수가 아니다.

실제 네이티브 전송 검사를 실행하려면 `CUCP_NATIVE_TEST_HOST`를 빌드한 DLL 또는 EXE의 절대 경로로 설정한다. DLL일 때는 .NET 런타임이 PATH에 있어야 한다.

```powershell
$env:PYTHONPATH = Join-Path (Get-Location).Path 'pcucp-next/python'
$env:CUCP_NATIVE_TEST_HOST = (Resolve-Path 'pcucp-next/dotnet/PcuCp.NativeHost/bin/Release/net8.0-windows10.0.19041.0/PcuCp.NativeHost.dll').Path
python -m unittest discover -s tests/python -p test_native_session.py -v
```

0.2.0의 첫 GitHub 실행에서는 Windows C# 빌드·네이티브 계약 검사가 통과했다. Pester 4 설치는 기존 Pester 5와의 인증서 차이로 실패했다. 이번 변경은 회귀 테스트를 Pester 5 실행 단계에 맞추고, 설치된 Pester 5를 사용한다. 서명 검사를 끄지 않는다.

[Windows GitHub 검사](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/36216294498)에서도 표준 .NET 빌드, 네이티브 계약 12,199개, 상주 전송 테스트 12개, Pester 5 회귀 테스트 14개가 모두 통과했다. Linux 작업도 통과했다.

Windows 실제 화면·UIA·입력·한글·관리자 앱·혼합 DPI 검증과 지연 측정은 별도 필요하다. 상주 구조만으로 모든 앱 동작이나 속도 향상을 보장하지 않는다.
