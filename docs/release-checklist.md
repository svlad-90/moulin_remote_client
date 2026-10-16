# Release Checklist

Use this maintainer checklist before sharing a build with the team.

## Automated Checks

```sh
python3 -m unittest discover -s . -p 'test_*.py'
python3 -m compileall -q .
git diff --check
```

## Publication Checks

1. Use synthetic host names, user names, repository URLs, and deployment paths
   in examples, tests, and screenshot fixtures. Use documentation address
   ranges such as `192.0.2.0/24` for network examples.
2. Regenerate README screenshots with
   `python3 scripts/render_readme_screenshots.py` and inspect the resulting
   images for internal infrastructure or product information.
3. Review Git history before publication. Cleaning the current files does not
   remove information from earlier commits.

## Real Environment Checks

1. Start the TUI with `MOULIN_REMOTE_AUTO_CONNECT=no`.
2. Configure a build host, board host, and project profile from an empty local
   config.
3. Connect the build host.
4. Select and activate at least one source mapping.
5. Pull selected mappings to the local overlay.
6. Edit a mapped local file.
7. Run a build command and confirm the pre-build rsync push happens first.
8. Copy board artifacts.
9. Run board flashing only on a board that is safe to reflash.
