# key-cli

The command-line companion for [Clavis Shell](https://github.com/StatIndet/quickshell).

`key-cli` installs the `key` command and provides shell lifecycle/IPC, screen recording, audio recording, clipboard integration and keyboard LED events.

## Project family

| Project | Role |
| --- | --- |
| **[Clavis Shell](https://github.com/StatIndet/quickshell)** | Quickshell UI, reactive services and native QML modules |
| **[key-cli](https://github.com/StatIndet/key-cli)** | `key` command and discrete system tasks |
| **[keytop](https://github.com/StatIndet/keytop)** | Standalone system monitor, TUI and metrics stream |

Install the main package and optionally the keyboard authorization package using [installation instructions](docs/installation.md). Neither package automatically enables clipboard capture.

## Commands

```text
key shell
key ipc
key record
key audio
key clipboard
key keyboard
key doctor
key version
```

### Shell

```bash
key shell
key shell --daemon
key shell --kill
key shell --log
```

### IPC

```bash
key ipc show
key ipc call TARGET METHOD [ARGUMENTS...]
```

### Screen recording

```bash
key record start --target region --type video
key record status --json
key record pause --json
key record resume --json
key record stop --json
```

### Audio recording

```bash
key audio start --source mic --json
key audio start --source system --json
key audio status --json
key audio stop --json
```

### Clipboard

```bash
key clipboard status --format json
key clipboard list --format json --limit 20
key clipboard inspect ID --format json
key clipboard restore ID --format json
key clipboard delete ID --format json
key clipboard clear --format json
```

## Installation from source

Requires Python 3.10 or newer.

```bash
python -m venv .venv
.venv/bin/python -m pip install .
```

The Arch main package installs the Clavis clipboard watcher user service; the Python wheel does not. After installing the system package, enable capture explicitly with:

```bash
systemctl --user daemon-reload
systemctl --user enable --now clavis-clipboard.service
```

For packaged installations, prefer your distribution package manager.

## External tools

Features use system executables when available:

- Quickshell (`qs`)
- gpu-screen-recorder
- slurp
- FFmpeg / ffprobe
- PulseAudio/PipeWire `pactl`
- cliphist
- wl-clipboard

Check the current environment with:

```bash
key doctor
key doctor --json
```

## Development

```bash
python -m pip install -e '.[dev]'
ruff format .
ruff format --check .
ruff check .
python -m compileall src
python -m pytest
python -m build --wheel
scripts/check.sh
```

The machine-facing JSON contract is documented in [`docs/protocol.md`](docs/protocol.md).
`scripts/check.sh` is the single local quality gate; it runs Ruff, `compileall`, pytest,
wheel creation and a check that Python code is present and system resources stay outside the wheel. It does not
install system files or start services.

## License

See [LICENSE](LICENSE).
