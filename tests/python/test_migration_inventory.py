"""The migration's public retirement measurements must match real Git-tracked source."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("migration_inventory", ROOT / "pcucp-next/packaging/check_migration_inventory.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MigrationInventoryTests(unittest.TestCase):
    def test_checked_in_measurement_and_source_locations_are_current(self):
        actual = json.loads((ROOT / module.INVENTORY).read_text(encoding="utf-8"))
        self.assertEqual(actual, module.expected(ROOT, actual))

    def test_only_top_level_function_declarations_are_navigation_entries(self):
        parsed = module.functions(b"\xef\xbb\xbffunction A {\n  function Nested {}\n}\nfunction B {}\n")
        self.assertEqual(parsed, {"lines": 4, "functions": [{"name": "A", "line": 1}, {"name": "B", "line": 4}]})

    def test_reintroduced_retired_function_is_not_claimed_as_removed(self):
        inventory = json.loads((ROOT / module.INVENTORY).read_text(encoding="utf-8"))
        entry = inventory["files"][0]
        inventory["retired_functions"].append({"path": entry["path"], "name": entry["functions"][0]["name"],
            "replacement": "README.md", "evidence": "test"})
        with self.assertRaisesRegex(ValueError, "still-present"):
            module.expected(ROOT, inventory)
