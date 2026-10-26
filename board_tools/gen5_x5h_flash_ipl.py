#!/usr/bin/env python3
"""Prepare IPLs at artifact copy time; list or flash already prepared files."""

import argparse
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile

import yaml


def is_bootloader_config(member_name):
    path = PurePosixPath(member_name)
    return (
        path.name == 'x5h_bootloaders.yaml'
        and path.parent.name == 'ipls'
        and 'build-domd' in path.parts[:-2]
    )


def archive_images(archive):
    configs = [m for m in archive.getmembers()
               if m.isfile() and is_bootloader_config(m.name)]
    if len(configs) != 1:
        raise ValueError('Expected one build-domd/.../ipls/x5h_bootloaders.yaml in boot artifacts')
    config = configs[0]
    with archive.extractfile(config) as stream:
        entries = yaml.safe_load(stream)['images']
    prefix = str(PurePosixPath(config.name).parent) + '/'
    images = []
    for entry in entries:
        name = str(entry['name'])
        if str(entry.get('target', '')).upper() != 'UFS':
            continue
        if PurePosixPath(name).name != name or name in ('.', '..'):
            raise ValueError(f'Invalid IPL filename: {name}')
        try:
            member = archive.getmember(prefix + name)
        except KeyError:
            continue
        if member.isfile():
            images.append({'name': name, 'flash_addr': hex(int(str(entry['flash_addr']), 16))})
    return config, images


def find_archive(artifacts):
    paths = sorted(p for p in artifacts.rglob('*') if p.is_file()
                   and ('boot-artifacts' in p.name or 'boot_artifacts' in p.name)
                   and p.name.endswith(('.tar.bz2', '.tar.gz', '.tar')))
    if len(paths) != 1:
        raise ValueError('Expected one boot-artifacts archive; remove stale copies from artifacts')
    return paths[0]




def prepared_listing(artifacts=None, ipls_dir=None):
    directory = ipls_dir or artifacts / '.moulin-ipls' / 'current'
    config = directory / 'x5h_bootloaders.yaml'
    if not config.is_file():
        raise ValueError('IPLs are not prepared on board host. Build boot_artifacts if needed, then run Copy build artifacts.')
    # Provenance is optional; YAML and files, not cached metadata, define the menu.
    try:
        metadata = json.loads((directory / 'source.json').read_text())
    except (OSError, ValueError):
        metadata = {}
    listing = {'archive': metadata.get('archive', str(directory.resolve())),
               'archive_stat': metadata.get('archive_stat'),
               'ipls_dir': str(directory.resolve()), 'images': []}
    entries = yaml.safe_load(config.read_text())['images']
    for entry in entries:
        if str(entry.get('target', '')).upper() != 'UFS':
            continue
        name = str(entry['name'])
        if PurePosixPath(name).name != name or name in ('.', '..'):
            raise ValueError(f'Invalid IPL filename: {name}')
        if not (directory / name).is_file():
            raise ValueError(f'IPL file from YAML is missing: {name}. Copy build artifacts again.')
        if any(image['name'] == name for image in listing['images']):
            raise ValueError(f'Duplicate IPL filename: {name}')
        listing['images'].append({'name': name, 'flash_addr': hex(int(str(entry['flash_addr']), 16))})
    return listing


def prepare_ipls(artifacts, archive_path=None):
    path = archive_path or find_archive(artifacts)
    stat = path.stat()
    signature = {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'ctime_ns': stat.st_ctime_ns}
    cache = artifacts / '.moulin-ipls'
    cache.mkdir(parents=True, exist_ok=True)
    try:
        current = prepared_listing(artifacts)
    except (ValueError, KeyError, OSError):
        current = None
    if current and current['archive'] == str(path) and current.get('archive_stat') == signature:
        return current
    snapshot = Path(tempfile.mkdtemp(prefix='snapshot-', dir=cache))
    link = cache / (snapshot.name + '.link')
    try:
        with tarfile.open(path) as archive:
            config, _images = archive_images(archive)
            prefix = str(PurePosixPath(config.name).parent)
            for member in archive.getmembers():
                member_path = PurePosixPath(member.name)
                if member.isfile() and str(member_path.parent) == prefix:
                    if member_path.name in ('', '.', '..'):
                        raise ValueError('Invalid IPL archive member')
                    with archive.extractfile(member) as src, (snapshot / member_path.name).open('wb') as dst:
                        shutil.copyfileobj(src, dst)
            (snapshot / 'source.json').write_text(json.dumps({'archive': str(path), 'archive_stat': signature}))
        listing = prepared_listing(ipls_dir=snapshot)
        link.symlink_to(snapshot.name)
        link.replace(cache / 'current')
        return listing
    except Exception:
        link.unlink(missing_ok=True)
        shutil.rmtree(snapshot)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--ipls-dir', type=Path)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--all', action='store_true', help='flash every UFS image from the prepared YAML')
    parser.add_argument('--name', action='append', help='repeat for a subset; execution follows YAML order')
    parser.add_argument('--port')
    parser.add_argument('--tftp-root', type=Path, default=Path('/srv/tftp'))
    parser.add_argument('--tftp-dir', type=Path)
    args = parser.parse_args()
    if args.prepare:
        if args.artifacts is None:
            parser.error('--prepare requires --artifacts')
        listing = prepare_ipls(args.artifacts, args.archive)
        print(f"Prepared {len(listing['images'])} UFS IPLs: {listing['ipls_dir']}")
        return
    if args.artifacts is None and args.ipls_dir is None:
        parser.error('--artifacts or --ipls-dir is required')
    listing = prepared_listing(args.artifacts, args.ipls_dir)
    if args.all and args.name:
        parser.error('--all and --name cannot be used together')
    names = [entry['name'] for entry in listing['images']] if args.all else args.name
    if args.all and not names:
        raise ValueError('Prepared YAML does not contain UFS images')
    if not names:
        print(json.dumps(listing))
        return
    if not set(names).issubset({entry['name'] for entry in listing['images']}):
        raise ValueError('Selected UFS image is not available in this IPL snapshot')
    if not args.port or args.tftp_dir is None:
        parser.error('--port and --tftp-dir are required for flashing')
    args.tftp_dir.resolve().relative_to(args.tftp_root.resolve())
    args.tftp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ipl-flash-', dir=args.tftp_dir) as directory:
        staging = Path(directory)
        staging.chmod(0o755)
        names = [entry['name'] for entry in listing['images'] if entry['name'] in names]
        for name in ['x5h_bootloaders.yaml', *names]:
            shutil.copyfile(Path(listing['ipls_dir']) / name, staging / name)
            (staging / name).chmod(0o644)
        prefix = staging.resolve().relative_to(args.tftp_root.resolve()).as_posix()
        commands = [[
            sys.executable, '-u', str(Path(__file__).with_name('ipl_ufs_flash.py')),
            '--port', args.port, '--config', str(staging / 'x5h_bootloaders.yaml'),
            '--name', name, '--file', str(staging / name),
            '--tftp', str(staging), '--tftp-prefix', prefix,
        ] for name in names]
        for command in commands:
            subprocess.run(command + ['--check'], check=True)
        if not args.check:
            for index, command in enumerate(commands, 1):
                print(f'Flashing IPL {index}/{len(commands)}: {names[index - 1]}', flush=True)
                subprocess.run(command, check=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, tarfile.TarError, subprocess.CalledProcessError) as exc:
        sys.exit(f'Error: {exc}')
