"""One routing/effect registry. Describing a command does not authorize it."""
from dataclasses import asdict, dataclass

@dataclass(frozen=True)
class CommandSpec:
    name: str
    effect: str = "read"
    route: str = "python-router"
    available_in_engine: bool = True

_CORE = [CommandSpec(n) for n in ("capabilities", "history", "observe", "screenshot")]
_CORE += [CommandSpec(n, route="dotnet-native-host") for n in ("windows", "privileges", "uia-tree")]
_CORE += [CommandSpec(n, "write", "dotnet-native-host") for n in ("focus", "click", "type", "key", "scroll")]
_CORE += [CommandSpec("batch", "conditional")]
COMMANDS = {s.name: s for s in _CORE}
for name in ("version", "plan", "task-plan", "find-label", "ocr-find-text"):
    COMMANDS[name] = CommandSpec(name, available_in_engine=False)
COMMANDS["ocr-image"] = CommandSpec("ocr-image", route="dotnet-native-host", available_in_engine=False)
for name in ("app-launch app-close with-app focus-window focus-verify click-label double-click-label right-click-label click-id click-point fill-label shortcut shortcut-native type-native uia-click-label uia-invoke uia-set-value uia-toggle safe-type smart-click form-run icon-click vision-click vision-click-precise click-and-verify click-and-verify-screen ocr-click ocr-uia-invoke cdp-type cdp-click cdp-eval cdp-smart-click cdp-smart-type auto-do goal clipboard mouse-verify cdp-prosemirror-insert ime-paste safe-type-ime recovery-run task-run workflow-run process registry").split():
    COMMANDS[name] = CommandSpec(name, "write", "legacy-powershell", False)

def normalize_command(command: str) -> str:
    return command.strip().lower().replace("_", "-")

def capabilities() -> list[dict]:
    return [asdict(spec) for spec in _CORE]
