from __future__ import annotations

import shlex
import unittest

import moulin_remote_client as client
from components.config.api import profiles as config_profiles
from components.remote.api import workflow
from components.remote.src.project import remote_project_maintenance_service
from components.remote.src.session import remote_session_command_service
from components.remote.test.command_adapter import commands

from components.remote.test.test_commands import sample_config


class RemoteCommandWorkflowServiceTests(unittest.TestCase):
    def test_session_commands_match_command_builders(self) -> None:
        config = sample_config()
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = self._service()

        self.assertIsInstance(service.session_service, commands.RemoteSessionCommandService)
        self.assertEqual(service.connect_command(config), commands.build_remote_connect_command_for_config(config))
        self.assertEqual(
            service.interactive_shell_command(config),
            commands.build_interactive_remote_shell_command_for_config(config),
        )

    def test_session_service_owns_connect_and_shell_use_cases(self) -> None:
        config = sample_config()
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = remote_session_command_service()
        calls: list[list[str]] = []

        self.assertEqual(service.connect_command_for_config(config), commands.build_remote_connect_command_for_config(config))
        self.assertEqual(
            service.interactive_shell_command_for_config(config),
            commands.build_interactive_remote_shell_command_for_config(config),
        )
        self.assertEqual(service.run_interactive_shell(config, lambda argv: calls.append(argv) or 31), 31)
        self.assertEqual(calls, [commands.build_interactive_remote_shell_command_for_config(config)])

    def test_project_repair_commands_match_command_builders(self) -> None:
        config = sample_config()
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = self._service()

        self.assertIsInstance(service.project_service, commands.RemoteProjectMaintenanceService)
        self.assertEqual(
            service.prepare_project_command(config),
            commands.build_remote_prepare_project_command_for_config(config),
        )
        clean_project = shlex.join(service.clean_project_folder_command(config))
        self.assertIn("Clean project folder", clean_project)
        self.assertIn("rm -rf", clean_project)
        self.assertIn("refusing to remove unsafe project directory", clean_project)
        self.assertEqual(
            service.checkout_git_ref_command(config),
            commands.build_remote_checkout_git_ref_command_for_config(config),
        )
        self.assertIn(
            "git stash push",
            shlex.join(service.stash_and_checkout_git_ref_command(config)),
        )
        stash_checkout = shlex.join(service.stash_and_checkout_git_ref_command(config))
        self.assertIn("git add -A", stash_checkout)
        self.assertIn("git diff --cached --quiet", stash_checkout)
        clear_lock = shlex.join(service.clear_git_index_lock_command(config))
        self.assertIn(".git/index.lock", clear_lock)
        self.assertIn("rm -f", clear_lock)
        repair_checkout = shlex.join(service.repair_and_checkout_git_ref_command(config))
        self.assertIn(".git/index.lock", repair_checkout)
        self.assertIn("rm -f", repair_checkout)
        self.assertIn("git add -A", repair_checkout)
        self.assertIn("git stash push", repair_checkout)
        self.assertIn("--include-untracked", repair_checkout)
        self.assertIn("git stash did not create a backup", repair_checkout)
        self.assertIn("working tree is still dirty", repair_checkout)
        self.assertIn("git reset --hard", repair_checkout)
        self.assertIn("git clean -fd", repair_checkout)
        self.assertIn("git checkout", repair_checkout)

    def test_project_maintenance_service_owns_prepare_checkout_and_preflight(self) -> None:
        config = sample_config()
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = remote_project_maintenance_service()

        self.assertEqual(
            service.prepare_project_command_for_config(config),
            commands.build_remote_prepare_project_command_for_config(config),
        )
        clean_project = shlex.join(service.clean_project_folder_command_for_config(config))
        self.assertIn("Clean project folder", clean_project)
        self.assertIn("rm -rf", clean_project)
        self.assertIn("refusing to remove unsafe project directory", clean_project)
        self.assertEqual(
            service.checkout_git_ref_command_for_config(config),
            commands.build_remote_checkout_git_ref_command_for_config(config),
        )
        self.assertIn(
            "git stash push",
            shlex.join(service.stash_and_checkout_git_ref_command_for_config(config)),
        )
        stash_checkout = shlex.join(service.stash_and_checkout_git_ref_command_for_config(config))
        self.assertIn("git add -A", stash_checkout)
        self.assertIn("git diff --cached --quiet", stash_checkout)
        clear_lock = shlex.join(service.clear_git_index_lock_command_for_config(config))
        self.assertIn(".git/index.lock", clear_lock)
        self.assertIn("rm -f", clear_lock)
        repair_checkout = shlex.join(service.repair_and_checkout_git_ref_command_for_config(config))
        self.assertIn(".git/index.lock", repair_checkout)
        self.assertIn("rm -f", repair_checkout)
        self.assertIn("git add -A", repair_checkout)
        self.assertIn("git stash push", repair_checkout)
        self.assertIn("--include-untracked", repair_checkout)
        self.assertIn("git stash did not create a backup", repair_checkout)
        self.assertIn("working tree is still dirty", repair_checkout)
        self.assertIn("git reset --hard", repair_checkout)
        self.assertIn("git clean -fd", repair_checkout)
        self.assertIn("git checkout", repair_checkout)
        self.assertEqual(
            service.preflight_command_for_config(config, "prod_img"),
            commands.build_remote_preflight_command_for_config(config, "prod_img"),
        )

    def test_build_commands_match_command_builders(self) -> None:
        config = sample_config()
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = self._service()

        self.assertIsInstance(service.build_service, commands.RemoteBuildCommandService)
        self.assertFalse(hasattr(service.build_service, "run_cli_remote_command_for_config"))
        self.assertFalse(hasattr(service.build_service, "planner"))
        self.assertFalse(hasattr(service.build_service, "prepare_project_command_for_config"))
        self.assertFalse(hasattr(service.build_service, "checkout_git_ref_command_for_config"))
        self.assertFalse(hasattr(service.build_service, "preflight_command_for_config"))
        self.assertEqual(
            service.docker_image_command(config, docker_image="prod_img"),
            commands.build_remote_docker_command_for_config(
                config,
                docker_image="prod_img",
                default_dockerfile=client.DEFAULT_DOCKERFILE,
            ),
        )
        components = [{"name": "domd", "builder_type": "yocto", "build_dir": "yocto", "work_dir": "build-domd"}]
        self.assertEqual(
            service.bitbake_cleanup_command(config, docker_image="prod_img", components=components),
            commands.build_remote_bitbake_cleanup_command_for_config(
                config,
                docker_image="prod_img",
                components=components,
            ),
        )
        self.assertEqual(
            service.moulin_regen_command(
                config,
                docker_image="prod_img",
                build_params={"ENABLE_ANDROID": "yes"},
            ),
            commands.build_remote_moulin_command_for_config(
                config,
                docker_image="prod_img",
                default_moulin_manifest=client.DEFAULT_MOULIN_MANIFEST,
                build_params={"ENABLE_ANDROID": "yes"},
            ),
        )
        self.assertEqual(
            service.product_build_command(
                config,
                docker_image="prod_img",
                targets="boot_artifacts full_ufs.img.gz",
            ),
            commands.build_remote_build_command_for_config(
                config,
                docker_image="prod_img",
                targets="boot_artifacts full_ufs.img.gz",
            ),
        )
        yocto_impact = service.yocto_impact_command(
            config,
            docker_image="prod_img",
            targets="boot_artifacts full_ufs.img.gz",
        )
        self.assertIn("-e PYTHONUNBUFFERED=1", yocto_impact[-1])
        self.assertIn("python3 -u - <<", yocto_impact[-1])
        self.assertIn("Impacted Yocto recipes", yocto_impact[-1])
        self.assertIn('ACTION = "analyze"', yocto_impact[-1])
        self.assertIn("[progress] step", yocto_impact[-1])
        self.assertIn("[progress] still running", yocto_impact[-1])
        self.assertIn("available_by_build_dir", yocto_impact[-1])
        self.assertIn("scan available recipes in", yocto_impact[-1])
        self.assertIn("elapsed:", yocto_impact[-1])
        self.assertIn("== yocto impact {ACTION} ==", yocto_impact[-1])
        self.assertIn('BUILD_DIRS = "".strip().split()', yocto_impact[-1])
        self.assertIn('ALLOW_EMPTY = "0" == "1"', yocto_impact[-1])
        self.assertIn('USE_CHANGED_FILES = "0" == "1"', yocto_impact[-1])
        self.assertIn(
            'BUILD_DIRS = "yocto/build-dom0".strip().split()',
            service.yocto_impact_command(
                config,
                docker_image="prod_img",
                targets="core-image-thin-initramfs",
                build_dirs=["yocto/build-dom0"],
            )[-1],
        )
        explicit_scope_impact = service.yocto_impact_command(
            config,
            docker_image="prod_img",
            targets="core-image-thin-initramfs",
            image_recipes=["core-image-thin-initramfs"],
            build_dirs=["yocto/build-dom0"],
        )[-1]
        self.assertIn("explicit_recipe_scope = bool(BUILD_DIRS and IMAGE_RECIPES)", explicit_scope_impact)
        self.assertIn("elif (recipes or IMAGE_RECIPES) and build_dirs:", explicit_scope_impact)
        self.assertIn(
            'IMAGE_RECIPES = "core-image-thin-initramfs".strip().split()',
            explicit_scope_impact,
        )
        changed_file_impact = service.yocto_impact_command(
            config,
            docker_image="prod_img",
            targets="core-image-thin-initramfs",
            changed_files=["layers/meta-xt-dom0-gen5/recipes-guests/domu/domu.bbappend"],
        )[-1]
        self.assertIn('USE_CHANGED_FILES = "1" == "1"', changed_file_impact)
        self.assertIn("CHANGED_FILES = json.loads", changed_file_impact)
        self.assertIn(
            'ALLOW_EMPTY = "1" == "1"',
            service.yocto_impact_command(
                config,
                docker_image="prod_img",
                targets="boot_artifacts full_ufs.img.gz",
                action="clean",
                allow_empty=True,
            )[-1],
        )
        self.assertIn(
            'ACTION = "clean-rebuild"',
            service.yocto_impact_command(
                config,
                docker_image="prod_img",
                targets="boot_artifacts full_ufs.img.gz",
                action="clean-rebuild",
            )[-1],
        )
        config_profiles.active_project(config)["yocto_image_recipes"] = "rcar-image-adas xt-rcar-image"
        yocto_clean_rebuild = service.yocto_impact_command(
            config,
            docker_image="prod_img",
            targets="boot_artifacts full_ufs.img.gz",
            action="clean-rebuild",
        )[-1]
        self.assertIn('IMAGE_RECIPES = "rcar-image-adas xt-rcar-image".strip().split()', yocto_clean_rebuild)
        self.assertIn("Configured Yocto image recipes", yocto_clean_rebuild)
        self.assertIn("cleansstate images", yocto_clean_rebuild)
        self.assertIn("rebuild images", yocto_clean_rebuild)

    def test_workflow_owns_cli_remote_command_routing(self) -> None:
        config = sample_config()
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = self._service()
        calls: list[list[str]] = []
        context = {
            "docker_image": "prod_img",
            "build_params": {"ENABLE_ANDROID": "yes"},
            "build_targets": "boot_artifacts full_ufs.img.gz",
        }

        service.run_cli_command(
            config,
            "regen-moulin",
            runtime_context=lambda: context,
            structured_script=commands.build_structured_script,
            runner=lambda argv: calls.append(argv),
        )

        self.assertEqual(
            calls,
            [
                service.moulin_regen_command(
                    config,
                    docker_image="prod_img",
                    build_params={"ENABLE_ANDROID": "yes"},
                )
            ],
        )

    def test_workflow_routes_bitbake_cleanup_to_build_host_command(self) -> None:
        config = sample_config()
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = self._service()
        calls: list[list[str]] = []
        context = {
            "docker_image": "prod_img",
            "build_params": {"ENABLE_ANDROID": "yes"},
            "build_targets": "boot_artifacts full_ufs.img.gz",
            "component_builders": [{"name": "domd", "builder_type": "yocto", "build_dir": "yocto", "work_dir": "build-domd"}],
        }

        service.run_cli_command(
            config,
            "cleanup-bitbake",
            runtime_context=lambda: context,
            structured_script=commands.build_structured_script,
            runner=lambda argv: calls.append(argv),
        )

        self.assertEqual(
            calls,
            [
                service.bitbake_cleanup_command(
                    config,
                    docker_image="prod_img",
                    components=[{"name": "domd", "builder_type": "yocto", "build_dir": "yocto", "work_dir": "build-domd"}],
                )
            ],
        )

    def test_workflow_routes_yocto_impact_to_build_host_command(self) -> None:
        config = sample_config()
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = self._service()
        calls: list[list[str]] = []
        context = {
            "docker_image": "prod_img",
            "build_params": {"ENABLE_ANDROID": "yes"},
            "build_targets": "boot_artifacts full_ufs.img.gz",
        }

        service.run_cli_command(
            config,
            "yocto-impact",
            runtime_context=lambda: context,
            structured_script=commands.build_structured_script,
            runner=lambda argv: calls.append(argv),
        )

        self.assertEqual(
            calls,
            [
                service.yocto_impact_command(
                    config,
                    docker_image="prod_img",
                    targets="boot_artifacts full_ufs.img.gz",
                )
            ],
        )

    def test_workflow_routes_yocto_impact_action_commands(self) -> None:
        config = sample_config()
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = self._service()
        context = {
            "docker_image": "prod_img",
            "build_params": {"ENABLE_ANDROID": "yes"},
            "build_targets": "boot_artifacts full_ufs.img.gz",
        }
        expected_actions = {
            "yocto-impact-clean": "clean",
            "yocto-impact-rebuild": "rebuild",
            "yocto-impact-clean-rebuild": "clean-rebuild",
        }

        for command, action in expected_actions.items():
            with self.subTest(command=command):
                calls: list[list[str]] = []

                service.run_cli_command(
                    config,
                    command,
                    runtime_context=lambda: context,
                    structured_script=commands.build_structured_script,
                    runner=lambda argv: calls.append(argv),
                )

                self.assertEqual(
                    calls,
                    [
                        service.yocto_impact_command(
                            config,
                            docker_image="prod_img",
                            targets="boot_artifacts full_ufs.img.gz",
                            action=action,
                        )
                    ],
                )

    def test_workflow_routes_connect_without_runtime_context(self) -> None:
        config = sample_config()
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = self._service()
        calls: list[list[str]] = []

        service.run_cli_command(
            config,
            "connect",
            runtime_context=lambda: (_ for _ in ()).throw(AssertionError("runtime context should not be read")),
            structured_script=commands.build_structured_script,
            runner=lambda argv: calls.append(argv),
        )

        self.assertEqual(calls, [service.interactive_shell_command(config)])

    def _service(self) -> workflow.RemoteCommandWorkflowService:
        return workflow.remote_command_workflow_service(
            default_dockerfile=client.DEFAULT_DOCKERFILE,
            default_moulin_manifest=client.DEFAULT_MOULIN_MANIFEST,
        )


if __name__ == "__main__":
    unittest.main()
