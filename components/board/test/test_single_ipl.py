from __future__ import annotations

import curses
import importlib.util
import io
import json
import shlex
from pathlib import Path
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from components.board.api import workflow
from components.board.test.test_commands import sample_config
from components.config.api import profiles
from components.main_menu.src.commands import MainMenuCommandItemsService


ROOT = Path(__file__).resolve().parents[3]


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'board_tools' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SingleIplTests(unittest.TestCase):
    def setUp(self):
        self.helper = load_tool('gen5_x5h_flash_ipl')
        self.flasher = load_tool('ipl_ufs_flash')
        self.uboot = load_tool('gen5_x5h_uboot')

    def make_archive(self, directory):
        path = directory / 'boot-artifacts.tar.gz'
        config = b'images:\n- {name: test.srec, target: UFS, flash_addr: "0x1000"}\n- {name: other.srec, target: QSPI, flash_addr: "0x0"}\n'
        with tarfile.open(path, 'w:gz') as archive:
            for name, data in [('x5h_bootloaders.yaml', config), ('test.srec', b'SREC'), ('other.srec', b'OTHER')]:
                info = tarfile.TarInfo('boot/build-domd/ipls/' + name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        return path

    def test_archive_lists_only_ufs_files_and_rejects_ambiguous_archives(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.make_archive(root)
            with tarfile.open(path) as archive:
                _, images = self.helper.archive_images(archive)
            self.assertEqual(images, [{'name': 'test.srec', 'flash_addr': '0x1000'}])
            self.assertEqual(self.helper.find_archive(root), path)
            (root / 'old-boot-artifacts.tar').touch()
            with self.assertRaises(ValueError):
                self.helper.find_archive(root)

    def test_wrapper_extracts_selected_file_and_cleans_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = self.make_archive(root)
            listing = self.helper.prepare_ipls(root, archive)
            def check_run(command, **kwargs):
                staging = Path(command[command.index('--tftp') + 1])
                self.assertEqual((staging / 'test.srec').read_bytes(), b'SREC')
                self.assertFalse((staging / 'other.srec').exists())
                self.assertEqual(staging.stat().st_mode & 0o777, 0o755)
                self.assertEqual(command[command.index('--tftp-prefix') + 1], staging.name)
                self.assertTrue(kwargs['check'])
            argv = ['helper', '--ipls-dir', listing['ipls_dir'], '--name', 'test.srec',
                    '--port', '/dev/test', '--tftp-root', str(root), '--tftp-dir', str(root)]
            with patch.object(sys, 'argv', argv), \
                    patch.object(self.helper.subprocess, 'run', side_effect=check_run) as run:
                self.helper.main()
            self.assertFalse(hasattr(self.helper, 'prepare_uboot'))
            self.assertEqual(run.call_count, 2)
            self.assertIn('--check', run.call_args_list[0].args[0])
            self.assertNotIn('--check', run.call_args_list[1].args[0])
            self.assertEqual(list(root.glob('ipl-flash-*')), [])

    def test_flasher_pads_blocks_uses_prefix_and_closes_serial(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'input.bin').write_bytes(b'ABC')
            (root / 'config.yaml').write_text('images:\n- {name: test.srec, target: UFS, flash_addr: "0x1000"}\n')
            argv = ['flasher', '--port', '/dev/test', '--config', str(root / 'config.yaml'),
                    '--name', 'test.srec', '--format', 'bin', '--file', str(root / 'input.bin'),
                    '--tftp', str(root), '--tftp-prefix', 'user/project']
            commands = []
            def command_run(conn, command, ok=None):
                commands.append(command)
                if command.startswith('tftp '):
                    self.assertEqual((root / 'ipl-flash-test.bin').read_bytes(), b'ABC' + bytes(4093))
            with patch.object(sys, 'argv', argv), patch.object(self.flasher.serial, 'Serial') as serial, \
                    patch.object(self.flasher, 'uboot_wait_for'), \
                    patch.object(self.flasher, 'uboot_cmd_run', side_effect=command_run):
                self.flasher.main()
            self.assertIn('tftp 0x50000000 user/project/ipl-flash-test.bin', commands)
            self.assertEqual(commands[-1], 'scsi write 0x50000000 0x1 0x1')
            serial.return_value.close.assert_called_once()
            self.assertFalse((root / 'ipl-flash-test.bin').exists())

    def test_subset_prechecks_every_image_and_stops_on_first_flash_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            listing = self.helper.prepare_ipls(root, self.make_archive(root))
            snapshot = Path(listing['ipls_dir'])
            config = snapshot / 'x5h_bootloaders.yaml'
            config.write_text(config.read_text() +
                              '- {name: second.srec, target: UFS, flash_addr: "0x2000"}\n' +
                              '- {name: third.srec, target: UFS, flash_addr: "0x3000"}\n')
            (snapshot / 'second.srec').write_bytes(b'SREC')
            (snapshot / 'third.srec').write_bytes(b'SREC')
            argv = ['helper', '--ipls-dir', str(snapshot), '--name', 'third.srec',
                    '--name', 'test.srec', '--name', 'second.srec', '--port', '/dev/test',
                    '--tftp-root', str(root), '--tftp-dir', str(root)]
            calls = []

            def run(command, **_kwargs):
                name = command[command.index('--name') + 1]
                calls.append((name, '--check' in command))
                if '--check' not in command and name == 'second.srec':
                    raise self.helper.subprocess.CalledProcessError(1, command)

            with patch.object(sys, 'argv', argv), patch.object(self.helper.subprocess, 'run', side_effect=run):
                with self.assertRaises(self.helper.subprocess.CalledProcessError):
                    self.helper.main()
            self.assertEqual(calls, [('test.srec', True), ('second.srec', True), ('third.srec', True),
                                     ('test.srec', False), ('second.srec', False)])
            self.assertEqual(list(root.glob('ipl-flash-*')), [])
            calls.clear()
            with patch.object(sys, 'argv', argv + ['--check']), \
                    patch.object(self.helper.subprocess, 'run', side_effect=run):
                self.helper.main()
            self.assertEqual(calls, [('test.srec', True), ('second.srec', True), ('third.srec', True)])
            with patch.object(sys, 'argv', argv), patch.object(self.helper.subprocess, 'run') as success:
                self.helper.main()
            self.assertEqual([call.args[0][call.args[0].index('--name') + 1]
                              for call in success.call_args_list],
                             ['test.srec', 'second.srec', 'third.srec'] * 2)
            failure = self.helper.subprocess.CalledProcessError(1, ['precheck'])
            with patch.object(sys, 'argv', argv), \
                    patch.object(self.helper.subprocess, 'run', side_effect=[None, failure]) as check:
                with self.assertRaises(self.helper.subprocess.CalledProcessError):
                    self.helper.main()
            self.assertEqual(check.call_count, 2)
            self.assertTrue(all('--check' in call.args[0] for call in check.call_args_list))

    def test_flasher_check_never_opens_serial(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'test.srec').write_text('S106100041424323\n')
            config = root / 'config.yaml'
            config.write_text('images:\n- {name: test.srec, target: UFS, flash_addr: "0x1000"}\n')
            argv = ['flasher', '--port', '/dev/test', '--config', str(config), '--name', 'test.srec', '--check']
            with patch.object(sys, 'argv', argv), patch.object(self.flasher.serial, 'Serial') as serial:
                self.flasher.main()
            serial.assert_not_called()

    def test_command_plan_discovers_without_serial_and_flashes_only_selected(self):
        config = sample_config()
        profiles.normalize_board_host_profiles(config)
        profiles.active_board_host(config).update(board_ip='10.0.0.2', server_ip='10.0.0.1')
        service = workflow.board_command_workflow_service(
            app_dir=ROOT, default_moulin_manifest='product.yaml',
            flash_bootloaders_tool=ROOT / 'board_tools/flash_bootloaders.py',
            xt_imager_tool=ROOT / 'board_tools/xt-imager.py',
            remote_read_project_file=lambda *_: '', manifest_cache={},
        )
        discovery = service.board_action_commands(config, 'flash_single_ipl')
        self.assertEqual(len(discovery), 1)
        self.assertIn('--artifacts', discovery[-1][-1])
        discovery_script = shlex.split(discovery[-1][-1])
        self.assertEqual(discovery_script[-2], '--artifacts')
        commands = service.board_action_commands(config, 'flash_single_ipl', build_params={
            '_ipl_name': 'test.srec', '_ipl_snapshot': '/tmp/ipls',
        })
        self.assertIn('--name test.srec', commands[-1][-1])
        self.assertIn('--ipls-dir /tmp/ipls', commands[-1][-1])
        self.assertEqual(len(commands), 5)
        self.assertIn('--power-off-command x5h_off', commands[-2][-1])
        self.assertIn('--boot-mode-command x5h_boot', commands[-2][-1])
        self.assertIn('--power-on-command x5h_on', commands[-2][-1])
        self.assertIn('--ipaddr', commands[-2][-1])
        self.assertIn('--serverip', commands[-2][-1])
        self.assertNotIn('--power-off-command', commands[-1][-1])
        subset = service.board_action_commands(config, 'flash_single_ipl', build_params={
            '_ipl_names': json.dumps(['test.srec', 'second.srec']), '_ipl_snapshot': '/tmp/ipls',
        })
        self.assertIn('--name test.srec --name second.srec', subset[-1][-1])
        self.assertEqual(sum('--power-off-command' in command[-1] for command in subset), 1)
        self.assertLess(subset[-2][-1].index('--check'), subset[-2][-1].index('--power-off-command'))
        profiles.active_board_host(config)['board_ip'] = ''
        commands = service.board_action_commands(config, 'flash_single_ipl', build_params={
            '_ipl_name': 'test.srec', '_ipl_snapshot': '/tmp/ipls',
        })
        script = shlex.split(commands[-2][-1])[-1]
        args = shlex.split(script)
        # Ignore the embedded Python source when inspecting actual CLI options.
        options = args[args.index('-c') + 2:]
        self.assertNotIn('--ipaddr', options)
        self.assertIn('--serverip', options)
        profiles.active_board_host(config)['board_ip'] = 'invalid'
        with self.assertRaisesRegex(ValueError, 'valid IPv4'):
            service.board_action_commands(config, 'flash_single_ipl', build_params={
                '_ipl_name': 'test.srec', '_ipl_snapshot': '/tmp/ipls',
            })


    def test_discovery_does_not_invoke_flasher(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.make_archive(Path(directory))
            self.helper.prepare_ipls(Path(directory), archive)
            archive.unlink()
            with patch.object(sys, 'argv', ['helper', '--artifacts', directory]), \
                    patch.object(self.helper.tarfile, 'open', side_effect=AssertionError('archive scanned')), \
                    patch.object(self.helper.subprocess, 'run') as run, \
                    patch('sys.stdout', new_callable=io.StringIO) as output:
                self.helper.main()
            self.assertEqual(json.loads(output.getvalue())['images'][0]['name'], 'test.srec')
            run.assert_not_called()

    def test_srec_conversion_and_checksum_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.srec'
            path.write_text('S106100041424323\n')
            self.assertEqual(self.flasher.srec_to_bin(path), b'ABC')
            path.write_text('S106100041424300\n')
            with self.assertRaises(SystemExit):
                self.flasher.srec_to_bin(path)

    def test_missing_prepared_ipls_fail_without_archive_access(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(self.helper.tarfile, 'open') as open_archive:
            with self.assertRaisesRegex(ValueError, 'Copy build artifacts'):
                self.helper.prepared_listing(Path(directory))
            open_archive.assert_not_called()

    def test_listing_does_not_fall_back_to_old_extracted_boot_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ipls = root / 'ironhide-boot-artifacts/build-domd/ipls'
            ipls.mkdir(parents=True)
            (ipls / 'x5h_bootloaders.yaml').write_text('images:\n- {name: existing.srec, target: UFS, flash_addr: "0x1000"}\n')
            (ipls / 'existing.srec').write_bytes(b'SREC')
            with patch.object(self.helper.tarfile, 'open', side_effect=AssertionError('archive scanned')):
                with self.assertRaisesRegex(ValueError, 'Copy build artifacts'):
                    self.helper.prepared_listing(root)

    def test_listing_reads_yaml_and_actual_files_without_saved_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = self.make_archive(root)
            listing = self.helper.prepare_ipls(root, archive)
            snapshot = Path(listing['ipls_dir'])
            (snapshot / 'source.json').unlink()
            (snapshot / 'index.json').write_text('invalid stale index')
            with patch.object(self.helper.tarfile, 'open', side_effect=AssertionError('archive scanned')):
                fresh = self.helper.prepared_listing(ipls_dir=snapshot)
                self.assertEqual(fresh['images'], [{'name': 'test.srec', 'flash_addr': '0x1000'}])
                (snapshot / 'test.srec').unlink()
                with self.assertRaisesRegex(ValueError, 'missing: test.srec'):
                    self.helper.prepared_listing(ipls_dir=snapshot)
                (snapshot / 'test.srec').write_bytes(b'SREC')
                config = snapshot / 'x5h_bootloaders.yaml'
                config.write_text(config.read_text() + '- {name: added.srec, target: UFS, flash_addr: "0x2000"}\n')
                (snapshot / 'added.srec').write_bytes(b'NEW')
                self.assertEqual(self.helper.prepared_listing(ipls_dir=snapshot)['images'],
                                 [{'name': 'test.srec', 'flash_addr': '0x1000'},
                                  {'name': 'added.srec', 'flash_addr': '0x2000'}])

    def test_prepare_reuses_unchanged_snapshot_and_preserves_it_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = self.make_archive(root)
            old = self.helper.prepare_ipls(root, archive)
            with patch.object(self.helper.tarfile, 'open', side_effect=AssertionError('archive scanned')):
                self.assertEqual(self.helper.prepare_ipls(root, archive), old)
            archive.write_bytes(b'not a tar file')
            with self.assertRaises(tarfile.TarError):
                self.helper.prepare_ipls(root, archive)
            self.assertEqual(self.helper.prepared_listing(root), old)
            self.assertEqual(len(list((root / '.moulin-ipls').glob('snapshot-*'))), 1)

    def test_recopy_does_not_replace_an_existing_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = self.make_archive(root)
            old = self.helper.prepare_ipls(root, archive)
            self.make_archive(root)
            new = self.helper.prepare_ipls(root, archive)
            self.assertNotEqual(old['ipls_dir'], new['ipls_dir'])
            self.assertEqual(self.helper.prepared_listing(root), new)
            self.assertEqual(self.helper.prepared_listing(ipls_dir=Path(old['ipls_dir'])), old)


    def preparation_args(self):
        return SimpleNamespace(port='/dev/test', ipaddr='10.0.0.2', serverip='10.0.0.1',
                               power_off_command='off', boot_mode_command='boot', power_on_command='on')

    def test_board_actions_use_the_same_uboot_helper_source(self):
        config = sample_config()
        profiles.normalize_board_host_profiles(config)
        profiles.active_board_host(config)['board_ip'] = '10.0.0.2'
        service = workflow.board_command_workflow_service(
            app_dir=ROOT, default_moulin_manifest='product.yaml',
            flash_bootloaders_tool=ROOT / 'board_tools/flash_bootloaders.py',
            xt_imager_tool=ROOT / 'board_tools/xt-imager.py',
            remote_read_project_file=lambda *_: '', manifest_cache={},
        )
        source = (ROOT / 'board_tools/gen5_x5h_uboot.py').read_text()
        for action in ('restart_board', 'open_uboot_console', 'apply_uboot_network_env',
                       'apply_uboot_ufs_env', 'inject_invasive_uboot_parameters'):
            with self.subTest(action=action):
                command = service.board_action_commands(config, action)[-1]
                script = shlex.split(command[-1])[-1]
                args = shlex.split(script)
                embedded = args[args.index('-c') + 1]
                self.assertEqual(embedded, source)
                compile(embedded, 'shared-uboot', 'exec')

    def test_shared_helper_can_apply_environment_then_start_boot(self):
        args = self.preparation_args()
        args.ipaddr = args.serverip = None
        args.require_variable = args.verify_variable = 'user_test'
        args.command = ["setenv user_test 'run bootcmd_moulin'", 'saveenv']
        args.boot_command = 'run user_test'
        with patch.object(self.uboot.serial, 'Serial') as serial, \
                patch.object(self.uboot.subprocess, 'run'), patch.object(self.uboot.time, 'sleep'):
            conn = serial.return_value.__enter__.return_value
            conn.read.side_effect = [b'=> ', b'user_test=old\r\n=> ', b'=> ', b'=> ',
                                     b'user_test=run bootcmd_moulin\r\n=> ']
            self.uboot.prepare_uboot(args)
        self.assertEqual([call.args[0] for call in conn.write.call_args_list], [
            b'printenv user_test\r', b"setenv user_test 'run bootcmd_moulin'\r",
            b'saveenv\r', b'printenv user_test\r', b'run user_test\r',
        ])

    def test_network_preparation_preserves_uboot_environment_when_ips_are_empty(self):
        args = self.preparation_args()
        args.ipaddr = args.serverip = ''
        with patch.object(self.uboot.serial, 'Serial') as serial, \
                patch.object(self.uboot.subprocess, 'run'), patch.object(self.uboot.time, 'sleep'):
            conn = serial.return_value.__enter__.return_value
            conn.read.return_value = b'=> '
            self.uboot.prepare_uboot(args)
        conn.write.assert_not_called()

    def test_network_preparation_overrides_only_the_explicit_ip(self):
        args = self.preparation_args()
        args.ipaddr = ''
        with patch.object(self.uboot.serial, 'Serial') as serial, \
                patch.object(self.uboot.subprocess, 'run'), patch.object(self.uboot.time, 'sleep'):
            conn = serial.return_value.__enter__.return_value
            conn.read.side_effect = [b'=> ', b'=> ', b'serverip=10.0.0.1\r\n=> ']
            self.uboot.prepare_uboot(args)
        self.assertEqual([call.args[0] for call in conn.write.call_args_list],
                         [b'setenv serverip 10.0.0.1\r', b'printenv serverip\r'])

    def test_preparation_power_cycles_and_verifies_temporary_network_settings(self):
        with patch.object(self.uboot.serial, 'Serial') as serial, \
                patch.object(self.uboot.subprocess, 'run') as run, \
                patch.object(self.uboot.time, 'sleep'):
            conn = serial.return_value.__enter__.return_value
            conn.read.side_effect = [b'Hit any key to stop autoboot: 1', b'\r\n=> ',
                                     b'\r\n=> ', b'ipaddr=10.0.0.2\r\n=> ',
                                     b'\r\n=> ', b'serverip=10.0.0.1\r\n=> ']
            self.uboot.prepare_uboot(self.preparation_args())
        serial.assert_called_once_with('/dev/test', 1843200, timeout=0.1, exclusive=True)
        self.assertEqual([call.args[0][-1].splitlines()[-1] for call in run.call_args_list], ['off', 'boot', 'on'])
        writes = [call.args[0] for call in conn.write.call_args_list]
        self.assertEqual(writes, [b'\r', b'setenv ipaddr 10.0.0.2\r', b'printenv ipaddr\r',
                                  b'setenv serverip 10.0.0.1\r', b'printenv serverip\r'])
        self.assertFalse(any(b'saveenv' in command for command in writes))
        serial.return_value.__exit__.assert_called_once()

    def test_preparation_rejects_invalid_ips_before_board_access(self):
        args = self.preparation_args()
        args.ipaddr = '10.0.0.2; reset'
        with patch.object(self.uboot.serial, 'Serial') as serial:
            with self.assertRaises(ValueError):
                self.uboot.prepare_uboot(args)
            serial.assert_not_called()

    def test_preparation_rejects_unverified_network_settings(self):
        with patch.object(self.uboot.serial, 'Serial') as serial, \
                patch.object(self.uboot.subprocess, 'run'), patch.object(self.uboot.time, 'sleep'):
            conn = serial.return_value.__enter__.return_value
            conn.read.side_effect = [b'=> ', b'=> ', b'ipaddr=10.0.0.99\r\n=> ']
            with self.assertRaisesRegex(RuntimeError, 'did not accept ipaddr'):
                self.uboot.prepare_uboot(self.preparation_args())
        serial.return_value.__exit__.assert_called_once()

    def test_autoboot_wait_has_total_timeout(self):
        conn = Mock()
        conn.read.return_value = b''
        with patch.object(self.uboot.time, 'monotonic', side_effect=[0, 0, 1, 46]):
            with self.assertRaises(TimeoutError):
                self.uboot.wait_uboot_prompt(conn, interrupt=True)
        conn.write.assert_called_once_with(b'\r')

    def test_power_failure_stops_preparation_before_uboot_commands(self):
        error = self.uboot.subprocess.CalledProcessError(1, ['off'])
        with patch.object(self.uboot.serial, 'Serial') as serial, \
                patch.object(self.uboot.subprocess, 'run', side_effect=error) as run:
            with self.assertRaises(self.uboot.subprocess.CalledProcessError):
                self.uboot.prepare_uboot(self.preparation_args())
        run.assert_called_once()
        serial.return_value.__enter__.return_value.write.assert_not_called()
        serial.return_value.__exit__.assert_called_once()


class SingleIplMenuTests(unittest.TestCase):
    def setUp(self):
        self.service = MainMenuCommandItemsService.__new__(MainMenuCommandItemsService)
        self.app = Mock()
        self.app.config = {}
        self.app.build_params = {}
        self.app.screen.getmaxyx.return_value = (24, 100)
        self.images = [{'name': 'first.srec', 'flash_addr': '0x0'},
                       {'name': 'second.srec', 'flash_addr': '0x1000'}]

    def test_submenu_selects_with_arrows_and_restores_timeout(self):
        self.app.read_key.side_effect = [ord(' '), curses.KEY_DOWN, 10]
        self.assertEqual(self.service.select_ipl_image(self.app, self.images), [self.images[1]])
        self.app.screen.timeout.assert_called_with(1000)

    def test_submenu_escape_cancels(self):
        self.app.read_key.return_value = 27
        self.assertIsNone(self.service.select_ipl_image(self.app, self.images))

    def test_submenu_defaults_to_all_yaml_images(self):
        self.app.read_key.return_value = 10
        self.assertEqual(self.service.select_ipl_image(self.app, self.images), self.images)

    def test_submenu_all_and_none_controls(self):
        self.app.read_key.side_effect = [ord('n'), 10]
        self.assertEqual(self.service.select_ipl_image(self.app, self.images), [])
        self.app.read_key.side_effect = [ord('n'), ord('a'), 10]
        self.assertEqual(self.service.select_ipl_image(self.app, self.images), self.images)

    def test_missing_ipls_do_not_open_submenu_or_start_a_job(self):
        self.service.board_action_commands = Mock(return_value=[['discovery']])
        self.app.remote_capture_command.side_effect = RuntimeError('IPLs not prepared; Copy build artifacts')
        self.service.select_ipl_image = Mock()
        self.service.run_single_ipl_menu(self.app)
        self.service.select_ipl_image.assert_not_called()
        self.app.command_workflow_service.assert_not_called()
        message = self.app.dialog_workflow_controller.return_value.show_message.call_args
        self.assertIn('Copy build artifacts', message.args[2][0])

    def test_discovery_error_shows_stderr_instead_of_embedded_ssh_command(self):
        import subprocess
        self.service.board_action_commands = Mock(return_value=[['discovery']])
        self.app.remote_capture_command.side_effect = subprocess.CalledProcessError(
            1, ['ssh', 'large embedded command'], stderr='Error: IPLs are not prepared. Copy build artifacts.')
        self.service.run_single_ipl_menu(self.app)
        message = self.app.dialog_workflow_controller.return_value.show_message.call_args
        self.assertEqual(message.args[2], ['Error: IPLs are not prepared. Copy build artifacts.'])

    def test_confirmed_selection_binds_archive_and_name(self):
        self.service.board_action_commands = Mock(return_value=[['discovery']])
        self.app.remote_capture_command.return_value = json.dumps({'archive': '/tmp/boot.tar', 'ipls_dir': '/tmp/ipls', 'images': self.images})
        self.service.select_ipl_image = Mock(return_value=[self.images[1]])
        self.service.board_command_workflow = Mock()
        self.app.dialog_workflow_controller.return_value.run_confirm_dialog.return_value = True
        self.service.run_single_ipl_menu(self.app)
        params = self.service.board_command_workflow.board_action_commands.call_args.kwargs['build_params']
        self.assertEqual(json.loads(params['_ipl_names']), ['second.srec'])
        self.assertEqual(params['_ipl_snapshot'], '/tmp/ipls')
        self.app.command_workflow_service.return_value.run_commands.assert_called_once()

    def test_cancelled_confirmation_does_not_flash(self):
        self.service.board_action_commands = Mock(return_value=[['discovery']])
        self.app.remote_capture_command.return_value = json.dumps({'archive': '/tmp/boot.tar', 'ipls_dir': '/tmp/ipls', 'images': self.images})
        self.service.select_ipl_image = Mock(return_value=[self.images[0]])
        self.service.board_command_workflow = Mock()
        self.app.dialog_workflow_controller.return_value.run_confirm_dialog.return_value = False
        self.service.run_single_ipl_menu(self.app)
        self.app.command_workflow_service.assert_not_called()

    def test_invalid_network_override_is_reported_before_confirmation_or_job(self):
        self.service.board_action_commands = Mock(return_value=[['discovery']])
        self.app.remote_capture_command.return_value = json.dumps({
            'archive': '/tmp/boot.tar', 'ipls_dir': '/tmp/ipls', 'images': self.images})
        self.service.select_ipl_image = Mock(return_value=[self.images[0]])
        self.service.board_command_workflow = Mock()
        self.service.board_command_workflow.board_action_commands.side_effect = ValueError('ipaddr override must be a valid IPv4 address')
        self.service.run_single_ipl_menu(self.app)
        dialog = self.app.dialog_workflow_controller.return_value
        dialog.run_confirm_dialog.assert_not_called()
        self.assertEqual(dialog.show_message.call_args.args[1], 'Cannot prepare IPL flash')
        self.app.command_workflow_service.assert_not_called()
