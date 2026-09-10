# Installation and independent lifecycles

The Arch split build produces:

- **key-cli**: Python CLI, keyboard backend, clipboard backend, fish completion and
  `/usr/lib/systemd/user/clavis-clipboard.service`. Runtime dependencies include
  python-evdev, python-pyudev, cliphist and wl-clipboard.
- **key-cli-keyboard-access** (optional):
  `/usr/lib/udev/rules.d/71-clavis-keyboard-leds.rules`. This grants the active local
  session access to LED-capable evdev keyboard nodes. The permission covers raw
  keyboard input, not just LED state; installing this package is an explicit opt-in.

Neither package enables or starts services. There is no root keyboard daemon, shared
`key daemon`, keyboard systemd unit, periodic status query, or polling fallback.
Quickshell owns one `key keyboard watch --format jsonl` child process; the clipboard
watcher has a separate systemd user lifecycle and survives shell restarts.

## Build and select packages

Install Arch build prerequisites yourself: base-devel, python-build, python-installer,
python-setuptools, python-wheel, python-pytest, python-evdev and python-pyudev.
Run `scripts/build-packages.sh` from the checkout. It snapshots tracked and unignored
files, including local edits, into a temporary directory and runs makepkg there.
It does not install packages. The PKGBUILD accepts this local archive (checksum SKIP);
for a published release use a fixed release archive and its verified checksum.

Use `sudo pacman -U /path/to/key-cli-0.2.0-1-any.pkg.tar.zst` with the **exact main package file**.
Optionally install the exact `key-cli-keyboard-access` package file separately. Avoid a
wildcard covering both packages when choosing not to grant keyboard access.
Package files remain in the temporary build directory reported by the script.
Repeated installation/upgrades use pacman ownership, not file copies or `--overwrite`.
The Python wheel only carries Python code and the key entry point; system resources
are installed by the distribution packages. A pip/venv installation alone does not
install or enable the systemd unit or udev rule.

## Existing installations

Before installing, inspect `command -v key`, `pacman -Qo /path/to/key`,
`systemctl --user cat clavis-clipboard.service` and
`/etc/udev/rules.d/71-clavis-keyboard-leds.rules`. An administrator rule in `/etc`
overrides the same-named package rule in `/usr/lib`; a user unit can override the
packaged unit. `key doctor --json` reports known overrides and its resolved key path.
Identify whether old files came from pip, a manual installation or another package;
back up and remove them through their owner only after reviewing them. Do not use
blanket overwrite/delete commands. In particular, removing the optional package
cannot revoke an independently installed rule in `/etc`.

## Enable only the desired features

For keyboard access, Arch's udev package hooks reload installed rules. To apply the
rule to existing devices now, run these commands yourself in an active local session:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger --action=change --subsystem-match=input
sudo udevadm settle
key keyboard status --format json
```

`available: true` confirms LED devices are readable. Permission failures remain
explicit errors; moving the backend to key-cli does not remove the permission need.
Enable Caps/Num Lock OSD in Clavis Keystone settings. Reload the shell after switching
from the old native module so it starts the new singleton subscriber.

Clipboard capture is separately opt-in and requires an active `niri.service`:

```bash
systemctl --user is-active niri.service
systemctl --user daemon-reload
systemctl --user enable --now clavis-clipboard.service
key clipboard status --format json
```

`key doctor --json` distinguishes executable dependencies from keyboard availability,
clipboard watcher presence and active user units. `runtimeReady` is false if either
optional feature is not running; this is not a reason to enable a feature you do not want.
The existing doctor exit code continues to describe missing executable dependencies.

## Stop, revoke or uninstall

Stop clipboard capture independently:
`systemctl --user disable --now clavis-clipboard.service`.
Stop the keyboard subscriber by stopping its owning shell before revoking access.
Remove `key-cli-keyboard-access` using pacman to withdraw the packaged rule. Existing
ACLs and open file descriptors are not automatically revoked by deleting a rule;
check for administrator overrides, reload rules, then log out and reconnect devices
(or reboot) before treating access as revoked. Verify device ACLs after logging in again.

Before removing the main package, stop the clipboard service and keyboard subscriber.
Uninstall/reinstall must preserve cliphist history and `$XDG_CONFIG_HOME/key/clipboard.json`.
No package uninstall hook removes user data or alters other users' services.
