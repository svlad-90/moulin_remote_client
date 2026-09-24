from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from components.moulin.api import manifest


class MoulinManifestBehaviorTests(unittest.TestCase):
    def test_yaml_tags_ignore_comments_and_include_directives(self) -> None:
        text = "\n".join(
            [
                "%TAG !m! tag:moulin:",
                "value: !include path.yaml",
                "other: value # !ignored",
                "list: [!merge {a: b}]",
            ]
        )

        self.assertEqual(
            manifest.yaml_tags(text),
            ["!include", "!m", "!merge", "%TAG"],
        )
        self.assertEqual(manifest.yaml_tags("plain: value\n# !ignored\n"), [])

    @unittest.skipUnless(manifest.yaml_available(), "PyYAML is not installed")
    def test_load_manifest_text_accepts_moulin_tags(self) -> None:
        text = "\n".join(
            [
                "min_ver: '1.0'",
                "components:",
                "  boot: !include boot.yaml",
            ]
        )

        self.assertEqual(
            manifest.load_manifest_text(text),
            {"min_ver": "1.0", "components": {"boot": "boot.yaml"}},
        )
        self.assertIsNotNone(manifest.MoulinYamlLoader)

    def test_resolve_manifest_path_prefers_existing_local_then_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local = root / "project"
            app = root / "app"
            local.mkdir()
            app.mkdir()
            fallback = app / "fallback.yaml"
            fallback.write_text("min_ver: '1.0'\n", encoding="utf-8")

            self.assertEqual(
                manifest.resolve_manifest_path("missing.yaml", local, app, "fallback.yaml"),
                fallback,
            )

            existing = local / "product.yaml"
            existing.write_text("min_ver: '1.0'\n", encoding="utf-8")
            self.assertEqual(
                manifest.resolve_manifest_path("product.yaml", local, app, "fallback.yaml"),
                existing,
            )

    def test_resolve_manifest_path_for_config_uses_active_project_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local = root / "overlay"
            local.mkdir()
            manifest_path = local / "prod.yaml"
            manifest_path.write_text("min_ver: '1.0'\n", encoding="utf-8")
            config = {
                "local": {"project_dir": str(root / "legacy")},
                "projects": [{"name": "prod", "local_project_dir": str(local), "moulin_manifest": "prod.yaml"}],
                "active_project": "prod",
            }

            self.assertEqual(manifest.resolve_manifest_path_for_config(config, root), manifest_path)

    @unittest.skipUnless(manifest.yaml_available(), "PyYAML is not installed")
    def test_load_manifest_for_config_prefers_remote_and_caches_by_project(self) -> None:
        calls: list[tuple[str, str]] = []

        def read_remote(config: dict[str, object], path: str) -> str:
            calls.append((str(config["active_project"]), path))
            return "min_ver: '1.0'\nimages:\n  full_ufs: {}\n"

        config = {
            "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
            "active_remote": "build",
            "projects": [{"name": "prod", "project_dir": "meta-product", "moulin_manifest": "prod.yaml"}],
            "active_project": "prod",
            "local": {"project_dir": "missing"},
        }
        cache: dict[tuple[str, str, str], dict[str, object]] = {}

        first = manifest.load_manifest_for_config(config, app_dir=Path("/tmp/app"), remote_read_project_file=read_remote, cache=cache)
        second = manifest.load_manifest_for_config(config, app_dir=Path("/tmp/app"), remote_read_project_file=read_remote, cache=cache)

        self.assertEqual(first, {"min_ver": "1.0", "images": {"full_ufs": {}}})
        self.assertIs(first, second)
        self.assertEqual(calls, [("prod", "prod.yaml")])

    @unittest.skipUnless(manifest.yaml_available(), "PyYAML is not installed")
    def test_build_runtime_context_for_config_merges_manifest_defaults_and_project_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local = root / "overlay"
            local.mkdir()
            (local / "prod.yaml").write_text(
                "\n".join(
                    [
                        "min_ver: '1.0'",
                        "parameters:",
                        "  ENABLE_ANDROID:",
                        "    no: {}",
                        "    yes:",
                        "      default: 'true'",
                    ]
                ),
                encoding="utf-8",
            )
            config = {
                "local": {"project_dir": str(root / "legacy")},
                "projects": [
                    {
                        "name": "prod",
                        "local_project_dir": str(local),
                        "moulin_manifest": "prod.yaml",
                        "parameters": {"ENABLE_ANDROID": "no", "CUSTOM": "value"},
                        "targets": "boot_artifacts",
                        "board_artifacts": "full_ufs.img.gz",
                        "docker_image": "project-image",
                    }
                ],
                "active_project": "prod",
            }

            context = manifest.build_runtime_context_for_config(
                config,
                app_dir=root,
                env={},
                default_docker_image="default-image",
                default_build_targets="default-target",
                default_moulin_manifest="fallback.yaml",
                remote_read_project_file=lambda _config, _path: "",
                cache={},
            )

            self.assertEqual(context["docker_image"], "project-image")
            self.assertEqual(context["build_params"], {"ENABLE_ANDROID": "no", "CUSTOM": "value"})
            self.assertEqual(context["build_targets"], "boot_artifacts")
            self.assertEqual(context["board_artifacts"], "full_ufs.img.gz")

    @unittest.skipUnless(manifest.yaml_available(), "PyYAML is not installed")
    def test_artifact_copy_specs_for_config_uses_effective_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local = root / "overlay"
            local.mkdir()
            (local / "prod.yaml").write_text(
                "\n".join(
                    [
                        "min_ver: '1.0'",
                        "variables:",
                        "  out: artifacts",
                        "components:",
                        "  boot_artifacts:",
                        "    builder:",
                        "      target_images:",
                        "        - '%{out}/boot.tar'",
                        "parameters:",
                        "  MODE:",
                        "    base: {}",
                        "    android:",
                        "      default: 'true'",
                        "      overrides:",
                        "        images:",
                        "          full_ufs: {}",
                    ]
                ),
                encoding="utf-8",
            )
            config = {
                "local": {"project_dir": str(local)},
                "projects": [{"name": "prod", "moulin_manifest": "prod.yaml"}],
                "active_project": "prod",
            }

            self.assertEqual(
                manifest.artifact_copy_specs_for_config(
                    config,
                    ["boot_artifacts", "full_ufs.img.gz"],
                    app_dir=root,
                    remote_read_project_file=lambda _config, _path: "",
                    cache={},
                ),
                [
                    {
                        "label": "boot_artifacts",
                        "path": "artifacts/boot.tar",
                        "source": "manifest component target_images",
                    },
                    {"label": "full_ufs.img.gz", "path": "full_ufs.img.gz", "source": "manifest image output"},
                ],
            )

    @unittest.skipUnless(manifest.yaml_available(), "PyYAML is not installed")
    def test_validate_manifest_text_reports_markers_and_tags(self) -> None:
        ok, detail = manifest.validate_manifest_text(
            "\n".join(
                [
                    "min_ver: '1.0'",
                    "components:",
                    "  boot:",
                    "    builder:",
                    "      type: !include tar",
                ]
            )
        )

        self.assertTrue(ok)
        self.assertEqual(detail, "min_ver, components, builder.type; tags !include")

    def test_manifest_markers_require_moulin_shape(self) -> None:
        data = {
            "min_ver": "1.0",
            "components": {"boot": {"builder": {"type": "tar", "target_images": ["boot.tar"]}}},
            "variables": {},
        }

        self.assertEqual(
            manifest.manifest_markers(data),
            ["min_ver", "components", "builder.type", "variables"],
        )
        self.assertTrue(manifest.is_manifest_data(data))
        self.assertFalse(manifest.is_manifest_data({"components": {}}))

    def test_parameters_defaults_and_targets_match_current_behavior(self) -> None:
        data = {
            "min_ver": "1.0",
            "images": {"full_ufs": {"desc": "UFS"}},
            "components": {"boot_artifacts": {"builder": {"target_images": ["artifacts/boot.tar"]}}},
            "parameters": {
                "ENABLE_ANDROID": {
                    "desc": "Android",
                    "no": {},
                    "yes": {
                        "default": "true",
                        "overrides": {
                            "images": {"android_only": {"desc": "Android image"}},
                            "components": {
                                "android_boot": {"builder": {"target_images": ["android/boot.tar"]}}
                            },
                        },
                    },
                }
            },
        }

        self.assertEqual(
            manifest.parameters_from_manifest(data),
            [
                {
                    "name": "ENABLE_ANDROID",
                    "desc": "Android",
                    "choices": ["no", "yes"],
                    "default": "yes",
                }
            ],
        )
        self.assertEqual(
            manifest.target_candidates_from_manifest(data),
            [
                {"target": "android_boot", "source": "ENABLE_ANDROID=yes", "desc": "ENABLE_ANDROID=yes component target"},
                {"target": "android_only.img.gz", "source": "ENABLE_ANDROID=yes", "desc": "Android image"},
                {"target": "boot_artifacts", "source": "manifest", "desc": "manifest component target"},
                {"target": "full_ufs.img.gz", "source": "manifest", "desc": "UFS"},
            ],
        )

    def test_effective_manifest_merges_overrides_without_mutating_source(self) -> None:
        data = {
            "min_ver": "1.0",
            "variables": {"base": "artifacts", "boot": "%{base}/boot.tar"},
            "images": {"full_ufs": {}},
            "parameters": {
                "mode": {
                    "base": {},
                    "custom": {
                        "default": "true",
                        "overrides": {
                            "images": {"debug": {}},
                            "variables": {"debug": "%{base}/debug.img"},
                        },
                    },
                }
            },
        }
        original = copy.deepcopy(data)

        effective = manifest.effective_manifest(data)

        self.assertEqual(data, original)
        self.assertIn("debug", effective["images"])
        self.assertEqual(
            manifest.effective_variables(effective),
            {"base": "artifacts", "boot": "artifacts/boot.tar", "debug": "artifacts/debug.img"},
        )

    def test_board_artifact_specs_resolve_component_images_and_fallbacks(self) -> None:
        data = {
            "variables": {"out": "artifacts"},
            "images": {"full_ufs": {}},
            "components": {
                "boot_artifacts": {
                    "builder": {"target_images": ["%{out}/ironhide-boot-artifacts.tar.bz2"]}
                }
            },
        }

        self.assertEqual(
            manifest.artifact_copy_specs_from_manifest(data, ["boot_artifacts", "full_ufs.img.gz", "extra.bin"]),
            [
                {
                    "label": "boot_artifacts",
                    "path": "artifacts/ironhide-boot-artifacts.tar.bz2",
                    "source": "manifest component target_images",
                },
                {"label": "full_ufs.img.gz", "path": "full_ufs.img.gz", "source": "manifest image output"},
                {"label": "extra.bin", "path": "extra.bin", "source": "filesystem fallback"},
            ],
        )

    def test_yocto_image_recipes_from_manifest_uses_effective_build_targets(self) -> None:
        data = {
            "variables": {"DOM0_IMAGE": "core-image-thin-initramfs", "DOMD_IMAGE": "rcar-image-adas"},
            "components": {
                "dom0": {"builder": {"type": "yocto", "build_target": "%{DOM0_IMAGE}"}},
                "domd": {"builder": {"type": "yocto", "build_target": "%{DOMD_IMAGE}"}},
                "domu": {"builder": {"type": "yocto", "build_target": "%{DOMD_IMAGE}"}},
                "boot_artifacts": {"builder": {"type": "tar", "target_images": ["boot.tar"]}},
            },
            "parameters": {
                "MODE": {
                    "base": {},
                    "custom": {
                        "default": "true",
                        "overrides": {
                            "components": {
                                "diagnostic": {"builder": {"type": "yocto", "build_target": "diagnostic-image"}}
                            }
                        },
                    },
                }
            },
        }

        self.assertEqual(
            manifest.yocto_image_recipes_from_manifest(data),
            ["core-image-thin-initramfs", "rcar-image-adas", "diagnostic-image"],
        )

    def test_component_builders_from_manifest_expands_supported_targets(self) -> None:
        data = {
            "variables": {
                "DOMD_IMAGE": "rcar-image-adas",
                "KERNEL_TARGET": "//common-modules/xen-virtual-device:xen_virtual_device_aarch64_dist",
            },
            "components": {
                "domd": {"builder": {"type": "yocto", "build_target": "%{DOMD_IMAGE}"}},
                "doma_kernel": {"builder": {"type": "bazel", "target": "%{KERNEL_TARGET}"}},
                "doma": {"builder": {"type": "android"}},
                "boot_artifacts": {"builder": {"type": "custom_script"}},
            },
        }

        self.assertEqual(
            manifest.component_builders_from_manifest(data),
            [
                {"name": "domd", "builder_type": "yocto", "target": "rcar-image-adas"},
                {
                    "name": "doma_kernel",
                    "builder_type": "bazel",
                    "target": "//common-modules/xen-virtual-device:xen_virtual_device_aarch64_dist",
                    "build_dir": "",
                    "tool": "tools/bazel",
                    "command": "build",
                    "args": [],
                    "target_patterns": [],
                    "target_images": [],
                },
                {"name": "doma", "builder_type": "android", "target": "doma"},
                {"name": "boot_artifacts", "builder_type": "custom_script", "target": "boot_artifacts"},
            ],
        )

    def test_component_builders_from_manifest_skips_components_disabled_by_parameters(self) -> None:
        data = {
            "components": {
                "dom0": {"builder": {"type": "yocto", "build_target": "core-image-thin-initramfs"}},
                "domd": {"builder": {"type": "yocto", "build_target": "rcar-image-adas"}},
                "domu": {"builder": {"type": "yocto", "build_target": "xt-rcar-image"}},
                "doma_kernel": {"builder": {"type": "bazel", "target": "//kernel:dist"}},
                "doma": {"builder": {"type": "android"}},
            },
        }

        self.assertEqual(
            manifest.component_builders_from_manifest(
                data,
                {
                    "ENABLE_DOMU": "no",
                    "ENABLE_DOMA": "no",
                },
            ),
            [
                {"name": "dom0", "builder_type": "yocto", "target": "core-image-thin-initramfs"},
                {"name": "domd", "builder_type": "yocto", "target": "rcar-image-adas"},
            ],
        )

    @unittest.skipUnless(manifest.yaml_available(), "PyYAML is not installed")
    def test_yocto_image_recipes_for_config_loads_manifest(self) -> None:
        manifest_text = "\n".join(
            [
                "min_ver: '1.0'",
                "variables:",
                "  DOM0_IMAGE: core-image-thin-initramfs",
                "  DOMD_IMAGE: rcar-image-adas",
                "components:",
                "  dom0:",
                "    builder:",
                "      type: yocto",
                "      build_target: '%{DOM0_IMAGE}'",
                "  domd:",
                "    builder:",
                "      type: yocto",
                "      build_target: '%{DOMD_IMAGE}'",
            ]
        )
        config = {
            "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
            "active_remote": "build",
            "projects": [{"name": "prod", "project_dir": "meta-product", "moulin_manifest": "prod.yaml"}],
            "active_project": "prod",
        }

        self.assertEqual(
            manifest.yocto_image_recipes_for_config(
                config,
                app_dir=Path("/tmp/app"),
                remote_read_project_file=lambda _config, _path: manifest_text,
                cache={},
            ),
            ["core-image-thin-initramfs", "rcar-image-adas"],
        )


if __name__ == "__main__":
    unittest.main()
