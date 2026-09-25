from __future__ import annotations

import shlex
import unittest

import moulin_remote_client as client
from components.config.api import accessors as config_accessors
from components.config.api import profiles as config_profiles
from components.remote.api import transport
from components.remote.test.command_adapter import commands


def sample_config() -> dict[str, object]:
    return {
        "remotes": [
            {
                "name": "build",
                "label": "Build",
                "user": "builder",
                "host": "10.0.0.1",
                "projects_dir": "/mnt/projects",
            }
        ],
        "active_remote": "build",
        "projects": [
            {
                "name": "prod",
                "label": "Prod",
                "project_dir": "meta-product",
                "docker_image": "prod_img",
                "dockerfile": "doc/Dockerfile",
                "git_url": "git@example:prod",
                "git_ref": "mirror",
                "moulin_manifest": "prod.yaml",
                "parameters": {"ENABLE_ANDROID": "yes"},
                "targets": "boot_artifacts full_ufs.img.gz",
            }
        ],
        "active_project": "prod",
    }


def prepare_config(config: dict[str, object]) -> None:
    config_profiles.normalize_remote_profiles(config)
    config_profiles.normalize_project_profiles(config)


class RemoteCommandBehaviorTests(unittest.TestCase):
    def test_connect_command_from_config_matches_low_level_builder(self) -> None:
        config = sample_config()
        prepare_config(config)

        self.assertEqual(
            commands.build_remote_connect_command_for_config(config),
            commands.build_remote_connect_command(
                config_accessors.remote_spec_for_config(config),
                config_accessors.remote_project_dir_for_config(config),
            ),
        )
        self.assertEqual(
            commands.build_interactive_remote_shell_command_for_config(config),
            transport.ssh_command("builder@10.0.0.1", "cd /mnt/projects/meta-product && exec bash -l", tty="-t"),
        )

    def test_project_file_read_and_status_probe_commands_match_current_shape(self) -> None:
        config = sample_config()
        prepare_config(config)

        self.assertEqual(
            commands.build_remote_project_file_read_command_for_config(config, "prod.yaml"),
            transport.ssh_command("builder@10.0.0.1", "cd /mnt/projects/meta-product && cat -- ./prod.yaml"),
        )
        self.assertEqual(
            commands.build_remote_project_file_read_command_for_config(config, "/tmp/prod.yaml"),
            transport.ssh_command("builder@10.0.0.1", "cd /mnt/projects/meta-product && cat -- /tmp/prod.yaml"),
        )
        self.assertEqual(
            commands.build_remote_status_probe_command_for_config(config),
            transport.ssh_command(
                "builder@10.0.0.1",
                "cd /mnt/projects/meta-product && pwd && df -h . && git status --short --branch || true",
            ),
        )

    def test_inventory_and_tree_commands_match_client_wrappers(self) -> None:
        config = sample_config()
        config["inventory"] = {"max_depth": 7}
        config["exclude"] = ["build/", "*.pyc"]
        prepare_config(config)

        self.assertEqual(
            commands.build_inventory_command(config_accessors.remote_project_dir_for_config(config), config["exclude"], 7),
            commands.build_inventory_command_for_config(config),
        )
        self.assertEqual(
            commands.build_inventory_fetch_command_for_config(config),
            transport.ssh_command("builder@10.0.0.1", commands.build_inventory_command_for_config(config)),
        )
        self.assertEqual(
            commands.build_project_tree_command(config_accessors.remote_project_dir_for_config(config), config["exclude"], 120),
            commands.build_project_tree_command_for_config(config, 120),
        )
        self.assertIn("-maxdepth 99", commands.build_project_tree_command_for_config(config, 120))
        self.assertIn("-path ./build -o -path './build/*' -o -name build -o -name '*.pyc'", commands.build_project_tree_command_for_config(config, 120))

    def test_project_listing_command_matches_client_wrapper(self) -> None:
        config = sample_config()
        config["exclude"] = ["build/", "tmp*"]
        prepare_config(config)

        self.assertEqual(
            commands.build_project_listing_command(config_accessors.remote_project_dir_for_config(config), config["exclude"], "layers/meta"),
            commands.build_project_listing_command_for_config(config, "layers/meta"),
        )
        self.assertEqual(
            commands.build_project_listing_fetch_command_for_config(config, "layers/meta"),
            transport.ssh_command("builder@10.0.0.1", commands.build_project_listing_command_for_config(config, "layers/meta")),
        )
        self.assertIn("find ./layers/meta -mindepth 1 -maxdepth 1", commands.build_project_listing_command_for_config(config, "layers/meta"))
        self.assertIn("-type f -printf 'f\\t%p\\n'", commands.build_project_listing_command_for_config(config, "layers/meta"))

    def test_remote_directory_browse_helpers_match_current_shape(self) -> None:
        config = sample_config()
        prepare_config(config)

        self.assertEqual(
            commands.build_remote_child_dirs_fetch_command_for_config(config, "~"),
            transport.ssh_command(
                "builder@10.0.0.1",
                "cd $HOME && find . -mindepth 1 -maxdepth 1 -type d -printf '%P\\n' | sort",
            ),
        )
        self.assertEqual(
            commands.build_remote_child_dirs_fetch_command_for_config(config, "/mnt/projects"),
            transport.ssh_command(
                "builder@10.0.0.1",
                "cd /mnt/projects && find . -mindepth 1 -maxdepth 1 -type d -printf '%P\\n' | sort",
            ),
        )
        self.assertEqual(
            commands.parse_remote_child_dirs_output("/mnt/projects", "b\na\n\n"),
            ["/mnt/projects/b", "/mnt/projects/a"],
        )
        self.assertEqual(
            commands.fetch_remote_child_dirs_for_config(config, "/mnt/projects", lambda argv: "meta\nother\n"),
            ["/mnt/projects/meta", "/mnt/projects/other"],
        )
        self.assertEqual(
            commands.build_remote_home_fetch_command_for_config(config),
            transport.ssh_command("builder@10.0.0.1", "printf '%s\\n' \"$HOME\""),
        )
        self.assertEqual(commands.remote_home_from_output("/home/builder\n"), "/home/builder")
        self.assertEqual(commands.remote_home_from_output("\n"), "~")
        self.assertEqual(commands.remote_parent_dir("~", "/home/builder"), "/home")
        self.assertEqual(commands.remote_parent_dir("~/work/project"), "~/work")
        self.assertEqual(commands.remote_parent_dir("/mnt/projects/meta"), "/mnt/projects")
        self.assertEqual(commands.remote_parent_dir(""), "~")

    def test_project_tree_fetch_command_and_parsers_match_tui_shape(self) -> None:
        config = sample_config()
        config["exclude"] = []
        prepare_config(config)

        self.assertEqual(
            commands.build_project_tree_fetch_command_for_config(config, 2),
            transport.ssh_command("builder@10.0.0.1", commands.build_project_tree_command_for_config(config, 2)),
        )
        self.assertEqual(
            commands.parse_project_tree_output("d\tlayers/meta\nd\t ./recipes \nf\tignored\n"),
            [
                {"path": "layers/meta", "kind": "directory"},
                {"path": "recipes", "kind": "directory"},
            ],
        )
        self.assertEqual(
            commands.parse_project_listing_output("d\tlayers/meta\nf\tREADME.md\nl\tlink\n\tignored\n"),
            [
                {"path": "layers/meta", "kind": "directory"},
                {"path": "README.md", "kind": "file"},
                {"path": "link", "kind": "file"},
                {"path": "ignored", "kind": "file"},
            ],
        )

    def test_runner_based_project_fetch_helpers_build_and_parse(self) -> None:
        config = sample_config()
        config["exclude"] = []
        prepare_config(config)
        calls: list[list[str]] = []

        def runner(argv: list[str]) -> str:
            calls.append(argv)
            if len(calls) == 1:
                return "d\tlayers\n"
            return "f\tREADME.md\n"

        self.assertEqual(commands.fetch_project_tree_for_config(config, 2, runner), [{"path": "layers", "kind": "directory"}])
        self.assertEqual(commands.fetch_project_listing_for_config(config, ".", runner), [{"path": "README.md", "kind": "file"}])
        self.assertEqual(calls[0], commands.build_project_tree_fetch_command_for_config(config, 2))
        self.assertEqual(calls[1], commands.build_project_listing_fetch_command_for_config(config, "."))

    def test_git_tracked_file_candidate_helpers_preserve_current_filters(self) -> None:
        config = sample_config()
        prepare_config(config)
        output = "\n".join(
            [
                " product.yaml ",
                "README.md",
                "doc/Dockerfile",
                "layers/meta.yml",
                "",
                "Dockerfile.debug",
                "tools/build.dockerfile",
            ]
        )

        self.assertEqual(
            commands.build_git_tracked_files_fetch_command_for_config(config),
            transport.ssh_command("builder@10.0.0.1", "cd /mnt/projects/meta-product && git ls-files"),
        )
        files = commands.parse_git_tracked_files(output)

        self.assertEqual(
            files,
            [
                "product.yaml",
                "README.md",
                "doc/Dockerfile",
                "layers/meta.yml",
                "Dockerfile.debug",
                "tools/build.dockerfile",
            ],
        )
        self.assertEqual(commands.root_yaml_candidates(files), ["product.yaml"])
        self.assertEqual(
            commands.dockerfile_candidates(files),
            ["doc/Dockerfile", "Dockerfile.debug", "tools/build.dockerfile"],
        )
        self.assertEqual(
            commands.fetch_git_tracked_files_for_config(config, lambda argv: output),
            files,
        )

    def test_git_branch_fetch_command_and_parser_match_current_shape(self) -> None:
        config = sample_config()
        prepare_config(config)
        output = "\n".join(
            [
                "abc refs/heads/mirror",
                "def refs/tags/v1",
                "ghi refs/heads/main",
                "jkl refs/heads/mirror",
            ]
        )

        self.assertEqual(
            commands.build_git_branch_list_fetch_command_for_config(config, "git@example:prod"),
            transport.ssh_command("builder@10.0.0.1", "git ls-remote --heads --refs git@example:prod"),
        )
        self.assertEqual(commands.parse_git_branch_list_output(output), ["main", "mirror"])
        self.assertEqual(
            commands.fetch_git_branches_for_config(config, "git@example:prod", lambda argv: output),
            ["main", "mirror"],
        )

    def test_validate_dockerfile_text_uses_first_non_comment_instruction(self) -> None:
        self.assertEqual(commands.validate_dockerfile_text("\n# comment\nFROM ubuntu:24.04\n"), (True, "FROM ubuntu:24.04"))
        self.assertEqual(commands.validate_dockerfile_text("\nARG BASE=ubuntu\nFROM $BASE\n"), (False, "first instruction is not FROM"))
        self.assertEqual(commands.validate_dockerfile_text("\n# only comments\n"), (False, "empty file"))

    def test_prepare_project_command_from_config_matches_low_level_builder(self) -> None:
        config = sample_config()
        prepare_config(config)

        self.assertEqual(
            commands.build_remote_prepare_project_command_for_config(config),
            commands.build_remote_prepare_project_command(
                config_accessors.remote_spec_for_config(config),
                config_accessors.remote_project_dir_for_config(config),
                config_accessors.project_git_url_for_config(config),
                config_accessors.project_git_ref_for_config(config),
            ),
        )

    def test_read_project_file_for_config_delegates_fetch_command_to_runner(self) -> None:
        config = sample_config()
        prepare_config(config)
        seen: list[list[str]] = []

        def runner(argv: list[str]) -> str:
            seen.append(argv)
            return "content\n"

        self.assertEqual(commands.read_project_file_for_config(config, "product.yaml", runner), "content\n")
        self.assertEqual(seen[0], commands.build_remote_project_file_read_command_for_config(config, "product.yaml"))

        reader = commands.project_file_reader(runner)
        self.assertEqual(reader(config, "other.yaml"), "content\n")
        self.assertEqual(seen[1], commands.build_remote_project_file_read_command_for_config(config, "other.yaml"))

    def test_docker_command_matches_current_shape(self) -> None:
        config = sample_config()
        prepare_config(config)
        docker_image = "prod_img"

        argv = commands.build_remote_docker_command_for_config(
            config,
            docker_image=docker_image,
            default_dockerfile=client.DEFAULT_DOCKERFILE,
        )

        self.assertEqual(argv[0], "ssh")
        self.assertIn("builder@10.0.0.1", argv)
        self.assertIn("cd /mnt/projects/meta-product && docker build doc -f doc/Dockerfile", argv[-1])
        self.assertIn("-t prod_img:latest", argv[-1])
        self.assertEqual(
            argv,
            commands.build_remote_docker_command(
                config_accessors.remote_spec_for_config(config),
                config_accessors.remote_project_dir_for_config(config),
                docker_image,
                config_accessors.configured_dockerfile_for_config(config),
            ),
        )

    def test_product_docker_command_preserves_mounts_and_inner_shell(self) -> None:
        command = commands.build_product_docker_command(
            "/mnt/projects/meta-product",
            "prod_img",
            "ninja boot_artifacts full_ufs.img.gz",
        )

        self.assertIn("--network=host --privileged", command)
        self.assertIn("-e PYTHONUNBUFFERED=1", command)
        self.assertIn("-v /mnt/projects/meta-product:/home/builder/workspace", command)
        self.assertIn(shlex.quote("cd /home/builder/workspace && ninja boot_artifacts full_ufs.img.gz"), command)

    def test_bazel_config_command_builds_requested_config_targets(self) -> None:
        config = sample_config()
        prepare_config(config)

        argv = commands.build_remote_bazel_config_command_for_config(
            config,
            docker_image="prod_img",
            targets="//common-modules/xen-virtual-device:xen_virtual_device_aarch64/.config",
        )

        self.assertEqual(argv[0], "ssh")
        self.assertIn("builder@10.0.0.1", argv)
        self.assertIn("cd /mnt/projects/meta-product && docker run", argv[-1])
        self.assertIn(
            "cd android_kernel && tools/bazel --max_idle_secs=1 build //common-modules/xen-virtual-device:xen_virtual_device_aarch64/.config",
            argv[-1],
        )
        self.assertIn("tools/bazel shutdown", argv[-1])
        self.assertIn("exit ${BUILD_RESULT}", argv[-1])

    def test_bazel_component_command_runs_manifest_builder_and_touches_outputs(self) -> None:
        config = sample_config()
        prepare_config(config)

        argv = commands.build_remote_bazel_component_command_for_config(
            config,
            docker_image="prod_img",
            component={
                "build_dir": "android_kernel",
                "tool": "tools/bazel",
                "command": "run",
                "args": ["--verbose_failures"],
                "target": "//common-modules/xen-virtual-device:xen_virtual_device_aarch64_dist",
                "target_patterns": [
                    "--destdir=../android/out/android_kernel/deploy/common-modules/xen-virtual-device/xen_virtual_device_aarch64"
                ],
                "target_images": [
                    "../android/out/android_kernel/deploy/common-modules/xen-virtual-device/xen_virtual_device_aarch64/Image"
                ],
            },
        )

        self.assertEqual(argv[0], "ssh")
        self.assertIn("builder@10.0.0.1", argv)
        self.assertIn(
            "cd android_kernel && tools/bazel --max_idle_secs=1 run --verbose_failures //common-modules/xen-virtual-device:xen_virtual_device_aarch64_dist -- --destdir=../android/out/android_kernel/deploy/common-modules/xen-virtual-device/xen_virtual_device_aarch64",
            argv[-1],
        )
        self.assertIn(
            "for p in ../android/out/android_kernel/deploy/common-modules/xen-virtual-device/xen_virtual_device_aarch64/Image",
            argv[-1],
        )
        self.assertIn("touch \"$p\"", argv[-1])
        self.assertIn("tools/bazel shutdown", argv[-1])
        self.assertIn("exit ${BUILD_RESULT}", argv[-1])

    def test_structured_script_api_is_used_directly(self) -> None:
        steps = [
            ("Project directory", "pwd"),
            ("Docker image", "docker image ls prod_img:latest"),
        ]

        expected = commands.build_structured_script(steps, fail_fast=False)

        self.assertIn("Project directory", expected)
        self.assertIn("docker image ls prod_img:latest", expected)

    def test_structured_script_preserves_current_shell_shape(self) -> None:
        script = commands.build_structured_script(
            [("Git status", "git status --short --branch")],
            fail_fast=True,
        )

        self.assertTrue(script.startswith("overall_rc=0; "))
        self.assertIn("printf '\\n== %s ==\\n' 'Git status'", script)
        self.assertIn("printf 'cmd: %s\\n' 'git status --short --branch'", script)
        self.assertIn("if [ \"$step_rc\" -ne 0 ]; then exit \"$step_rc\"; fi", script)
        self.assertTrue(script.endswith("exit \"$overall_rc\""))

    def test_moulin_and_build_commands_from_config_match_low_level_builders(self) -> None:
        config = sample_config()
        prepare_config(config)
        docker_image = "prod_img"
        build_params = {"ENABLE_ANDROID": "yes"}
        build_targets = "boot_artifacts full_ufs.img.gz"

        self.assertEqual(
            commands.build_remote_moulin_command_for_config(
                config,
                docker_image=docker_image,
                default_moulin_manifest=client.DEFAULT_MOULIN_MANIFEST,
                build_params=build_params,
            ),
            commands.build_remote_moulin_command(
                config_accessors.remote_spec_for_config(config),
                config_accessors.remote_project_dir_for_config(config),
                docker_image,
                config_accessors.moulin_manifest_name_for_config(config),
                build_params,
            ),
        )
        self.assertEqual(
            commands.build_remote_build_command_for_config(
                config,
                docker_image=docker_image,
                targets=build_targets,
            ),
            commands.build_remote_build_command(
                config_accessors.remote_spec_for_config(config),
                config_accessors.remote_project_dir_for_config(config),
                docker_image,
                build_targets,
            ),
        )

    def test_remote_run_helpers_delegate_built_commands_to_runner(self) -> None:
        config = sample_config()
        prepare_config(config)
        docker_image = "prod_img"
        build_params = {"ENABLE_ANDROID": "yes"}
        build_targets = "boot_artifacts"
        ran: list[list[str]] = []

        rc = commands.run_interactive_remote_shell_for_config(config, lambda argv: ran.append(argv) or 17)
        self.assertEqual(rc, 17)
        commands.run_remote_docker_for_config(
            config,
            docker_image=docker_image,
            default_dockerfile=client.DEFAULT_DOCKERFILE,
            runner=ran.append,
        )
        commands.run_remote_moulin_for_config(
            config,
            docker_image=docker_image,
            default_moulin_manifest=client.DEFAULT_MOULIN_MANIFEST,
            build_params=build_params,
            runner=ran.append,
        )
        commands.run_remote_build_for_config(
            config,
            docker_image=docker_image,
            targets=build_targets,
            runner=ran.append,
        )
        commands.run_remote_status_for_config(
            config,
            docker_image=docker_image,
            structured_script=lambda steps: commands.build_structured_script(steps, fail_fast=False),
            runner=ran.append,
        )

        self.assertEqual(ran[0], commands.build_interactive_remote_shell_command_for_config(config))
        self.assertEqual(ran[1], commands.build_remote_docker_command_for_config(config, docker_image=docker_image, default_dockerfile=client.DEFAULT_DOCKERFILE))
        self.assertEqual(
            ran[2],
            commands.build_remote_moulin_command_for_config(
                config,
                docker_image=docker_image,
                default_moulin_manifest=client.DEFAULT_MOULIN_MANIFEST,
                build_params=build_params,
            ),
        )
        self.assertEqual(ran[3], commands.build_remote_build_command_for_config(config, docker_image=docker_image, targets=build_targets))
        self.assertEqual(ran[4][0], "ssh")
        self.assertIn("builder@10.0.0.1", ran[4])
        self.assertIn("Docker image", ran[4][-1])

    def test_run_cli_remote_command_for_config_routes_build_commands(self) -> None:
        config = sample_config()
        prepare_config(config)
        runtime_context = {
            "docker_image": "prod_img",
            "build_params": {"ENABLE_ANDROID": "yes"},
            "build_targets": "boot_artifacts",
        }
        ran: list[list[str]] = []

        commands.run_cli_remote_command_for_config(
            config,
            "regen-moulin",
            runtime_context=lambda: runtime_context,
            default_dockerfile=client.DEFAULT_DOCKERFILE,
            default_moulin_manifest=client.DEFAULT_MOULIN_MANIFEST,
            structured_script=lambda steps: commands.build_structured_script(steps, fail_fast=False),
            runner=ran.append,
        )
        commands.run_cli_remote_command_for_config(
            config,
            "build",
            runtime_context=lambda: runtime_context,
            default_dockerfile=client.DEFAULT_DOCKERFILE,
            default_moulin_manifest=client.DEFAULT_MOULIN_MANIFEST,
            structured_script=lambda steps: commands.build_structured_script(steps, fail_fast=False),
            runner=ran.append,
        )

        self.assertEqual(
            ran[0],
            commands.build_remote_moulin_command_for_config(
                config,
                docker_image="prod_img",
                default_moulin_manifest=client.DEFAULT_MOULIN_MANIFEST,
                build_params={"ENABLE_ANDROID": "yes"},
            ),
        )
        self.assertEqual(ran[1], commands.build_remote_build_command_for_config(config, docker_image="prod_img", targets="boot_artifacts"))

    def test_run_cli_remote_command_for_config_routes_status_to_status_runner(self) -> None:
        config = sample_config()
        prepare_config(config)
        ran: list[list[str]] = []
        status_ran: list[list[str]] = []

        commands.run_cli_remote_command_for_config(
            config,
            "remote-status",
            runtime_context=lambda: {"docker_image": "prod_img", "build_params": {}, "build_targets": ""},
            default_dockerfile=client.DEFAULT_DOCKERFILE,
            default_moulin_manifest=client.DEFAULT_MOULIN_MANIFEST,
            structured_script=lambda steps: commands.build_structured_script(steps, fail_fast=False),
            runner=ran.append,
            status_runner=status_ran.append,
        )

        self.assertEqual(ran, [])
        self.assertEqual(status_ran[0][0], "ssh")
        self.assertIn("builder@10.0.0.1", status_ran[0])
        self.assertIn("Docker image", status_ran[0][-1])

    def test_run_cli_remote_command_for_config_routes_connect_without_runtime_context(self) -> None:
        config = sample_config()
        prepare_config(config)
        ran: list[list[str]] = []

        def runtime_context() -> dict[str, object]:
            raise AssertionError("runtime context should not be loaded for connect")

        commands.run_cli_remote_command_for_config(
            config,
            "connect",
            runtime_context=runtime_context,
            default_dockerfile=client.DEFAULT_DOCKERFILE,
            default_moulin_manifest=client.DEFAULT_MOULIN_MANIFEST,
            structured_script=lambda steps: commands.build_structured_script(steps, fail_fast=False),
            runner=ran.append,
        )

        self.assertEqual(ran, [commands.build_interactive_remote_shell_command_for_config(config)])


if __name__ == "__main__":
    unittest.main()
