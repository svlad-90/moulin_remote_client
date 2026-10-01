from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from components.remote.api import transport
from components.sync.api import mapping
from components.sync.test.test_planner import sample_config


class SyncMappingCommandServiceTests(unittest.TestCase):
    def test_rsync_mapping_command_owns_single_mapping_use_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            local_path = local_base / "layers/meta"
            local_path.mkdir(parents=True)
            service = mapping.sync_mapping_command_service()

            argv = service.rsync_mapping_command(
                {"name": "layer", "kind": "directory", "push": True, "remote": "layers/meta", "local": "layers/meta"},
                direction="push",
                dry_run=True,
                excludes=["--exclude", "*.pyc"],
                local_base=local_base,
                remote_base="builder@10.0.0.1:/mnt/projects/meta-product",
            )

            expected = transport.rsync_base_command(dry_run=True)
            expected.extend(
                [
                    "--exclude",
                    "*.pyc",
                    "--rsync-path",
                    "mkdir -p /mnt/projects/meta-product/layers/meta && rsync",
                    str(local_path) + "/",
                    "builder@10.0.0.1:/mnt/projects/meta-product/layers/meta/",
                ]
            )
            self.assertEqual(argv, expected)

    def test_remote_mapping_directory_uses_directory_target(self) -> None:
        service = mapping.sync_mapping_command_service()

        remote_dir = service.remote_mapping_directory(
            {"name": "layer", "kind": "directory", "push": True, "remote": "layers/meta", "local": "layers/meta"},
            remote_base="builder@10.0.0.1:/mnt/projects/meta-product",
        )

        self.assertEqual(remote_dir, "/mnt/projects/meta-product/layers/meta")

    def test_remote_mapping_directory_uses_file_parent(self) -> None:
        service = mapping.sync_mapping_command_service()

        remote_dir = service.remote_mapping_directory(
            {
                "name": "fragment",
                "kind": "file",
                "push": True,
                "remote": "android_kernel/common-modules/xen-virtual-device/xenvm.aarch64.fragment",
                "local": "android_kernel/common-modules/xen-virtual-device/xenvm.aarch64.fragment",
            },
            remote_base="builder@10.0.0.1:/mnt/projects/meta-product",
        )

        self.assertEqual(remote_dir, "/mnt/projects/meta-product/android_kernel/common-modules/xen-virtual-device")

    def test_rsync_mappings_push_command_batches_directory_and_file_mappings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            layer = local_base / "layers/meta"
            fragment = local_base / "android_kernel/common-modules/xen-virtual-device/xenvm.aarch64.fragment"
            layer.mkdir(parents=True)
            fragment.parent.mkdir(parents=True)
            fragment.write_text("CONFIG_XEN=y\n", encoding="utf-8")
            service = mapping.sync_mapping_command_service()

            argv = service.rsync_mappings_push_command(
                [
                    {"name": "layer", "kind": "directory", "push": True, "remote": "layers/meta", "local": "layers/meta"},
                    {
                        "name": "fragment",
                        "kind": "file",
                        "push": True,
                        "remote": "android_kernel/common-modules/xen-virtual-device/xenvm.aarch64.fragment",
                        "local": "android_kernel/common-modules/xen-virtual-device/xenvm.aarch64.fragment",
                    },
                ],
                dry_run=False,
                excludes=["--exclude", "*.pyc"],
                local_base=local_base,
                remote_base="builder@10.0.0.1:/mnt/projects/meta-product",
            )

            expected = transport.rsync_base_command(dry_run=False, relative=True)
            expected.extend(
                [
                    "--exclude",
                    "*.pyc",
                    "--rsync-path",
                    "mkdir -p /mnt/projects/meta-product && rsync",
                    str(local_base) + "/./layers/meta",
                    str(local_base) + "/./android_kernel/common-modules/xen-virtual-device/xenvm.aarch64.fragment",
                    "builder@10.0.0.1:/mnt/projects/meta-product/",
                ]
            )
            self.assertEqual(argv, expected)

    def test_mapping_sync_plan_owns_header_and_argv_use_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            (local_base / "layers/meta").mkdir(parents=True)
            service = mapping.sync_mapping_command_service()
            config = sample_config(app_dir)

            plan = service.mapping_sync_plan_for_config(
                config,
                ["layer"],
                direction="push",
                dry_run=True,
                app_dir=app_dir,
                excludes=[],
                remote_base="builder@10.0.0.1:/mnt/projects/meta-product",
            )

            self.assertEqual(plan[0]["header"][0], "\n== push: layer ==")
            self.assertEqual(plan[0]["argv"][-2:], [str(local_base / "layers/meta") + "/", "builder@10.0.0.1:/mnt/projects/meta-product/layers/meta/"])

    def test_selected_mapping_commands_read_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            (local_base / "layers/meta").mkdir(parents=True)
            selection_path = app_dir / "selected-mappings.txt"
            selection_path.write_text("layer\n", encoding="utf-8")
            service = mapping.sync_mapping_command_service()
            config = sample_config(app_dir)

            commands = service.selected_mapping_commands_for_config(
                config,
                selection_path=selection_path,
                direction="push",
                dry_run=True,
                app_dir=app_dir,
                excludes=[],
                remote_base="builder@10.0.0.1:/mnt/projects/meta-product",
            )

            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0][-2:], [str(local_base / "layers/meta") + "/", "builder@10.0.0.1:/mnt/projects/meta-product/layers/meta/"])


if __name__ == "__main__":
    unittest.main()
