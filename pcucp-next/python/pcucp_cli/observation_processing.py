"""Bounded, pure observation processing; never captures, opens files, or acts.

OCR coordinates are image pixels. UIA rectangles are physical screen pixels.
Scores rank evidence, not permission or proof that an action is safe.
"""
from __future__ import annotations

import math
import re
import struct
import unicodedata
import zlib
from typing import Any, Mapping

MAX_ITEMS = 10_000
MAX_TEXT = 4096
MAX_TEXT_TOTAL = 262_144
MAX_FUZZY_CELLS = 10_000_000
MAX_PIXELS = 16_777_216
MAX_PNG_BYTES = 67_108_864


def _integer(value: Any, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in {low}..{high}")
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result) or abs(result) > 100_000_000:
        raise ValueError(f"{name} must be finite and within coordinate bounds")
    return result


def normalize_ocr_text(text: str | None) -> str:
    """Legacy FormKC + invariant lowercase + Unicode letters/decimal digits."""
    if text is None:
        return ""
    if not isinstance(text, str) or len(text) > MAX_TEXT:
        raise ValueError(f"OCR text must be a string of at most {MAX_TEXT} characters")
    normalized = unicodedata.normalize("NFKC", text).lower()
    if len(normalized) > MAX_TEXT:
        raise ValueError("normalized OCR text exceeds the character budget")
    return " ".join("".join(
        c if unicodedata.category(c).startswith("L") or unicodedata.category(c) == "Nd" or c.isspace()
        else " " for c in normalized
    ).split())


