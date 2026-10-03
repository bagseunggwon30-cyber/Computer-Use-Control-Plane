"""Frozen legacy routing facts, never executable dispatch or authorization.

This source-only checkpoint describes the retained PowerShell entry point, not
modern engine capabilities. A resolved handler is an inert name. Consumers must
use their own closed implementation allowlist and retain all authority gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .legacy_cdp_contract import _ps_equal

SCHEMA = "cucp.legacy-dispatch-contract/v1"
CONTRACT_PATH = Path(__file__).resolve().parents[3] / "docs/legacy-dispatch-contract.json"
# Deliberately updated only with a reviewed source/contract checkpoint.
CONTRACT_SHA256 = "0d1631e4196995e9e86780582a544827c9760058b8de5aa51e09635315ec9aa7"


class LegacyDispatchContractError(ValueError):
    """A frozen routing checkpoint or one of its production sources drifted."""


@dataclass(frozen=True)
class LegacyMacroRecord:
    clause_index: int
    name: str
    handler: str
    options: tuple[str, ...]
    implementation: str
    hint: str | None
    source_line: int


@dataclass(frozen=True)
class FrozenDispatchContract:
    clauses: tuple[LegacyMacroRecord, ...]
    direct_safety_macros: tuple[str, ...]
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class LegacyTopLevelRoute:
    kind: str
    argv: tuple[str, ...]
    rest: tuple[str, ...]
    macro: LegacyMacroRecord | None = None


def _canonical_text(raw: bytes) -> str:
    """UTF-8 BOM and checkout CRLF are transport, not source changes."""
    return raw.decode("utf-8-sig").replace("\r\n", "\n")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@lru_cache(maxsize=1)
def load_contract() -> FrozenDispatchContract:
    """Read the checked-in source-relative checkpoint once, without env/cwd lookup."""
    try:
        source = _canonical_text(CONTRACT_PATH.read_bytes())
    except (OSError, UnicodeError) as exc:
        raise LegacyDispatchContractError("Frozen legacy dispatch contract is unavailable") from exc
    if _digest(source) != CONTRACT_SHA256:
        raise LegacyDispatchContractError("Frozen legacy dispatch contract digest drift")
    data = json.loads(source)
    if data["schema"] != SCHEMA:
        raise LegacyDispatchContractError("Unsupported legacy dispatch contract schema")
    records = tuple(LegacyMacroRecord(
        clause_index=row["clause_index"], name=row["name"], handler=row["handler"],
        options=tuple(row["options"]), implementation=row["implementation"],
        hint=row["hint"], source_line=row["source_line"],
    ) for row in data["clauses"])
    return FrozenDispatchContract(records, tuple(data["direct_safety_macros"]), _freeze(data))


def resolve_macro(name: str) -> LegacyMacroRecord | None:
    """Case-insensitive ordered match, returning the first returning PS clause.

    No trimming, underscore conversion, argument evaluation, availability claim,
    or callable lookup is permitted here. Windows uses the existing invariant
    NLS comparator; its portable fallback is fixture evidence, not PS5.1 parity.
    """
    if not isinstance(name, str):
        raise TypeError("Legacy macro name must be a string")
    for record in load_contract().clauses:
        if _ps_equal(record.name, name):
            return record
    return None


def classify_top_level(argv: Sequence[str]) -> LegacyTopLevelRoute:
    """Describe routing after PowerShell parameter binding; do not run the route.

    A single leading separator is removed only from the already-bound array.
    This is not a replacement for powershell.exe -File's parameter binder.
    Macro safety and direct-CLI authorization still belong before invocation.
    """
    if not isinstance(argv, (list, tuple)) or any(type(arg) is not str for arg in argv):
        raise TypeError("Legacy argv must be a list or tuple of strings")
    args = tuple(argv)
    if args and args[0] == "--":
        args = args[1:]
    if not args:
        return LegacyTopLevelRoute("help", args, ())
    if _ps_equal(args[0], "version"):
        return LegacyTopLevelRoute("version", args, args[1:])
    if _ps_equal(args[0], "macro"):
        rest = args[2:]
        return LegacyTopLevelRoute("macro", args, rest,
                                   resolve_macro(args[1]) if len(args) > 1 else None)
    first_words = load_contract().metadata["top_level"]["json_capture_first_words"]
    kind = "cli_json" if any(_ps_equal(args[0], word) for word in first_words) else "cli_stream"
    return LegacyTopLevelRoute(kind, args, args)


def requires_direct_safety(name: str) -> bool:
    """List membership only. False never means read-only, implemented, or allowed."""
    if not isinstance(name, str):
        raise TypeError("Legacy macro name must be a string")
    return any(_ps_equal(name, entry) for entry in load_contract().direct_safety_macros)


def _function_extent(text: str, name: str) -> tuple[int, int, str]:
    """Read a declared PS function extent without executing or storing its code.

    This narrowly handles braces, quoted strings, here-strings, line/block
    comments and backtick escapes. It is not a general PowerShell parser. The
    independently pinned whole-file digest prevents an unrecognized edit from
    being accepted because of this navigation helper.
    """
    matches = list(re.finditer(r"^function\s+" + re.escape(name) + r"(?=\s|\{|\()", text, re.MULTILINE))
    if len(matches) != 1:
        raise LegacyDispatchContractError(f"Expected one function declaration: {name}")
    start = matches[0].start()
    i = text.index("{", matches[0].end())
    depth = 0
    quote = None
    here = None
    block_comment = False
    while i < len(text):
        char = text[i]
        if here is not None:
            if (i == 0 or text[i - 1] == "\n") and text.startswith(here + "@", i):
                i += 2
                here = None
            else:
                i += 1
            continue
        if block_comment:
            if text.startswith("#>", i):
                block_comment = False
                i += 2
            else:
                i += 1
            continue
        if quote is not None:
            if quote == '"' and char == "`":
                i += 2
                continue
            if char == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if text.startswith("<#", i):
            block_comment = True
            i += 2
            continue
        if char == "#":
            newline = text.find("\n", i)
            i = len(text) if newline < 0 else newline + 1
            continue
        if char == "@" and i + 1 < len(text) and text[i + 1] in "\"'":
            here = text[i + 1]
            i += 2
            continue
        if char in "\"'":
            quote = char
        elif char == "`":
            i += 2
            continue
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                return text.count("\n", 0, start) + 1, text.count("\n", 0, end) + 1, text[start:end]
        i += 1
    raise LegacyDispatchContractError(f"Unterminated function extent: {name}")


def assert_frozen_sources(root: Path | None = None) -> None:
    """Fail on production drift; no Git, PowerShell, services or live actions.

    Validation reads the caller-selected checkout (temporary fixtures in tests)
    against the separately pinned contract. It never regenerates a checkpoint.
    """
    root = Path(root) if root is not None else CONTRACT_PATH.parents[1]
    contract = load_contract().metadata
    texts = {}
    for source in contract["sources"]:
        path = root / source["path"]
        if path.is_symlink() or not path.is_file():
            raise LegacyDispatchContractError(f"Frozen source unavailable: {source['path']}")
        try:
            text = _canonical_text(path.read_bytes())
        except (OSError, UnicodeError) as exc:
            raise LegacyDispatchContractError(f"Frozen source unreadable: {source['path']}") from exc
        if _digest(text) != source["sha256"] or len(text.splitlines()) != source["lines"]:
            raise LegacyDispatchContractError(f"Frozen source drift: {source['path']}")
        texts[source["path"]] = text
    for extent in contract["extents"]:
        text = texts[extent["path"]]
        if extent["kind"] == "function":
            first, last, body = _function_extent(text, extent["name"])
        else:
            first, last = extent["start_line"], extent["end_line"]
            body = "\n".join(text.splitlines()[first - 1:last])
        if (first, last, _digest(body)) != (extent["start_line"], extent["end_line"], extent["sha256"]):
            raise LegacyDispatchContractError(f"Frozen extent drift: {extent['name']}")
    for call in contract["call_sites"]:
        line = texts[call["path"]].splitlines()[call["line"] - 1]
        if _digest(line) != call["line_sha256"]:
            raise LegacyDispatchContractError(f"Frozen caller drift: {call['caller']} -> {call['callee']}")
