# key-cli

The command-line companion for [Clavis Shell](https://github.com/StatIndet/quickshell).
It provides the `key` command for shell lifecycle and IPC, recording, clipboard history,
and event-driven Caps Lock / Num Lock state.

Clavis owns the interface; key-cli owns these independent system backends and their
[JSON/JSONL protocol](docs/protocol.md). [keytop](https://github.com/StatIndet/keytop)
remains responsible for system metrics.

## Choose an installation method

Requires Linux and Python 3.10 or newer. For a desktop installation on Arch Linux,
use the system packages. A virtual environment is useful for development and testing.

| Installation | Provides | Does not do automatically |
| --- | --- | --- |
| `key-cli` Arch package | `key`, keyboard and clipboard backends, fish completion, clipboard user service file | Grant keyboard access or start clipboard capture |
| `key-cli-keyboard-access` optional Arch package | udev rule granting the active local user access to LED-capable keyboards | Start a keyboard monitor or clipboard service |
| Python wheel / venv | Python modules and the `key` entry point inside the selected environment | Replace a system `key`, install systemd/udev files, or grant device access |

Installing dependencies, granting keyboard access, and enabling clipboard capture are
separate steps. Neither Arch package enables or starts a service during installation.

### Arch Linux: build and install packages

From this repository, install the build prerequisites and build both packages:

```bash
sudo pacman -S --needed base-devel python-build python-installer \
  python-setuptools python-wheel python-pytest python-evdev python-pyudev
scripts/build-packages.sh
```

The script builds a snapshot of the current checkout, including local edits, runs checks,
and prints the temporary directory containing the package files. It does **not** install
them. This is a local package build; see [installation details](docs/installation.md)
for the source archive and checksum policy.

Install the main package with `sudo pacman -U`, using its exact file path. For example,
replace `/path/to/packages` and the version below with the build output:

```bash
sudo pacman -U /path/to/packages/key-cli-0.2.0-1-any.pkg.tar.zst
```

For global Caps/Num Lock monitoring, explicitly opt into the authorization package:

```bash
sudo pacman -U /path/to/packages/key-cli-keyboard-access-0.2.0-1-any.pkg.tar.zst
```

Avoid a wildcard that selects both packages if you do not want keyboard authorization.
The main package declares `python-evdev`, `python-pyudev`, `cliphist` and `wl-clipboard`
as runtime dependencies. Additional tools are listed below.

If an older installation already provides `key`, check `command -v key` and its ownership
with `pacman -Qo /actual/path/to/key` first. A manually installed or pip-installed copy
may conflict with the package. Follow the [migration instructions](docs/installation.md#existing-installations)
rather than overwriting files or deleting an unidentified installation.

### Development or testing: use a virtual environment

From this repository:

```bash
python -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/key keyboard status --format json
```

This installs the declared Python dependencies into the venv. External commands and
keyboard permissions must still be supplied separately. The venv does not install the
clipboard systemd unit or optional udev rule.

**Installing into `.venv` does not update `/usr/bin/key` or an already running shell.**
Use the explicit executable path to launch Clavis with this version:

```bash
.venv/bin/key shell
```

Exit an existing Clavis instance first when switching versions. The `key shell` launcher
sets `CLAVIS_KEY` to its own executable so the new shell uses the same key-cli installation.
For direct `qs` launches, set `CLAVIS_KEY` to the absolute path of the intended `key`.

## Enable and verify features

### Caps Lock / Num Lock

Keyboard monitoring reads actual evdev LED state and handles device changes through udev.
It has no periodic status query or polling fallback. Clavis starts one shared
`key keyboard watch` child process; it does not require a separate keyboard service.

The optional authorization rule grants access to the **whole keyboard event device**,
including raw key events. It is not LED-only or application-specific permission.
The backend only processes lock LED state and does not output ordinary keystrokes.

After installing the authorization package, apply the rule to existing devices from an
active local desktop session:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger --action=change --subsystem-match=input
sudo udevadm settle
key keyboard status --format json
```

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

After installing the main Arch package, enable capture explicitly:

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

Use `key --help` or `key COMMAND --help` for all options.

| Task | Examples |
| --- | --- |
| Shell lifecycle | `key shell`, `key shell --daemon`, `key shell --kill`, `key shell --log` |
| Shell IPC | `key ipc show`, `key ipc call TARGET METHOD [ARGUMENTS...]` |
| Screen recording | `key record start --target region --type video`, `key record status --json`, `key record stop --json` |
| Pause / resume recording | `key record pause --json`, `key record resume --json` |
| Audio recording | `key audio start --source mic --json`, `key audio start --source system --json`, `key audio status --json`, `key audio stop --json` |
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
Yazi is launched through `xdg-terminal-exec`; Dolphin and Nautilus can select the file.
Other managers open its parent directory. See [file actions](docs/protocol.md#saved-file-actions).

## Dependencies and troubleshooting

| Feature | Runtime dependencies |
| --- | --- |
| Shell and IPC | Clavis Shell and Quickshell (`qs`) |
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
| `keyboard_device_unavailable` / permission denied | Check the optional authorization package, active local session and device ACLs. Python dependencies do not grant device access. |
| Watch reports changes but Clavis shows no OSD | Check the Keystone switches and restart Clavis with the intended key-cli version. |
| Clipboard watcher is inactive | Check `niri.service` and `systemctl --user status clavis-clipboard.service`. |

## Upgrade, revoke access or uninstall

Use pacman to upgrade or remove the system packages. Keyboard authorization can be
removed separately from the main package and clipboard capture. Stop the shell's
keyboard subscriber before revoking access: deleting a udev rule does not immediately
revoke existing ACLs or already open device handles.

Administrator rules in `/etc/udev/rules.d` and user systemd units may override packaged
files. Review these when migrating or revoking access. See the
[installation guide](docs/installation.md#stop-revoke-or-uninstall) for the complete sequence.
Uninstalling packages does not clear cliphist history or user configuration.

## Development

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
scripts/check.sh
```

`scripts/check.sh` uses the repository venv when available. It runs Ruff, Python
compilation checks, pytest, wheel creation and wheel content validation. It does not
install system files or start services. Format only the files you change with
`.venv/bin/python -m ruff format PATH...` before running checks.

The Arch build additionally validates the split package contents. Tests run independently
of the Clavis Shell and keytop repositories.

## License

[GPL-3.0-or-later](LICENSE).
