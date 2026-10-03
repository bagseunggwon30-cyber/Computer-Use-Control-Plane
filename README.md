# CUCP — Computer Use Control Plane

Windows 컴퓨터 사용 기능을 AI 호스트에 연결하는 Python/C# 엔진입니다. Python이 MCP·JSONL 세션, 워크플로, OCR 처리, CDP, 설치·빌드를 맡고 C#이 Windows 캡처·UIA·입력·권한 검사를 맡습니다. Pi는 선택적인 TypeScript 어댑터입니다.

**0.5.0은 범용 코어 기준의 전환안입니다. 기존 PowerShell 매크로 CLI는 종료하며 완전한 호환 포팅을 주장하지 않습니다.** [이전 범위와 종료 기능](docs/migration-matrix.md)을 먼저 확인하세요. 원본은 정상 Git 이력과 `migration/python-csharp-runtime` 브랜치에 남아 있습니다. 언어 통계 제외 설정은 사용하지 않습니다.

## 시작

Windows, Python 3.10+, 최초 게시용 .NET 8 SDK를 준비하고 저장소 루트에서 실행합니다.

```text
python pcucp-next/packaging/publish_native.py
python pcucp-next/python/run_source.py doctor --json
python pcucp-next/python/run_source.py mcp
```

MCP 호스트에는 마지막 명령을 연결합니다. 자체 브리지는 `serve`의 UTF-8 JSONL을 사용합니다. 기본 읽기 전용입니다. 사용자가 승인한 세션만 시작 인자 `--allow-live-control`로 입력을 허용합니다. 모델·계정·API 키 관리는 호스트가 담당합니다.

## 기능과 설치

창 목록·화면 캡처·UIA 패턴·관찰에 묶인 입력·명시적 EXE 실행과 정상 종료, 같은 캡처의 OCR·OCR/UIA 결합·PNG 비교, 검증된 JSON 워크플로·폼·작업·watch·메모리 기록, 선택적 loopback CDP를 지원합니다. 실제 명령과 스키마는 `capabilities`에서 확인합니다.

```text
python install.py --bin-dir C:\chosen\bin
python install.py --bin-dir C:\chosen\bin --apply
python pcucp-next/packaging/start_pi.py
```

설치기는 먼저 계획을 출력합니다. `--apply`가 있어야 해시로 소유권을 확인한 실행기를 씁니다. PATH·레지스트리·시작 프로그램은 수정하지 않습니다. Pi 조작 모드는 사람이 `/computer on`으로 켭니다. `start_pi.py --elevated`는 정상 UAC 승인을 통해 Pi 전체를 승격합니다.

[호스트 연결](docs/host-neutral-setup.md) · [명령](references/command-reference.md) · [포터블 빌드](docs/portable-distribution.md) · [검증](docs/core-validation.md)

## 검증과 한계

```text
python -m unittest discover -s tests/python -v
dotnet run --project pcucp-next/dotnet/PcuCp.NativeHost.ContractTests -c Release
```

코드·프로토콜·설치 검사와 실제 앱 사용 검증은 다릅니다. IME 조합, 혼합 DPI, UIA 공급자, 관리자 앱 및 실제 UAC 승인은 수동 검증이 필요합니다. 입력 전송 성공은 저장 같은 최종 목적의 성공을 증명하지 않습니다. SYSTEM/PPL·UAC 보안 데스크톱·로그인 화면은 지원하지 않습니다.

기존 0.4.0 ZIP에는 이 변경이 없습니다. [CUCP core Actions](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/workflows/core.yml)의 해당 커밋으로 새로 만든 포터블을 사용하세요.

MIT License. [LICENSE](LICENSE)
