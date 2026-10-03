"""One routing/effect registry. Describing a command does not authorize it."""
from dataclasses import asdict, dataclass

@dataclass(frozen=True)
class CommandSpec:
    name: str
    effect: str = "read"
    route: str = "python-router"
    available_in_engine: bool = True

_CORE = [CommandSpec(n) for n in ("capabilities", "history", "observe", "screenshot", "wait-window", "uia-find", "ocr-window", "ocr-find", "ocr-uia-fuse", "screenshot-diff")]
_CORE += [CommandSpec(n, route="dotnet-native-host") for n in ("windows", "privileges", "uia-tree")]
_CORE += [CommandSpec(n, "write", "dotnet-native-host") for n in ("focus", "click", "drag", "type", "key", "scroll", "app-close", "app-launch", "uia-invoke", "uia-set-value", "uia-toggle", "uia-select", "uia-expand-collapse", "uia-scroll")]
_CORE += [CommandSpec(n) for n in ("workflow-plan", "task-build", "form-plan", "watch", "app-profile", "recovery-plan", "record-read")]
_CORE += [CommandSpec(n, "conditional") for n in ("batch", "workflow-run", "task-run", "form-run", "record-start", "record-stop")]
_CORE += [CommandSpec(n, route="python-cdp-adapter") for n in ("cdp-detect", "cdp-observe", "cdp-query", "cdp-smart-find", "cdp-smart-type-find", "cdp-deep-find")]
_CORE += [CommandSpec(n, "write", "python-cdp-adapter") for n in ("cdp-click", "cdp-smart-click", "cdp-type", "cdp-smart-type", "cdp-prosemirror-insert", "cdp-eval")]
COMMANDS = {s.name: s for s in _CORE}
for name in ("version", "plan", "task-plan", "find-label", "ocr-find-text"):
    COMMANDS[name] = CommandSpec(name, available_in_engine=False)
COMMANDS["ocr-image"] = CommandSpec("ocr-image", route="dotnet-native-host", available_in_engine=False)

def normalize_command(command: str) -> str:
    return command.strip().lower().replace("_", "-")

def capabilities() -> list[dict]:
    return [asdict(spec) for spec in _CORE]
