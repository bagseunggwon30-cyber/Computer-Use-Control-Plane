"""Separate compiled-helper packaging is opt-in, deterministic, and fail-closed."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "publish_legacy_helper", ROOT / "pcucp-next/packaging/publish_legacy_helper.py")
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class LegacyHelperPackageTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="CUCP helper 한글 ")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.source = self.root / "build output"
        self.source.mkdir()
        self.output = self.root / "staged helper"
        self.artifacts = {
            "PcuCp.LegacyHelper.exe": b"test-only helper bytes\x00\xff",
            "PcuCp.LegacyHelper.exe.config": b"<configuration/>\n",
            "PcuCp.LegacyInterop.dll": b"test-only interop bytes\x00\xfe",
        }
        self.populate(self.source)

    def populate(self, target):
        for name, content in self.artifacts.items():
            (target / name).write_bytes(content)

    def package(self):
        return publisher.stage_package(self.source, self.output)

    def write_manifest(self, manifest):
        (self.output / publisher.MANIFEST_NAME).write_text(
            json.dumps(manifest), encoding="utf-8")

    def test_build_argv_preserves_spaces_unicode_and_targets_only_helper(self):
        command = publisher.build_command("C:/SDK 한글 folder/dotnet.exe", self.source)
        self.assertEqual(command, ["C:/SDK 한글 folder/dotnet.exe", "build",
            str(ROOT / "pcucp-next/dotnet/PcuCp.LegacyHelper/PcuCp.LegacyHelper.csproj"),
            "-c", "Release", "--output", str(self.source.resolve())])
        self.assertNotIn("--self-contained", command)
        self.assertNotIn("publish", command)

    def test_default_is_separate_opt_in_helper_directory(self):
        self.assertEqual(publisher.DEFAULT_OUTPUT, ROOT / "pcucp-next/bin/legacy-helper")
        self.assertEqual(publisher.REQUIRED_FILES, (
            "PcuCp.LegacyHelper.exe", "PcuCp.LegacyHelper.exe.config", "PcuCp.LegacyInterop.dll"))

    def test_manifest_freezes_staged_metadata_and_required_hashes(self):
        manifest = self.package()
        self.assertEqual(manifest, {
            "schema": "cucp.legacy-helper-package/v1",
            "status": "staged-unqualified", "helper_version": "2.0.0",
            "runtime": "net48", "runtime_dependencies": ["Windows", ".NET Framework 4.8"],
            "entrypoint": "PcuCp.LegacyHelper.exe",
            "files": {name: {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
                      for name, content in self.artifacts.items()},
        })
        self.assertEqual(publisher.validate_package(self.output), manifest)

    def test_manifest_is_deterministic_across_relocation(self):
        manifest = self.package()
        relocated = self.root / "another 한글 folder"
        publisher.stage_package(self.source, relocated)
        first = (self.output / "manifest.json").read_bytes()
        self.assertEqual(first, (relocated / "manifest.json").read_bytes())
        self.assertEqual(first, (json.dumps(manifest, indent=2, sort_keys=True,
                                           ensure_ascii=False) + "\n").encode("utf-8"))
        self.assertNotIn(str(self.root).encode("utf-8"), first)
        self.assertNotIn(b"\r", first)

    def test_copies_only_frozen_required_artifacts(self):
        for name in ("PcuCp.LegacyHelper.pdb", "PcuCp.LegacyInterop.pdb", "fixture.json",
                     "PcuCp.LegacyHelper.OracleFixtures.exe", "ScriptedHelperProvider.cs",
                     "PcuCp.LegacyHelper.ContractTests.exe", "manifest.json"):
            (self.source / name).write_text("not a runtime artifact", encoding="utf-8")
        (self.source / "fixtures").mkdir()
        (self.source / "fixtures" / "replay.json").write_text("{}", encoding="utf-8")
        self.package()
        self.assertEqual({p.name for p in self.output.iterdir()}, set(self.artifacts) | {"manifest.json"})
        for name, content in self.artifacts.items():
            self.assertEqual((self.output / name).read_bytes(), content)

    def test_missing_each_artifact_is_detected_before_output_creation(self):
        for name in self.artifacts:
            with self.subTest(name=name):
                (self.source / name).unlink()
                with self.assertRaisesRegex(ValueError, "Required regular file"):
                    self.package()
                self.assertFalse(self.output.exists())
                self.populate(self.source)

    def test_required_directory_is_not_an_artifact(self):
        path = self.source / "PcuCp.LegacyHelper.exe"
        path.unlink()
        path.mkdir()
        with self.assertRaises(ValueError):
            self.package()
        self.assertFalse(self.output.exists())

    def test_refuses_existing_empty_directory_and_preserves_existing_package(self):
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError, "overwritten"):
            self.package()
        self.assertEqual(list(self.output.iterdir()), [])
        self.output.rmdir()
        self.package()
        before = {p.name: p.read_bytes() for p in self.output.iterdir()}
        with self.assertRaisesRegex(ValueError, "overwritten"):
            self.package()
        self.assertEqual({p.name: p.read_bytes() for p in self.output.iterdir()}, before)

    def test_copy_failure_removes_incomplete_output(self):
        with patch.object(publisher.shutil, "copyfileobj", side_effect=OSError("copy failed")):
            with self.assertRaisesRegex(OSError, "copy failed"):
                self.package()
        self.assertFalse(self.output.exists())
        self.assertEqual({p.name for p in self.source.iterdir()}, set(self.artifacts))

    def test_validator_rejects_missing_package_and_manifest(self):
        with self.assertRaises(ValueError):
            publisher.validate_package(self.output)
        self.output.mkdir()
        with self.assertRaises(ValueError):
            publisher.validate_package(self.output)

    def test_validator_rejects_tampering_and_missing_required_file(self):
        manifest = self.package()
        for name in self.artifacts:
            with self.subTest(name=name):
                path = self.output / name
                path.write_bytes(b"tampered")
                with self.assertRaisesRegex(ValueError, "hash or size mismatch"):
                    publisher.validate_package(self.output)
                path.unlink()
                with self.assertRaises(ValueError):
                    publisher.validate_package(self.output)
                path.write_bytes(self.artifacts[name])
        self.assertEqual(publisher.validate_package(self.output), manifest)

    def test_validator_rejects_changed_metadata(self):
        manifest = self.package()
        mutations = {"schema": "cucp.legacy-helper-package/v2", "status": "qualified",
                     "helper_version": "1.0.0", "runtime": "net8.0",
                     "runtime_dependencies": [], "entrypoint": "other.exe"}
        for key, value in mutations.items():
            with self.subTest(key=key):
                self.write_manifest({**manifest, key: value})
                with self.assertRaisesRegex(ValueError, key):
                    publisher.validate_package(self.output)

    def test_validator_rejects_extra_missing_and_nonobject_manifest_fields(self):
        manifest = self.package()
        for malformed in ({**manifest, "qualified": True},
                          {key: value for key, value in manifest.items() if key != "status"},
                          [], None, "not a manifest"):
            with self.subTest(manifest=malformed):
                self.write_manifest(malformed)
                with self.assertRaises(ValueError):
                    publisher.validate_package(self.output)

    def test_validator_rejects_malformed_json_encoding_and_duplicate_keys(self):
        self.package()
        for value in (b"{", b"\xff", b'{"schema":"first","schema":"second"}'):
            with self.subTest(value=value):
                (self.output / "manifest.json").write_bytes(value)
                with self.assertRaises(ValueError):
                    publisher.validate_package(self.output)

    def test_validator_rejects_extra_payload_file_or_directory(self):
        self.package()
        extra = self.output / "fixtures"
        extra.mkdir()
        with self.assertRaises(ValueError):
            publisher.validate_package(self.output)
        extra.rmdir()
        extra.write_bytes(b"fixture")
        with self.assertRaises(ValueError):
            publisher.validate_package(self.output)

    def test_validator_rejects_extra_missing_and_path_file_records(self):
        manifest = self.package()
        files = manifest["files"]
        for malformed in ({**files, "../outside.exe": next(iter(files.values()))},
                          {key: value for key, value in files.items() if key != publisher.ENTRYPOINT},
                          list(files), None):
            with self.subTest(files=malformed):
                self.write_manifest({**manifest, "files": malformed})
                with self.assertRaises(ValueError):
                    publisher.validate_package(self.output)

    def test_validator_rejects_malformed_records_and_bool_sizes(self):
        manifest = self.package()
        record = manifest["files"][publisher.ENTRYPOINT]
        variants = [[], None, {**record, "path": "../outside.exe"},
                    {"bytes": record["bytes"]}, {**record, "sha256": "A" * 64},
                    {**record, "sha256": "f" * 63}, {**record, "sha256": 1}]
        variants += [{**record, "bytes": value} for value in (True, False, -1, 1.0, "1", None)]
        for bad_record in variants:
            with self.subTest(record=bad_record):
                self.write_manifest({**manifest, "files": {
                    **manifest["files"], publisher.ENTRYPOINT: bad_record}})
                with self.assertRaises(ValueError):
                    publisher.validate_package(self.output)

    def test_validator_checks_size_even_if_hash_matches(self):
        manifest = self.package()
        manifest["files"][publisher.ENTRYPOINT]["bytes"] += 1
        self.write_manifest(manifest)
        with self.assertRaisesRegex(ValueError, "hash or size mismatch"):
            publisher.validate_package(self.output)

    def symlink(self, target, path, is_directory=False):
        try:
            path.symlink_to(target, target_is_directory=is_directory)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlink creation is unavailable: {error}")

    def test_rejects_linked_build_artifact(self):
        linked = self.source / publisher.ENTRYPOINT
        linked.unlink()
        outside = self.root / "outside.exe"
        outside.write_bytes(b"outside")
        self.symlink(outside, linked)
        with self.assertRaises(ValueError):
            self.package()
        self.assertFalse(self.output.exists())

    def test_validator_rejects_linked_payload_manifest_and_package(self):
        self.package()
        for name in (publisher.ENTRYPOINT, "manifest.json"):
            path = self.output / name
            content = path.read_bytes()
            target = self.root / name
            target.write_bytes(content)
            path.unlink()
            self.symlink(target, path)
            with self.assertRaises(ValueError):
                publisher.validate_package(self.output)
            path.unlink()
            path.write_bytes(content)
        alias = self.root / "linked package"
        self.symlink(self.output, alias, is_directory=True)
        with self.assertRaises(ValueError):
            publisher.validate_package(alias)

    def test_refuses_dangling_output_symlink(self):
        self.symlink(self.root / "does not exist", self.output, is_directory=True)
        with self.assertRaisesRegex(ValueError, "overwritten"):
            self.package()
        self.assertTrue(self.output.is_symlink())

    def test_main_builds_in_clean_temporary_directory_argv_only(self):
        def fake_build(argv, **kwargs):
            target = Path(argv[-1])
            self.assertNotEqual(target, self.output)
            self.assertEqual(list(target.iterdir()), [])
            self.populate(target)
            (target / "fixture.json").write_text("{}", encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0)
        with patch.object(publisher.shutil, "which", return_value="/SDK 한글/dotnet"), \
                patch.object(publisher.subprocess, "run", side_effect=fake_build) as run, \
                redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(publisher.main(["--output", str(self.output)]), 0)
        self.assertIs(run.call_args.kwargs["shell"], False)
        self.assertEqual(run.call_args.kwargs["cwd"], ROOT)
        self.assertEqual(run.call_args.args[0][0], "/SDK 한글/dotnet")
        self.assertEqual(json.loads(stdout.getvalue())["status"], "staged-unqualified")
        self.assertEqual(list(self.root.glob(".legacy-helper-build-*")), [])
        publisher.validate_package(self.output)

    def test_optional_build_evidence_keeps_closure_outside_package(self):
        evidence = self.root / 'bounded evidence'
        def fake_build(argv, **kwargs):
            target=Path(argv[-1]);self.populate(target)
            (target/'PcuCp.LegacyHelper.pdb').write_bytes(b'owned symbols')
            return subprocess.CompletedProcess(argv,0)
        with patch.object(publisher.shutil,'which',return_value='dotnet'), \
                patch.object(publisher.subprocess,'run',side_effect=fake_build), redirect_stdout(io.StringIO()):
            self.assertEqual(publisher.main(['--output',str(self.output),'--evidence-dir',str(evidence)]),0)
        closure=json.loads((evidence/'package-build-closure.json').read_text())
        self.assertEqual(closure['included'],list(publisher.REQUIRED_FILES))
        self.assertIn('PcuCp.LegacyHelper.pdb',closure['build_output'])
        self.assertEqual(closure['source_program']['sha256'],hashlib.sha256((publisher.PROJECT.parent/'Program.cs').read_bytes()).hexdigest())
        self.assertEqual(json.loads((evidence/'package-manifest.json').read_text()),publisher.validate_package(self.output))
        self.assertFalse((self.output/'PcuCp.LegacyHelper.pdb').exists())

    def test_main_preserves_build_exit_code_and_leaves_no_package(self):
        with patch.object(publisher.shutil, "which", return_value="dotnet"), \
                patch.object(publisher.subprocess, "run", return_value=subprocess.CompletedProcess([], 7)):
            self.assertEqual(publisher.main(["--output", str(self.output)]), 7)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".legacy-helper-build-*")), [])

    def test_main_success_without_artifacts_fails(self):
        with patch.object(publisher.shutil, "which", return_value="dotnet"), \
                patch.object(publisher.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)), \
                redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as failure:
                publisher.main(["--output", str(self.output)])
        self.assertEqual(failure.exception.code, 2)
        self.assertFalse(self.output.exists())

    def test_main_refuses_existing_output_before_sdk_or_build(self):
        self.output.mkdir()
        with patch.object(publisher.shutil, "which") as sdk, \
                patch.object(publisher.subprocess, "run") as run, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                publisher.main(["--output", str(self.output)])
        sdk.assert_not_called()
        run.assert_not_called()

    def test_main_missing_sdk_fails_without_creating_output(self):
        with patch.object(publisher.shutil, "which", return_value=None), \
                patch.object(publisher.subprocess, "run") as run, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                publisher.main(["--output", str(self.output), "--dotnet", "absent-sdk"])
        run.assert_not_called()
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
