# key-cli

The command-line companion for [Clavis Shell](https://github.com/StatIndet/quickshell).
It provides the `key` command for shell lifecycle and IPC, screen/audio recording,
saved-file actions, clipboard history and event-driven Caps Lock / Num Lock state.

Clavis owns the interface; key-cli owns these independent system backends and their
[JSON/JSONL protocol](docs/protocol.md). [keytop](https://github.com/StatIndet/keytop)
provides kernel/system information snapshots and metrics directly to Clavis through
its own JSONL stream.

## Scope

| Backend | Commands |
| --- | --- |
| Shell lifecycle and IPC compatibility | `key shell`, `key ipc` |
| Screen recording, GIF finalization and session events | `key record` |
| Microphone/system audio recording and session events | `key audio` |
| Open or reveal saved files | `key file` |
| Clipboard capture, history and configuration | `key clipboard` |
| Caps Lock / Num Lock snapshots and events | `key keyboard` |
| Runtime diagnostics and version | `key doctor`, `key version` |

Clavis owns the UI and its native weather, media, lyrics and compositor integrations.
Key-cli does not forward system metrics or implement a second system monitor.

## Development

Requires Linux and Python 3.10+. Configure once in the checkout:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

Optionally select this environment in fish (this also changes `python`/`pip`, not only `key`):

```fish
fish_add_path --universal --move ~/Projects/key-cli/.venv/bin
```

New `key` processes now read ordinary Python edits directly. No wheel, makepkg or system
installation is needed. Reinstall the editable project after dependency/entry-point
metadata changes. Existing watchers keep already imported modules; restart the specific
watcher when needed. Rebuild `.venv` after moving/deleting the checkout or incompatible
Python upgrades. Nothing silently edits your fish configuration.

For one-time clipboard service configuration, including a checkout without an installed
base unit:

```bash
./scripts/install.sh --dev-services enable
systemctl --user daemon-reload
```

To also generate the Clavis development override, reuse Clavis's own unit:

```bash
./scripts/install.sh --dev-services enable --clavis-unit ~/Projects/clavis/packaging/systemd/user/clavis-shell.service
```

The tool prints the base-unit link command if needed. Both overrides use this checkout's
absolute `.venv/bin/key`, without relying on fish PATH. `key shell` propagates its own
entry point through `CLAVIS_KEY`; clipboard callbacks use their invoking `key` too.
Service activation is separate; see [installation details](docs/installation.md).
Remove only generated development configuration with:

```bash
./scripts/install.sh --dev-services disable
systemctl --user daemon-reload
```

## Install from source

Start as your desktop user, **without sudo**:

```bash
./scripts/install.sh
```

The tool builds this checkout and dependencies as your user, then requests sudo only
for deployment into `/usr/local/lib/key-cli/venv`. `/usr/local/bin/key` uses that dedicated
regular installation; it works after the checkout is removed. System Python is untouched.
Python/venv and dependency build prerequisites must already be available. The installer
does not install distribution dependencies; native evdev wheel builds may need a C
compiler and Python/Linux input headers. Build errors stop before deployment.

Update with the same command, including when the project version is unchanged. No
manual intermediate wheel or package handling is needed. No services are started or
restarted and no keyboard access is granted by default.

```bash
./scripts/uninstall.sh
```

Without a checkout, use `/usr/local/share/key-cli/uninstall.sh` as your ordinary user.
Optional keyboard authorization is managed independently; uninstall preserves it and
user data. See [layout, ownership and removal](docs/installation.md).

## Distribution packages

`packaging/arch/PKGBUILD` and `scripts/build-packages.sh` remain future distribution
packaging references. They are not prerequisites for development or source installation.
Existing `key-cli-keyboard-access` packages can remain installed; the source installer
will not adopt or duplicate an equivalent package-owned rule. No AUR/Deb/RPM release
workflow is provided here.

## Enable and verify features

### Caps Lock / Num Lock

Keyboard monitoring reads actual evdev LED state and handles device changes through udev.
It has no periodic status query or polling fallback. Clavis starts one shared
`key keyboard watch` child process; it does not require a separate keyboard service.

The optional authorization rule grants access to the **whole keyboard event device**,
including raw key events. It is not LED-only or application-specific permission.
The backend only processes lock LED state and does not output ordinary keystrokes.

For source or editable development, authorization is independently opt-in:

```bash
./scripts/install.sh --keyboard enable --acknowledge-keyboard-access --apply
key keyboard status --format json
```

The flag explicitly accepts whole-device access. `--apply` reloads/triggers udev only
when this tool adds or changes the rule. Omit it to save the rule without changing
current devices. Existing equivalent external authorization is left alone.

Look for `"available":true`. Then test changes:

```bash
key keyboard watch --format jsonl
```

The first line is a `snapshot`; normal lock changes produce `changed` events. Silence
between changes is expected. Press Ctrl+C to stop this diagnostic process. Clavis uses
snapshots to establish a baseline without showing a toggle notification.

Enable the Caps Lock and Num Lock OSD switches in **Clavis Settings → Keystone**.
If using a venv, substitute `.venv/bin/key` in the diagnostic commands above.

### Clipboard history

Clipboard capture uses the separate `clavis-clipboard.service` user service. It continues
across shell restarts and is independent of keyboard permissions or monitor failures.
The packaged unit requires an active `niri.service`.

After installing the source unit or configuring the development override, enable capture explicitly:

```bash
systemctl --user is-active niri.service
systemctl --user daemon-reload
systemctl --user enable --now clavis-clipboard.service
key clipboard status --format json
```

If `niri.service` is inactive, resolve the session setup before starting the watcher.
Check `watcherRunning` in the status response; installed executables alone do not mean
capture is running. To stop capture without disabling keyboard monitoring:

```bash
systemctl --user disable --now clavis-clipboard.service
```

History is stored by cliphist. The saved history limit defaults to 500 and accepts
50–750 in steps of 50:

```bash
key clipboard config --format json
key clipboard config --max-items 500 --format json
```

The setting lives in `$XDG_CONFIG_HOME/key/clipboard.json`, or
`~/.config/key/clipboard.json` when XDG_CONFIG_HOME is unset. Lowering the limit does not
immediately delete history: cliphist applies the new limit on the next accepted save,
keeping the newest records. The query limit is a separate setting.

## Command reference

Use `key --help` or `key COMMAND --help` for all options. For new Clavis keybindings,
prefer direct Quickshell IPC; `key ipc` remains available as a compatibility entry:

```bash
qs -c clavis ipc call sidebar toggle dashboard
qs -c clavis ipc call sidebar toggle quicksettings
```

These targets select sidebar content, independently of the configured screen edge.

| Task | Examples |
| --- | --- |
| Shell lifecycle | `key shell`, `key shell --daemon`, `key shell --kill`, `key shell --log` |
| Shell IPC | `key ipc show`, `key ipc call TARGET METHOD [ARGUMENTS...]` |
| Screen recording | `key record start --target region --type video`, `key record status --json`, `key record stop --json` |
| Pause / resume recording | `key record pause --json`, `key record resume --json` |
| Audio recording | `key audio start --source mic --json`, `key audio start --source system --json`, `key audio status --json`, `key audio stop --json` |
| Saved-file actions | `key file reveal /absolute/path --format json`, `key file open /absolute/path --format json` |
| Clipboard queries | `key clipboard list --format json --limit 20`, `key clipboard inspect ID --format json` |
| Clipboard actions | `key clipboard restore ID --format json`, `key clipboard delete ID --format json`, `key clipboard clear --format json` |
| Keyboard state | `key keyboard status --format json`, `key keyboard watch --format jsonl` |
| Diagnostics / version | `key doctor --json`, `key version` |

`clipboard clear` deletes history; it is not a diagnostic command.
Machine clients should follow the [protocol specification](docs/protocol.md), including
schema validation, errors and exit codes.

Recording clients can subscribe with `key record watch --format jsonl` or
`key audio watch --format jsonl`. These session-scoped Linux event streams replace
repeated status queries and exit when the session becomes idle or terminal. See the
[recording subscription protocol](docs/protocol.md#recording-subscriptions) for snapshot,
ordering, process-exit and error semantics.

Use `key file reveal /absolute/path --format json` to find a saved recording, or
`key file open /absolute/path --format json` to open it with its default application.
Reveal uses FileManager1 selection, with a parent-directory fallback through GIO.
Terminal apps use the system terminal launcher. See [file actions](docs/protocol.md#file-search-and-desktop-actions).

## Dependencies and troubleshooting

| Feature | Runtime dependencies |
| --- | --- |
| Shell and IPC | Clavis Shell and Quickshell (`qs`) |
| Saved-file actions | GLib (`gio`), a default application; `xdg-terminal-exec` for terminal apps; `busctl` for selection |
| Keyboard LEDs | Python `evdev`, `pyudev`, and access to the relevant evdev devices |
| Clipboard | `cliphist`, `wl-copy`, `wl-paste`; capture also requires the watcher |
| Screen recording | `gpu-screen-recorder`; `slurp` for region selection |
| Audio recording / GIF processing | FFmpeg; audio also uses `ffprobe` and `pactl` |

Run `key doctor --json` for dependency and runtime diagnostics. `runtimeReady` covers
keyboard availability and clipboard capture; it can be false when an optional feature
is intentionally disabled. Doctor's exit code continues to describe missing executable
dependencies, not whether every feature is running.

| Symptom | Check |
| --- | --- |
| `keyboard` is an unknown command | An older `key` is being invoked. Check `command -v key`, the shell's `CLAVIS_KEY`, and the venv executable directly. |
| `keyboard_dependency_unavailable` | Install evdev/pyudev in the Python environment used by that `key`; system Python and a venv are separate environments. |
| `keyboard_device_unavailable` / permission denied | Check optional udev authorization, active local session and device ACLs. Python dependencies do not grant device access. |
| Watch reports changes but Clavis shows no OSD | Check the Keystone switches and restart Clavis with the intended key-cli version. |
| Clipboard watcher is inactive | Check `niri.service` and `systemctl --user status clavis-clipboard.service`. |

## Checks and removal

```bash
scripts/check.sh         # daily source checks
# Or, when packaging/install behavior is affected:
scripts/check.sh --build
```

The daily check runs Ruff, compilation and pytest against current source. `--build`
adds wheel creation/content validation and isolated install verification; it is separate
from distribution package validation. Format only changed files. Tests do not depend on
Clavis or keytop checkouts.

Withdraw only installer-owned persistent keyboard authorization independently:

```bash
./scripts/install.sh --keyboard disable
```

Removing a rule does **not** immediately revoke existing ACLs or open device handles.
Review other rules and input-group membership, reconnect devices and log in again (or
reboot), then verify access. User history, settings and recordings are never removed.
See [migration and lifecycle details](docs/installation.md).


## Arch packages and date releases

Arch x86_64 packaging and GitHub Actions release workflows are included. Versions use
`2026.9.12` (tag `v2026.9.12`), with `.1`, `.2` for further releases on the same day.
See [GitHub release setup](docs/releasing.md) and the
[dependency inventory](docs/dependencies.md). Each repository remains independently buildable.

AUR packages: `key-cli` and optional `key-cli-keyboard-access`. The existing
[source installer](docs/installation.md) remains available and independent of Arch packaging.

## License

[GPL-3.0-or-later](LICENSE).

### File search

Install the external `fd` (or `fdfind`), GLib (`gio`), and `busctl` runtime tools;
a Python wheel does not include OS dependencies. `key file status --format json`
reports capabilities. Search HOME with `key file search --format json -- 'report'`
or supply repeatable absolute `--root` paths. Hidden/ignored files retain fd defaults;
results are bounded, and the response identifies incomplete searches.
Use `key file open -- /absolute/path` for the default association, or
`key file reveal -- /absolute/path` to request selection in a file manager.
Reveal falls back to opening the parent directory when FileManager1 cannot accept
the request. See [the protocol](docs/protocol.md#file-search-and-desktop-actions).
