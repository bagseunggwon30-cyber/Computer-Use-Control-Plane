from __future__ import annotations

from typing import Any

from .native_host import run_native


def _score_text(needle: str, candidate: str, mode: str) -> int:
    left = needle.casefold().strip()
    right = candidate.casefold().strip()
    if not left or not right:
        return 0
    if mode == "exact":
        return 100 if left == right else 0
    if mode == "prefix":
        return 90 if right.startswith(left) else 0
    if left == right:
        return 100
    if left in right:
        return 85
    return 0


def _word_candidate(word: dict[str, Any], score: int) -> dict[str, Any]:
    return {
        "scope": "word",
        "text": word.get("text", ""),
        "score": score,
        "x": word.get("x"),
        "y": word.get("y"),
        "width": word.get("width"),
        "height": word.get("height"),
        "cx": word.get("cx"),
        "cy": word.get("cy"),
    }


def _line_candidate(line: dict[str, Any], score: int) -> dict[str, Any]:
    words = [word for word in line.get("words", []) if isinstance(word, dict)]
    xs = [float(word.get("x", 0)) for word in words]
    ys = [float(word.get("y", 0)) for word in words]
    rs = [float(word.get("x", 0)) + float(word.get("width", 0)) for word in words]
    bs = [float(word.get("y", 0)) + float(word.get("height", 0)) for word in words]
    if xs and ys and rs and bs:
        x = min(xs)
        y = min(ys)
        width = max(rs) - x
        height = max(bs) - y
        cx = x + width / 2
        cy = y + height / 2
    else:
        x = y = width = height = cx = cy = 0
    return {
        "scope": "line",
        "text": line.get("text", ""),
        "score": score,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "cx": cx,
        "cy": cy,
    }


def ocr_find_text(path: str, text: str, match: str = "contains", language: str | None = None) -> tuple[int, dict[str, Any]]:
    native_args = ["--path", path]
    if language:
        native_args += ["--language", language]
    code, ocr_payload, error = run_native("ocr-image", native_args)
    route = {
        "primary": "python-router",
        "observation": "dotnet-native-host/ocr-image",
        "fallback": "legacy-powershell",
    }
    if ocr_payload is None:
        return code, {
            "schema": "pcucp.ocr-find-text/v1",
            "status": "error",
            "kind": "ocr-find-text",
            "query": {"text": text, "match": match},
            "route": route,
            "top": None,
            "candidates": [],
            "errors": [error],
        }
    if ocr_payload.get("status") != "ok":
        return code, {
            "schema": "pcucp.ocr-find-text/v1",
            "status": "error",
            "kind": "ocr-find-text",
            "query": {"text": text, "match": match},
            "route": route,
            "top": None,
            "candidates": [],
            "errors": ocr_payload.get("errors", []),
        }

    candidates: list[dict[str, Any]] = []
    for word in ocr_payload.get("words", []):
        if not isinstance(word, dict):
            continue
        score = _score_text(text, str(word.get("text", "")), match)
        if score > 0:
            candidates.append(_word_candidate(word, score))
    for line in ocr_payload.get("lines", []):
        if not isinstance(line, dict):
            continue
        score = _score_text(text, str(line.get("text", "")), match)
        if score > 0:
            candidates.append(_line_candidate(line, score))

    candidates.sort(key=lambda item: item["score"], reverse=True)
    status = "ok" if candidates else "not_found"
    return (0 if candidates else 2), {
        "schema": "pcucp.ocr-find-text/v1",
        "status": status,
        "kind": "ocr-find-text",
        "query": {"text": text, "match": match},
        "route": route,
        "top": candidates[0] if candidates else None,
        "candidates": candidates,
        "candidate_count": len(candidates),
        "ocr": {
            "engine_language": ocr_payload.get("engine_language"),
            "line_count": ocr_payload.get("line_count", 0),
            "word_count": ocr_payload.get("word_count", 0),
        },
        "errors": [] if candidates else ["no_text_match"],
    }