def _distance(left: str, right: str) -> int:
    if len(right) > len(left):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(previous[j] + 1, current[-1] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def _score_normalized(needle: str, hay: str, mode: str, budget: list[int]) -> int:
    if not needle or not hay:
        return 0
    if needle == hay:
        return 100
    if mode == "exact":
        return 0
    if mode == "prefix":
        return 80 if hay.startswith(needle) else 0
    if mode == "fuzzy":
        cost = len(needle) * len(hay)
        budget[0] -= cost
        if budget[0] < 0:
            raise ValueError("fuzzy matching exceeds the edit-distance work budget")
        best = round((1 - _distance(needle, hay) / max(len(needle), len(hay))) * 100)
        if needle in hay:
            best = max(best, 55 + math.floor(len(needle) / len(hay) * 30))
        return max(0, min(100, best))
    index = hay.find(needle)
    if index < 0:
        return 0
    return min(95, 50 + math.floor(len(needle) / len(hay) * 30) + (10 if index == 0 else 0))


def _mode(mode: str) -> None:
    if not isinstance(mode, str) or mode not in {"exact", "prefix", "contains", "fuzzy"}:
        raise ValueError("match must be exact, prefix, contains, or fuzzy")


def score_ocr_text(needle: str, hay: str, mode: str = "contains") -> int:
    _mode(mode)
    return _score_normalized(normalize_ocr_text(needle), normalize_ocr_text(hay), mode, [MAX_FUZZY_CELLS])


def _rect(item: Mapping[str, Any]) -> dict[str, float]:
    if not isinstance(item, Mapping):
        raise ValueError("rectangle must be an object")
    source = item
    for key in ("rect", "bounding_rectangle", "geometry"):
        if isinstance(item.get(key), Mapping):
            source = item[key]
            break
    x, y = _number(source.get("x"), "x"), _number(source.get("y"), "y")
    width = _number(source.get("width", source.get("w")), "width")
    height = _number(source.get("height", source.get("h")), "height")
    if width <= 0 or height <= 0:
        raise ValueError("rectangle dimensions must be positive")
    return {"x": x, "y": y, "width": width, "height": height}


def _union(rectangles: list[dict[str, float]]) -> dict[str, float]:
    left, top = min(r["x"] for r in rectangles), min(r["y"] for r in rectangles)
    return {"x": left, "y": top,
            "width": max(r["x"] + r["width"] for r in rectangles) - left,
            "height": max(r["y"] + r["height"] for r in rectangles) - top}


def _location(item: Mapping[str, Any]) -> tuple[float, ...]:
    return tuple(item[key] for key in ("x", "y", "width", "height"))


def _list(value: Any, name: str) -> list:
    if not isinstance(value, (list, tuple)) or len(value) > MAX_ITEMS:
        raise ValueError(f"{name} must be a list of at most {MAX_ITEMS} items")
    return value


def match_ocr_candidates(body: Mapping[str, Any], text: str, match: str = "contains", *,
                         min_score: int = 0, limit: int = 50,
                         ambiguity_margin: int = 8) -> dict[str, Any]:
    """Rank line/word/adjacent 2–3-word matches, retaining spatial ambiguity.

    Limits affect output only; ambiguity is computed before truncation. Duplicate
    flat/nested words and duplicate line/word boxes do not create false ambiguity.
    Input/work-budget overflow raises ValueError rather than returning a false best.
    """
    _mode(match)
    _integer(min_score, "min_score", 0, 100)
    _integer(limit, "limit", 1, 1000)
    _integer(ambiguity_margin, "ambiguity_margin", 1, 101)
    if not isinstance(body, Mapping):
        raise ValueError("OCR body must be an object")
    data = body.get("ocr", body)
    if not isinstance(data, Mapping):
        raise ValueError("ocr must be an object")
    space = data.get("coordinate_space", "image_pixels")
    if space != "image_pixels":
        raise ValueError("OCR candidate matching requires image_pixels coordinates")
    needle = normalize_ocr_text(text)
    if not needle:
        raise ValueError("text must contain a letter or decimal digit")
    needs_ngrams = len(needle.split()) >= 2
    candidates: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    budget = [MAX_FUZZY_CELLS]
    item_count = char_count = 0

    def add(raw: Mapping[str, Any], scope: str, rect: dict | None = None, n: int | None = None) -> None:
        nonlocal item_count, char_count
        if not isinstance(raw, Mapping) or not isinstance(raw.get("text", ""), str):
            raise ValueError("OCR entries must be objects with string text")
        item_count += 1
        char_count += len(raw.get("text", ""))
        if item_count > MAX_ITEMS or char_count > MAX_TEXT_TOTAL:
            raise ValueError("OCR input exceeds the item or character work budget")
        hay = normalize_ocr_text(raw.get("text", ""))
        score = _score_normalized(needle, hay, match, budget)
        if score <= 0 or score < min_score:
            return
        box = rect or _rect(raw)
        key = (scope, hay, *_location(box))
        if key in seen:
            return
        seen.add(key)
        candidate = {"scope": scope, "score": score, "text": raw.get("text", ""), **box,
                     "w": box["width"], "h": box["height"],
                     "cx": box["x"] + box["width"] / 2,
                     "cy": box["y"] + box["height"] / 2, "coordinate_space": "image_pixels"}
        if n is not None:
            candidate["n"] = n
        candidates.append(candidate)

    for line in _list(data.get("lines", []), "lines"):
        if not isinstance(line, Mapping):
            raise ValueError("OCR lines must be objects")
        words = _list(line.get("words", []), "line.words")
        # Native lines have no geometry. Derive their box from their actual words.
        rectangles = [_rect(word) for word in words]
        line_box = _union(rectangles) if rectangles else None
        if line_box is not None or any(k in line for k in ("x", "rect", "geometry")):
            add(line, "line", line_box)
        else:
            # Text-only lines cannot ground a point; still account for their text.
            add({"text": ""}, "line")
        for word in words:
            add(word, "word")
        if needs_ngrams:
            for n in (2, 3):
                for start in range(len(words) - n + 1):
                    part = words[start:start + n]
                    if any(not isinstance(word.get("text", ""), str) for word in part):
                        raise ValueError("OCR word text must be a string")
                    add({"text": " ".join(word.get("text", "") for word in part)},
                        "word_ngram", _union(rectangles[start:start + n]), n)
    for word in _list(data.get("words", []), "words"):
        add(word, "word")
    order = {"word_ngram": 0, "word": 1, "line": 2}
    candidates.sort(key=lambda c: (-c["score"], order[c["scope"]], c["width"] * c["height"]))
    top = candidates[0] if candidates else None
    distinct = next((c for c in candidates[1:] if _location(c) != _location(top)), None) if top else None
    ambiguous = bool(distinct and top["score"] - distinct["score"] < ambiguity_margin)
    incomplete = bool(body.get("truncated") or data.get("truncated") or body.get("status") == "partial" or data.get("status") == "partial")
    return {"status": "partial" if ambiguous or incomplete else "ok" if top else "not_found",
            "query": {"text": text, "match": match, "min_score": min_score},
            "top": top, "candidates": candidates[:limit], "candidate_count": len(candidates),
            "ambiguous": ambiguous, "truncated": incomplete or len(candidates) > limit,
            "source_incomplete": incomplete, "coordinate_space": "image_pixels", "actionable": False}


def _identity(target: Mapping[str, Any]) -> tuple[int, int]:
    if not isinstance(target, Mapping):
        raise ValueError("target must contain hwnd and pid")
    hwnd = target.get("hwnd")
    if type(hwnd) is int:
        handle = hwnd
    elif isinstance(hwnd, str) and re.fullmatch(r"0[xX][0-9a-fA-F]{1,16}", hwnd):
        handle = int(hwnd, 16)
    else:
        raise ValueError("hwnd must be a positive integer or hexadecimal handle")
    _integer(handle, "hwnd", 1, 2**64 - 1)
    return handle, _integer(target.get("pid"), "pid", 1, 2**32 - 1)


def fuse_ocr_uia(ocr_candidates: list[Mapping[str, Any]] | Mapping[str, Any],
                 uia_nodes: list[Mapping[str, Any]], *, geometry: Mapping[str, Any],
                 target: Mapping[str, Any], uia_target: Mapping[str, Any],
                 limit: int = 8, ambiguity_margin: int = 8) -> dict[str, Any]:
    """Map OCR image points to same-target physical UIA rectangles; never act.

    Tree parent relationships come only from children arrays. Return all bounded
    alternatives rather than the legacy helper's unconditional best candidate.
    """
    identity = _identity(target)
    if identity != _identity(uia_target):
        raise ValueError("OCR and UIA target identities must match exactly")
    _integer(limit, "limit", 1, 100)
    _integer(ambiguity_margin, "ambiguity_margin", 1, 101)
    area = _rect(geometry)
    iw = _number(geometry.get("image_width"), "image_width")
    ih = _number(geometry.get("image_height"), "image_height")
    if iw <= 0 or ih <= 0:
        raise ValueError("image dimensions must be positive")
    source_incomplete = False
    source_ambiguous = False
    if isinstance(ocr_candidates, Mapping):
        source_incomplete = bool(ocr_candidates.get("truncated") or ocr_candidates.get("source_incomplete"))
        source_ambiguous = bool(ocr_candidates.get("ambiguous"))
        ocr_candidates = ocr_candidates.get("candidates", [])
    ocr_candidates = _list(ocr_candidates, "ocr_candidates")
    nodes: list[tuple[Mapping[str, Any], int | None, dict | None]] = []
    stack = [(node, None, 0) for node in reversed(_list(uia_nodes, "uia_nodes"))]
    seen: set[int] = set()
    while stack:
        node, parent, depth = stack.pop()
        if not isinstance(node, Mapping) or depth > 64 or len(nodes) >= MAX_ITEMS or id(node) in seen:
            raise ValueError("UIA tree is malformed, cyclic, or exceeds the node/depth budget")
        seen.add(id(node))
        index = len(nodes)
        raw_rect = next((node.get(key) for key in ("bounding_rectangle", "rect", "geometry") if node.get(key) is not None), None)
        box = _rect(raw_rect) if raw_rect is not None else None
        nodes.append((node, parent, box))
        stack.extend((child, index, depth + 1) for child in reversed(_list(node.get("children", []), "children")))
    results: dict[int, dict] = {}
    for ocr in ocr_candidates[:limit]:
        if not isinstance(ocr, Mapping) or ocr.get("coordinate_space", "image_pixels") != "image_pixels":
            raise ValueError("OCR fusion requires image_pixels candidates")
        r = _rect(ocr)
        if r["x"] < 0 or r["y"] < 0 or r["x"] + r["width"] > iw or r["y"] + r["height"] > ih:
            raise ValueError("OCR candidate lies outside the captured image")
        score = _integer(ocr.get("score"), "OCR score", 0, 100)
        # Never trust caller-supplied cx/cy independent of the validated box.
        x = area["x"] + (r["x"] + r["width"] / 2) * area["width"] / iw
        y = area["y"] + (r["y"] + r["height"] / 2) * area["height"] / ih
        hits = []
        for index, (node, _, box) in enumerate(nodes):
            if box and node.get("process_id", node.get("pid", identity[1])) == identity[1] and box["x"] <= x < box["x"] + box["width"] and box["y"] <= y < box["y"] + box["height"]:
                hits.append((box["width"] * box["height"], index))
        if not hits:
            continue
        smallest = min(hit[0] for hit in hits)
        # Keep equally small overlapping nodes instead of arbitrary first-hit selection.
        for _, first in (hit for hit in hits if hit[0] == smallest):
            index = first
            for depth in range(7):
                node, parent, box = nodes[index]
                if box is None or node.get("process_id", node.get("pid", identity[1])) != identity[1]:
                    break
                if not (box["x"] <= x < box["x"] + box["width"] and box["y"] <= y < box["y"] + box["height"]):
                    break
                patterns = _list(node.get("supported_patterns", node.get("patterns", [])), "patterns")
                supported = {p.removesuffix("Pattern") for p in patterns if isinstance(p, str)}
                pattern = next((p for p in ("Invoke", "Toggle", "SelectionItem") if p in supported), None)
                if pattern is None and node.get("invoke_pattern") in {"InvokePattern", "TogglePattern", "SelectionItemPattern"}:
                    pattern = node["invoke_pattern"].removesuffix("Pattern")
                enabled = node.get("is_enabled", node.get("enabled"))
                offscreen = node.get("is_offscreen", node.get("offscreen"))
                role = str(node.get("control_type", node.get("role", ""))).lower()
                bonus = 100 if pattern else 0
                bonus += 20 if re.search(r"button|menu|hyperlink|tab|list.?item|check|radio", role) else 0
                bonus += 10 if enabled is True else -20 if enabled is False else 0
                bonus -= 30 if offscreen is True else 0
                item = {"ocr": dict(ocr), "uia": {"node_index": index, "name": node.get("name"),
                        "automation_id": node.get("automation_id"), "element_ref": node.get("element_ref"),
                        "control_type": node.get("control_type", node.get("role")), "rect": box},
                        "pattern": f"{pattern}Pattern" if pattern else None, "can_invoke": bool(pattern),
                        "enabled": enabled, "offscreen": offscreen,
                        "fusion_score": score + bonus - depth * 3, "parent_climb_depth": depth,
                        "point": {"x": x, "y": y, "screen_x": x, "screen_y": y,
                                  "image_x": r["x"] + r["width"] / 2,
                                  "image_y": r["y"] + r["height"] / 2,
                                  "coordinate_space": "physical_screen_pixels"},
                        "target": dict(target), "actionable": False}
                previous = results.get(index)
                if previous is None or (item["fusion_score"], score) > (previous["fusion_score"], previous["ocr"]["score"]):
                    results[index] = item
                if pattern or parent is None:
                    break
                index = parent
    ranked = sorted(results.values(), key=lambda r: (-int(r["can_invoke"]), -r["fusion_score"], -r["ocr"]["score"], r["uia"]["node_index"]))
    ambiguous = source_ambiguous or bool(len(ranked) > 1 and ranked[0]["can_invoke"] == ranked[1]["can_invoke"] and ranked[0]["fusion_score"] - ranked[1]["fusion_score"] < ambiguity_margin)
    incomplete = source_incomplete or len(ocr_candidates) > limit
    return {"status": "partial" if ambiguous or incomplete else "ok" if ranked else "not_found",
            "top": ranked[0] if ranked else None, "candidates": ranked[:limit], "candidate_count": len(ranked),
            "ambiguous": ambiguous, "truncated": incomplete or len(ranked) > limit,
            "target": dict(target), "coordinate_space": "physical_screen_pixels", "actionable": False,
            "requires_fresh_observation": True}


def decode_png(data: bytes) -> dict[str, Any]:
    """Decode bounded noninterlaced 8-bit RGB/RGBA PNG, validating every CRC.

    Reject unsupported formats explicitly. No Pillow, file access, or native codec.
    """
    if not isinstance(data, bytes) or not 8 <= len(data) <= MAX_PNG_BYTES or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("invalid PNG signature or input byte limit")
    position = 8
    width = height = channels = 0
    compressed = bytearray()
    seen_header = seen_data = ended_data = ended = False
    chunk_count = 0
    while position < len(data):
        chunk_count += 1
        if chunk_count > 10_000 or len(data) - position < 12:
            raise ValueError("truncated PNG or excessive chunk count")
        length = struct.unpack_from(">I", data, position)[0]
        kind = data[position + 4:position + 8]
        if any(not (65 <= byte <= 90 or 97 <= byte <= 122) for byte in kind) or kind[2] & 32:
            raise ValueError("invalid PNG chunk type")
        if length > MAX_PNG_BYTES or position + 12 + length > len(data):
            raise ValueError("invalid PNG chunk length")
        payload = data[position + 8:position + 8 + length]
        expected_crc = struct.unpack_from(">I", data, position + 8 + length)[0]
        if zlib.crc32(payload, zlib.crc32(kind)) & 0xFFFFFFFF != expected_crc:
            raise ValueError("PNG CRC mismatch")
        position += 12 + length
        if not seen_header and kind != b"IHDR":
            raise ValueError("PNG IHDR must be first")
        if kind == b"IHDR":
            if seen_header or length != 13:
                raise ValueError("invalid PNG IHDR")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
            if not 1 <= width <= 10000 or not 1 <= height <= 10000 or width * height > MAX_PIXELS:
                raise ValueError("PNG dimensions exceed pixel budget")
            if depth != 8 or color not in (2, 6) or compression or filtering or interlace:
                raise ValueError("only noninterlaced 8-bit RGB/RGBA PNG is supported")
            channels = 3 if color == 2 else 4
            seen_header = True
        elif kind == b"IDAT":
            if ended_data:
                raise ValueError("PNG IDAT chunks must be consecutive")
            seen_data = True
            compressed.extend(payload)
        elif kind == b"IEND":
            if length or not seen_data or position != len(data):
                raise ValueError("invalid PNG IEND or trailing data")
            ended = True
            break
        elif kind == b"PLTE":
            if seen_data or not length or length % 3 or length > 768:
                raise ValueError("invalid PNG PLTE")
        elif kind in (b"tRNS", b"acTL", b"fcTL", b"fdAT") or not kind[0] & 32:
            raise ValueError("unsupported PNG transparency, animation, or critical chunk")
        if seen_data and kind != b"IDAT":
            ended_data = True
    if not ended:
        raise ValueError("PNG IEND missing")
    stride = width * channels
    expected = (stride + 1) * height
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, expected + 1)
    except zlib.error as exc:
        raise ValueError("invalid PNG deflate stream") from exc
    if len(raw) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError("PNG decompressed size or stream boundary mismatch")
    rgba = bytearray(width * height * 4)
    previous = bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        filter_type = raw[start]
        if filter_type > 4:
            raise ValueError("invalid PNG filter")
        row = bytearray(raw[start + 1:start + 1 + stride])
        if filter_type:
            for i in range(stride):
                a = row[i - channels] if i >= channels else 0
                b = previous[i]
                c = previous[i - channels] if i >= channels else 0
                if filter_type == 1:
                    predictor = a
                elif filter_type == 2:
                    predictor = b
                elif filter_type == 3:
                    predictor = (a + b) // 2
                else:
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    predictor = a if pa <= pb and pa <= pc else b if pb <= pc else c
                row[i] = (row[i] + predictor) & 255
        dest = y * width * 4
        if channels == 4:
            rgba[dest:dest + width * 4] = row
        else:
            for x in range(width):
                rgba[dest + x * 4:dest + x * 4 + 3] = row[x * 3:x * 3 + 3]
                rgba[dest + x * 4 + 3] = 255
        previous = row
    return {"width": width, "height": height, "rgba": bytes(rgba)}


