from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from components.config.api import profiles
from components.build_runtime.api import runtime


class ConfigRuntimeBehaviorTests(unittest.TestCase):
    def test_load_runtime_config_uses_example_and_legacy_build_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            config_path = app_dir / "config.json"
            example_path = app_dir / "example.json"
            legacy_path = app_dir / "state" / "build-settings.json"
            legacy_path.parent.mkdir()
            legacy_path.write_text(
                json.dumps({"parameters": {"ENABLE_ANDROID": "yes"}, "targets": "legacy_target"}),
                encoding="utf-8",
            )
            example_path.write_text(
                json.dumps(
                    {
                        "remote": {"name": "build", "label": "Build", "user": "u", "host": "h"},
                        "project": {"project_dir": "/projects/meta-product"},
                        "local": {"project_dir": "overlay"},
                        "state": {"build_settings": str(legacy_path)},
                    }
                ),
                encoding="utf-8",
            )

            config = runtime.load_runtime_config(
                config_path,
                example_path,
                app_dir=app_dir,
                env={},
                default_build_targets="default_target",
                default_moulin_manifest="prod.yaml",
                default_dockerfile="doc/Dockerfile",
            )

            self.assertEqual(config["__config_path"], str(config_path))
            self.assertEqual(profiles.active_project(config)["parameters"], {"ENABLE_ANDROID": "yes"})
            self.assertEqual(profiles.active_project(config)["targets"], "legacy_target")
            self.assertEqual(profiles.active_project(config)["moulin_manifest"], "prod.yaml")

    def test_load_runtime_config_for_env_applies_env_build_target_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            config_path = app_dir / "config.json"
            example_path = app_dir / "example.json"
            example_path.write_text(
                json.dumps(
                    {
                        "remote": {"name": "build", "user": "u", "host": "h"},
                        "project": {"project_dir": "/projects/meta-product"},
                        "local": {"project_dir": "overlay"},
                    }
                ),
                encoding="utf-8",
            )

            config = runtime.load_runtime_config_for_env(
                config_path,
                example_path,
                app_dir=app_dir,
                env={"MOULIN_REMOTE_BUILD_TARGETS": "env_target"},
                default_build_targets="default_target",
                default_moulin_manifest="prod.yaml",
                default_dockerfile="doc/Dockerfile",
            )

            self.assertEqual(profiles.active_project(config)["targets"], "env_target")

    def test_runtime_build_settings_save_updates_project_and_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            config_path = app_dir / "config.json"
            settings_path = app_dir / "state" / "build-settings.json"
            config = {
                "__config_path": str(config_path),
                "state": {"build_settings": str(settings_path)},
                "remotes": [{"name": "build", "user": "u", "host": "h"}],
                "active_remote": "build",
                "projects": [{"name": "prod", "project_dir": "meta-product"}],
                "active_project": "prod",
            }
            profiles.normalize_remote_profiles(config)
            profiles.normalize_project_profiles(config)
            runtime.save_runtime_config(config, config_path)

            runtime.save_runtime_build_settings(
                config,
                {"parameters": {"ENABLE_DOMU": "yes"}, "targets": "target", "docker_image": "img"},
                app_dir,
                config_path,
            )

            self.assertEqual(profiles.active_project(config)["parameters"], {"ENABLE_DOMU": "yes"})
            self.assertEqual(profiles.active_project(config)["targets"], "target")
            self.assertEqual(json.loads(settings_path.read_text(encoding="utf-8"))["docker_image"], "img")

    def test_current_runtime_build_settings_helper_builds_settings_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            config_path = app_dir / "config.json"
            settings_path = app_dir / "state" / "build-settings.json"
            config = {
                "__config_path": str(config_path),
                "state": {"build_settings": str(settings_path)},
                "remotes": [{"name": "build", "user": "u", "host": "h"}],
                "active_remote": "build",
                "projects": [{"name": "prod", "project_dir": "meta-product"}],
                "active_project": "prod",
            }
            profiles.normalize_remote_profiles(config)
            profiles.normalize_project_profiles(config)

            runtime.save_current_runtime_build_settings(
                config,
                parameters={"ENABLE_ANDROID": "yes"},
                targets="android_only.img.gz",
                docker_image="prod-image",
                app_dir=app_dir,
                default_path=config_path,
            )

            self.assertEqual(profiles.active_project(config)["parameters"], {"ENABLE_ANDROID": "yes"})
            self.assertEqual(profiles.active_project(config)["targets"], "android_only.img.gz")
            self.assertEqual(profiles.active_project(config)["docker_image"], "prod-image")
            self.assertEqual(json.loads(settings_path.read_text(encoding="utf-8"))["targets"], "android_only.img.gz")

    def test_runtime_incremental_components_are_saved_in_state_file_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            config_path = app_dir / "config.json"
            settings_path = app_dir / "state" / "build-settings.json"
            config = {
                "__config_path": str(config_path),
                "state": {"build_settings": str(settings_path)},
                "remotes": [{"name": "build", "user": "u", "host": "h"}],
                "active_remote": "build",
                "projects": [{"name": "prod", "project_dir": "meta-product"}],
                "active_project": "prod",
            }
            profiles.normalize_remote_profiles(config)
            profiles.normalize_project_profiles(config)
            runtime.save_runtime_build_settings(
                config,
                {"parameters": {}, "targets": "target", "docker_image": "img"},
                app_dir,
                config_path,
            )

            runtime.save_runtime_incremental_components(config, app_dir, ["doma_kernel", "doma"])

            self.assertEqual(runtime.load_runtime_incremental_components(config, app_dir), ["doma_kernel", "doma"])
            self.assertNotIn("incremental_components", profiles.active_project(config))
            saved = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["targets"], "target")
            self.assertEqual(saved["incremental_components"], ["doma_kernel", "doma"])

    def test_runtime_mapping_snapshot_tracks_changed_mappings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            layer = local_base / "layers/meta-xt-dom0-gen5"
            layer.mkdir(parents=True)
            recipe = layer / "recipe.bbappend"
            recipe.write_text("old\n", encoding="utf-8")
            config = {
                "state": {"build_settings": str(app_dir / "state/build-settings.json")},
                "exclude": [".git/"],
                "local": {"project_dir": str(local_base)},
                "remotes": [{"name": "build", "user": "u", "host": "h"}],
                "active_remote": "build",
                "projects": [{"name": "prod", "project_dir": "meta-product"}],
                "active_project": "prod",
            }
            profiles.normalize_remote_profiles(config)
            profiles.normalize_project_profiles(config)
            mappings = [{"name": "layers-meta-xt-dom0-gen5", "local": "layers/meta-xt-dom0-gen5"}]

            runtime.save_runtime_mapping_snapshot(config, app_dir, mappings)
            runtime.mark_runtime_mapping_build_applied(config, app_dir, mappings)
            self.assertEqual(runtime.changed_runtime_mappings(config, app_dir, mappings), [])
            self.assertEqual(runtime.changed_runtime_mapping_files(config, app_dir, mappings), [])

            recipe.write_text("new\n", encoding="utf-8")

            self.assertEqual(runtime.changed_runtime_mappings(config, app_dir, mappings), ["layers-meta-xt-dom0-gen5"])
            self.assertEqual(runtime.changed_runtime_mapping_files(config, app_dir, mappings), ["layers/meta-xt-dom0-gen5/recipe.bbappend"])

    def test_runtime_mapping_snapshot_preserves_copied_changes_until_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            layer = local_base / "layers/meta-xt-dom0-gen5"
            layer.mkdir(parents=True)
            recipe = layer / "recipe.bbappend"
            recipe.write_text("old\n", encoding="utf-8")
            config = {
                "state": {"build_settings": str(app_dir / "state/build-settings.json")},
                "local": {"project_dir": str(local_base)},
                "remotes": [{"name": "build", "user": "u", "host": "h"}],
                "active_remote": "build",
                "projects": [{"name": "prod", "project_dir": "meta-product"}],
                "active_project": "prod",
            }
            profiles.normalize_remote_profiles(config)
            profiles.normalize_project_profiles(config)
            mappings = [{"name": "layers-meta-xt-dom0-gen5", "local": "layers/meta-xt-dom0-gen5"}]

            runtime.save_runtime_mapping_snapshot(config, app_dir, mappings)
            runtime.mark_runtime_mapping_build_applied(config, app_dir, mappings)
            recipe.write_text("new\n", encoding="utf-8")
            runtime.save_runtime_mapping_snapshot(config, app_dir, mappings)

            self.assertEqual(runtime.changed_runtime_mappings(config, app_dir, mappings), ["layers-meta-xt-dom0-gen5"])
            self.assertEqual(
                runtime.changed_runtime_mapping_files(config, app_dir, mappings),
                ["layers/meta-xt-dom0-gen5/recipe.bbappend"],
            )

            runtime.clear_runtime_mapping_pending_changes(config, app_dir)

            self.assertEqual(runtime.changed_runtime_mappings(config, app_dir, mappings), [])
            self.assertEqual(runtime.changed_runtime_mapping_files(config, app_dir, mappings), [])

    def test_runtime_mapping_state_reset_queues_local_workspace_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            layer = local_base / "layers/meta-xt-dom0-gen5"
            layer.mkdir(parents=True)
            recipe = layer / "recipe.bbappend"
            recipe.write_text("old\n", encoding="utf-8")
            untouched = layer / "untouched.bbappend"
            untouched.write_text("same\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=app_dir, check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=app_dir, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=app_dir, check=True)
            subprocess.run(["git", "add", "."], cwd=app_dir, check=True)
            subprocess.run(["git", "commit", "-m", "baseline"], cwd=app_dir, check=True, stdout=subprocess.DEVNULL)
            recipe.write_text("current\n", encoding="utf-8")
            config = {
                "state": {"build_settings": str(app_dir / "state/build-settings.json")},
                "local": {"project_dir": str(local_base)},
                "remotes": [{"name": "build", "user": "u", "host": "h"}],
                "active_remote": "build",
                "projects": [{"name": "prod", "project_dir": "meta-product"}],
                "active_project": "prod",
            }
            profiles.normalize_remote_profiles(config)
            profiles.normalize_project_profiles(config)
            mappings = [{"name": "layers-meta-xt-dom0-gen5", "local": "layers/meta-xt-dom0-gen5"}]
            runtime.save_runtime_mapping_snapshot(config, app_dir, mappings)

            runtime.reset_runtime_mapping_state(config, app_dir, mappings)

            self.assertEqual(runtime.changed_runtime_mappings(config, app_dir, mappings), ["layers-meta-xt-dom0-gen5"])
            self.assertEqual(
                runtime.changed_runtime_mapping_files(config, app_dir, mappings),
                ["layers/meta-xt-dom0-gen5/recipe.bbappend"],
            )

    def test_incremental_state_workflow_keeps_pending_files_until_build_applies_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            dom0 = local_base / "layers/meta-xt-dom0-gen5"
            domu = local_base / "layers/meta-xt-domu-gen5"
            dom0.mkdir(parents=True)
            domu.mkdir(parents=True)
            dom0_recipe = dom0 / "recipe.bbappend"
            domu_recipe = domu / "recipe.bbappend"
            dom0_recipe.write_text("old-dom0\n", encoding="utf-8")
            domu_recipe.write_text("old-domu\n", encoding="utf-8")
            config = {
                "state": {"build_settings": str(app_dir / "state/build-settings.json")},
                "local": {"project_dir": str(local_base)},
                "remotes": [{"name": "build", "user": "u", "host": "h"}],
                "active_remote": "build",
                "projects": [{"name": "prod", "project_dir": "meta-product"}],
                "active_project": "prod",
            }
            profiles.normalize_remote_profiles(config)
            profiles.normalize_project_profiles(config)
            mappings = [
                {"name": "dom0-layer", "local": "layers/meta-xt-dom0-gen5"},
                {"name": "domu-layer", "local": "layers/meta-xt-domu-gen5"},
            ]

            runtime.save_runtime_mapping_snapshot(config, app_dir, mappings)
            runtime.mark_runtime_mapping_build_applied(config, app_dir, mappings)
            dom0_recipe.write_text("new-dom0\n", encoding="utf-8")
            domu_recipe.write_text("new-domu\n", encoding="utf-8")

            runtime.save_runtime_mapping_snapshot(config, app_dir, mappings)

            self.assertEqual(runtime.changed_runtime_mappings(config, app_dir, mappings), ["dom0-layer", "domu-layer"])
            self.assertEqual(
                runtime.changed_runtime_mapping_files(config, app_dir, mappings),
                [
                    "layers/meta-xt-dom0-gen5/recipe.bbappend",
                    "layers/meta-xt-domu-gen5/recipe.bbappend",
                ],
            )

            runtime.mark_runtime_mapping_build_applied(
                config,
                app_dir,
                mappings,
                applied_files=["layers/meta-xt-dom0-gen5/recipe.bbappend"],
            )

            self.assertEqual(runtime.changed_runtime_mappings(config, app_dir, mappings), ["domu-layer"])
            self.assertEqual(
                runtime.changed_runtime_mapping_files(config, app_dir, mappings),
                ["layers/meta-xt-domu-gen5/recipe.bbappend"],
            )

            runtime.mark_runtime_mapping_build_applied(config, app_dir, mappings)

            self.assertEqual(runtime.changed_runtime_mappings(config, app_dir, mappings), [])
            self.assertEqual(runtime.changed_runtime_mapping_files(config, app_dir, mappings), [])

    def test_runtime_mapping_snapshot_ignores_generated_product_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            local_base.mkdir(parents=True)
            recipe = local_base / "layers/meta-xt-dom0-gen5/recipe.bbappend"
            recipe.parent.mkdir(parents=True)
            recipe.write_text("old\n", encoding="utf-8")
            config = {
                "state": {"build_settings": str(app_dir / "state/build-settings.json")},
                "local": {"project_dir": str(local_base)},
                "remotes": [{"name": "build", "user": "u", "host": "h"}],
                "active_remote": "build",
                "projects": [{"name": "prod", "project_dir": "meta-product"}],
                "active_project": "prod",
            }
            profiles.normalize_remote_profiles(config)
            profiles.normalize_project_profiles(config)
            mappings = [{"name": "workspace-root", "local": "."}]

            runtime.save_runtime_mapping_snapshot(config, app_dir, mappings)
            runtime.mark_runtime_mapping_build_applied(config, app_dir, mappings)
            for generated in (
                ".ninja_deps.bad-20261005-153130",
                ".ninja_log",
                ".moulin_boot_artifacts.d",
                "defras-build-console.log",
                "full_ufs.img.gz",
                "yocto/build-dom0/tmp/work/stamp",
                "android/out/target/product/image.img",
            ):
                path = local_base / generated
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("generated\n", encoding="utf-8")

            self.assertEqual(runtime.changed_runtime_mappings(config, app_dir, mappings), [])
            self.assertEqual(runtime.changed_runtime_mapping_files(config, app_dir, mappings), [])

            recipe.write_text("new\n", encoding="utf-8")

            self.assertEqual(runtime.changed_runtime_mapping_files(config, app_dir, mappings), ["layers/meta-xt-dom0-gen5/recipe.bbappend"])

    def test_build_runtime_context_merges_config_settings_and_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            config = {
                "state": {"build_settings": str(app_dir / "state" / "build-settings.json")},
                "docker": {"image": "config-image"},
                "remotes": [{"name": "build", "user": "u", "host": "h"}],
                "active_remote": "build",
                "projects": [
                    {
                        "name": "prod",
                        "project_dir": "meta-product",
                        "parameters": {"ENABLE_ANDROID": "yes"},
                        "targets": "project-target",
                        "board_artifacts": "boot_artifacts",
                    }
                ],
                "active_project": "prod",
            }
            profiles.normalize_remote_profiles(config)
            profiles.normalize_project_profiles(config)

            context = runtime.build_runtime_context_for_config(
                config,
                app_dir=app_dir,
                env={"MOULIN_REMOTE_BUILD_TARGETS": "env-target"},
                default_docker_image="default-image",
                default_build_targets="default-target",
                default_parameters=lambda: {"ENABLE_DOMU": "no"},
            )

            self.assertEqual(context["docker_image"], "config-image")
            self.assertEqual(context["build_params"], {"ENABLE_DOMU": "no", "ENABLE_ANDROID": "yes"})
            self.assertEqual(context["build_targets"], "env-target")
            self.assertEqual(context["board_artifacts"], "boot_artifacts")


if __name__ == "__main__":
    unittest.main()
