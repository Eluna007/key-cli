# Dependencies

The source of truth is [`packaging/dependencies.json`](../packaging/dependencies.json).
Release tooling generates PKGBUILD dependency fields from this inventory. `defaultInstall`
selects the full installation profile; optional authorization and vendor GPU drivers are never implicit.

Runtime-only dependencies are assigned in package functions, so this repository builds and
tests independently of other Clavis repositories. CI installs only build, check and CI entries.

## Build

| Arch package | Purpose | Full install |
| --- | --- | --- |
| `python-build` | PEP 517 wheel build | Yes |
| `python-installer` | Wheel installation | Yes |
| `python-setuptools` | Build backend | Yes |
| `python-wheel` | Wheel tooling | Yes |

## Tests

| Arch package | Purpose | Full install |
| --- | --- | --- |
| `python-pytest` | CLI and installer contracts | Yes |
| `python-evdev` | Keyboard backend | Yes |
| `python-pyudev` | Device discovery | Yes |
| `git` | Isolated source archive contract fixtures | Yes |

## CI quality tools

This phase is used only in CI; these tools are not installer runtime requests.

| Arch package | Purpose | Full install |
| --- | --- | --- |
| `actionlint` | GitHub Actions workflow validation | CI only |
| `ruff` | Python formatting and lint | Yes |
| `shellcheck` | Shell quality checks | Yes |
| `git` | Source metadata | Yes |

## key-cli runtime

| Arch package | Purpose | Full install |
| --- | --- | --- |
| `python>=3.10` | CLI interpreter | Yes |
| `python-evdev>=1.7` | Keyboard events | Yes |
| `python-pyudev>=0.24` | Keyboard discovery | Yes |
| `cliphist` | Clipboard history | Yes |
| `wl-clipboard` | Wayland clipboard | Yes |

## key-cli-keyboard-access runtime

| Arch package | Purpose | Full install |
| --- | --- | --- |
| `systemd` | logind and udev uaccess | Yes |

## key-cli optional

| Arch package | Purpose | Full install |
| --- | --- | --- |
| `key-cli-keyboard-access` | Whole keyboard event device access | Explicit opt-in |
| `quickshell` | Shell lifecycle and IPC | Yes |
| `gpu-screen-recorder` | Screen recording | Yes |
| `ffmpeg` | Audio recording and GIF conversion | Yes |
| `libpulse` | pactl audio source discovery | Yes |
| `slurp` | Region selection | Yes |
| `xdg-utils` | Open files and query defaults | Yes |
| `xdg-terminal-exec` | Terminal file managers | Yes |
