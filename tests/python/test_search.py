import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pcucp-next" / "python"))
search = importlib.import_module("pcucp_cli.find_label")
ocr = importlib.import_module("pcucp_cli.ocr")


def windows(status="ok", data=None, errors=None):
    return {"status": status, "data": {"windows": data or []}, "errors": errors or []}


def uia(status="ok", data=None, errors=None):
    return {"status": status, "data": {"nodes": data or []}, "errors": errors or []}


class SearchTests(unittest.TestCase):
    def test_both_provider_errors_preserved(self):
        with patch.object(search, "run_native", side_effect=[(5, windows("error", errors=["denied"]), ""), (1, uia("error", errors=["UIA unavailable"]), "")]):
            code, result = search.find_label("test")
        self.assertEqual(code, 5)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["providers"][0]["errors"], ["denied"])
        self.assertEqual(result["providers"][1]["errors"], ["UIA unavailable"])

    def test_partial_with_match_does_not_appear_complete(self):
        with patch.object(search, "run_native", side_effect=[(0, windows(data=[{"title": "Save"}]), ""), (1, uia("partial", errors=["deadline"]), "")]):
            code, result = search.find_label("Save")
        self.assertNotEqual(code, 0)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["providers"][1]["errors"], ["deadline"])

    def test_partial_without_match_is_not_not_found(self):
        with patch.object(search, "run_native", side_effect=[(0, windows(), ""), (2, None, "host crashed")]):
            code, result = search.find_label("Save")
        self.assertEqual(code, 3)
        self.assertEqual(result["status"], "partial")
        self.assertIn("host crashed", str(result["errors"]))

    def test_complete_no_match(self):
        with patch.object(search, "run_native", side_effect=[(0, windows(), ""), (0, uia(), "")]):
            code, result = search.find_label("Save")
        self.assertEqual((code, result["status"]), (2, "not_found"))

    def test_bounds_and_target_forwarded(self):
        with patch.object(search, "run_native", side_effect=[(0, windows(data=[{"title": "Save", "hwnd": "0x20", "process_id": 7}, {"title": "Save", "hwnd": "0x21", "process_id": 7}]), ""), (0, uia(), "")]) as run:
            code, result = search.find_label("Save", hwnd="0x20", pid=7, max_depth=3, max_nodes=100, timeout_s=2)
        self.assertEqual(code, 0)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(run.call_args.args, ("uia-tree", ["--max-depth", "3", "--max-nodes", "100", "--hwnd", "0x20", "--pid", "7"]))
        self.assertEqual(run.call_args.kwargs, {"timeout_s": 2})

    def test_empty_query_does_not_call_provider(self):
        with patch.object(search, "run_native") as run:
            self.assertEqual(search.find_label("  ")[0], 2)
            run.assert_not_called()

    def test_ocr_error_exit_never_zero(self):
        with patch.object(ocr, "run_native", return_value=(0, {"status": "error", "errors": ["OCR unavailable"]}, "")):
            code, result = ocr.ocr_find_text("image.png", "Save")
        self.assertNotEqual(code, 0)
        self.assertEqual(result["errors"], ["OCR unavailable"])

    def test_ocr_exit_failure_does_not_return_candidates(self):
        with patch.object(ocr, "run_native", return_value=(5, {"status": "ok", "words": [{"text": "Save"}], "errors": []}, "crashed")):
            code, result = ocr.ocr_find_text("image.png", "Save")
        self.assertEqual(code, 5)
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["errors"], ["crashed"])


if __name__ == "__main__":
    unittest.main()
