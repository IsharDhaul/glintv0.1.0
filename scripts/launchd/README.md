# Nightly refresh on macOS (optional)

`glint refresh` always works by hand. If you want it to run every morning:

```bash
make schedule-install   # from the main checkout, not a worktree
make schedule-remove    # undo
```

- **When:** 09:15 local time. Set your Mac to Europe/London (the install warns if it isn't). By then SEC has rebuilt the bulk files (about 03:00 ET, usually 08:00 London) and Massive has yesterday's bars (SPEC §4.8). The Mac must be awake: launchd runs a missed job when the Mac wakes, not while it sleeps.
- **What:** `cd <repo>/engine && uv run glint refresh`, which builds into the checkout you installed from (`GLINT_DB_DIR`, default `./data`).
- **Logs:** `~/GlintData/logs/refresh.out.log` and `refresh.err.log`, plus one log per build in `data/logs/<build_id>.log` and a report in `data/reports/<build_id>.md`.
- **On failure:** the previous build stays live. The out log names the failing stage, and the per-build log has the traceback.
- **Check it's loaded:** `launchctl print gui/$(id -u)/com.glint.refresh`. Run it now with `launchctl kickstart gui/$(id -u)/com.glint.refresh`.
