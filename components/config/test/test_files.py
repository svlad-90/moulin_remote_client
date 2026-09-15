from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from components.config.api import files


class ConfigFileBehaviorTests(unittest.TestCase):
    def test_load_config_file_uses_example_fallback_and_prepare_callback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "missing.json"
            example = Path(tmpdir) / "example.json"
            example.write_text('{"ui": {"title": "Example"}}\n', encoding="utf-8")
            prepared = []

            config = files.load_config_file(path, example, prepare=lambda value: prepared.append(value))

            self.assertEqual(config["__config_path"], str(path))
            self.assertEqual(config["ui"]["title"], "Example")
            self.assertIs(prepared[0], config)

    def test_save_config_file_merges_existing_file_and_skips_internal_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text('{"preserve": true, "ui": {"title": "Old"}}\n', encoding="utf-8")
            config = {
                "__config_path": str(path),
                "__runtime": "skip",
                "ui": {"title": "New"},
                "active_project": "prod",
            }
            synced = []

            files.save_config_file(config, Path(tmpdir) / "default.json", sync=lambda value: synced.append(value))

            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["preserve"], True)
            self.assertEqual(data["ui"], {"title": "New"})
            self.assertEqual(data["active_project"], "prod")
            self.assertNotIn("__runtime", data)
            self.assertIs(synced[0], config)

    def test_save_config_file_refuses_config_without_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError):
                files.save_config_file({}, Path(tmpdir) / "default.json", sync=lambda config: None)

    def test_prepare_loaded_config_normalizes_profiles_env_and_legacy_views(self) -> None:
        config = {
            "remote": {"name": "build", "label": "Build", "user": "u", "host": "h"},
            "project": {"project_dir": "/projects/meta-product"},
            "local": {"project_dir": "overlay"},
        }

        files.prepare_loaded_config(
            config,
            env={"MOULIN_REMOTE_SSH_HOST": "env-host"},
            legacy_settings={"parameters": {"ENABLE_ANDROID": "yes"}},
            default_build_targets="full_ufs.img.gz",
            default_moulin_manifest="prod.yaml",
            default_dockerfile="doc/Dockerfile",
        )

        self.assertEqual(config["active_remote"], "build")
        self.assertEqual(config["remote"], config["remotes"][0])
        self.assertEqual(config["remote"]["host"], "env-host")
        self.assertEqual(config["active_project"], "default")
        self.assertEqual(config["project"], config["projects"][0])
        self.assertEqual(config["project"]["project_dir"], "meta-product")
        self.assertEqual(config["project"]["targets"], "full_ufs.img.gz")
        self.assertEqual(config["project"]["moulin_manifest"], "prod.yaml")
        self.assertEqual(config["project"]["dockerfile"], "doc/Dockerfile")
        self.assertEqual(config["project"]["parameters"], {"ENABLE_ANDROID": "yes"})


if __name__ == "__main__":
    unittest.main()