def _image(value: bytes | Mapping[str, Any]) -> tuple[int, int, bytes]:
    if isinstance(value, bytes):
        value = decode_png(value)
    if not isinstance(value, Mapping):
        raise ValueError("image must be PNG bytes or {width,height,rgba}")
    width = _integer(value.get("width"), "image width", 1, 10000)
    height = _integer(value.get("height"), "image height", 1, 10000)
    pixels = value.get("rgba")
    if width * height > MAX_PIXELS or not isinstance(pixels, (bytes, bytearray)) or len(pixels) != width * height * 4:
        raise ValueError("image pixel budget or RGBA byte length mismatch")
    return width, height, pixels


def _pixel_rect(value: Mapping[str, Any]) -> dict[str, int]:
    rect = _rect(value)
    if any(n != int(n) for n in rect.values()):
        raise ValueError("pixel regions require integer coordinates and dimensions")
    return {k: int(v) for k, v in rect.items()}


def screenshot_diff(before: bytes | Mapping[str, Any], after: bytes | Mapping[str, Any], *,
                    threshold: int = 16, region: Mapping[str, Any] | None = None,
                    ignore_regions: list[Mapping[str, Any]] | tuple = ()) -> dict[str, Any]:
    """Legacy RGB-L1 difference over overlap; alpha is intentionally ignored.

    changed means changed_ratio > .001, not proof of task completion. A fully
    masked comparison is partial/inconclusive. Regions use absolute image pixels.
    """
    _integer(threshold, "threshold", 0, 765)
    aw, ah, a = _image(before)
    bw, bh, b = _image(after)
    left = top = 0
    right, bottom = min(aw, bw), min(ah, bh)
    if region is not None:
        requested = _pixel_rect(region)
        left, top = max(0, requested["x"]), max(0, requested["y"])
        right = min(right, requested["x"] + requested["width"])
        bottom = min(bottom, requested["y"] + requested["height"])
    if right <= left or bottom <= top:
        raise ValueError("empty compare region")
    if not isinstance(ignore_regions, (list, tuple)) or len(ignore_regions) > 64:
        raise ValueError("ignore_regions must contain at most 64 rectangles")
    masks = [_pixel_rect(value) for value in ignore_regions]
    changed = ignored = 0
    for y in range(top, bottom):
        intervals = sorted((max(left, r["x"]), min(right, r["x"] + r["width"]))
                           for r in masks if r["y"] <= y < r["y"] + r["height"] and r["x"] < right and r["x"] + r["width"] > left)
        merged: list[list[int]] = []
        for start, end in intervals:
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        ignored += sum(end - start for start, end in merged)
        cursor = left
        for start, end in merged + [[right, right]]:
            for x in range(cursor, start):
                ai, bi = (y * aw + x) * 4, (y * bw + x) * 4
                if abs(a[ai] - b[bi]) + abs(a[ai + 1] - b[bi + 1]) + abs(a[ai + 2] - b[bi + 2]) > threshold:
                    changed += 1
            cursor = end
    total = (right - left) * (bottom - top)
    effective = total - ignored
    ratio = changed / effective if effective else 0.0
    return {"status": "ok" if effective and (aw, ah) == (bw, bh) else "partial",
            "width": right - left, "height": bottom - top, "offset": {"x": left, "y": top},
            "total_pixels": total, "effective_pixels": effective, "ignored_pixels": ignored,
            "changed_pixels": changed, "changed_ratio": round(ratio, 6), "changed": ratio > .001,
            "threshold": threshold, "same_dimensions": (aw, ah) == (bw, bh),
            "comparison_complete": bool(effective and (aw, ah) == (bw, bh)), "alpha_compared": False}
