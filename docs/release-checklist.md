# Release Checklist

Use this maintainer checklist before sharing a build with the team.

## Automated Checks

```sh
python3 -m unittest discover -s . -p 'test_*.py'
python3 -m compileall -q .
git diff --check
```

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
