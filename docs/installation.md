# Development and source installation

These workflows target Linux/Python 3.10+. Arch packages and date releases are an independent distribution channel; see
[release setup](releasing.md) and [dependencies](dependencies.md). They are not a development prerequisite.
Ubuntu/Fedora and native dependency builds have not been validated end to end.

## Editable development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

In fish, optionally run `fish_add_path --universal --move ~/Projects/key-cli/.venv/bin`.
This affects all environment commands, including Python/pip. The tool also prints a
command with the actual checkout path. It never writes fish configuration.
Ordinary Python edits affect new processes immediately. Metadata/dependency changes
need another editable install; running processes do not hot-reload. Recreate the venv
if the checkout moves or Python upgrades invalidate it.

```bash
./scripts/install.sh --dev-services enable
systemctl --user daemon-reload
```

This writes `80-key-cli-development.conf` under the clipboard unit's user drop-in
directory. It resets ExecStart to this checkout's absolute `.venv/bin/key clipboard watch`.
If no loaded base unit exists, it deploys the existing repository unit into the user's
unit directory. It does not replace someone else's base unit.

For Clavis, whose lifecycle remains owned by the Clavis repository:

```bash
./scripts/install.sh --dev-services enable --clavis-unit ~/Projects/clavis/packaging/systemd/user/clavis-shell.service
```

If the Clavis base unit is not installed, follow the printed `systemctl --user link`
command, which links Clavis's existing unit. The generated drop-in invokes
`.venv/bin/key shell --foreground --no-duplicate`. No fish subprocess or activation
script is involved. `key shell` supplies CLAVIS_KEY automatically. Direct `qs` launches
still require explicitly selecting CLAVIS_KEY. Clipboard callbacks use their current key.

After configuration, activate clipboard only when wanted:

```bash
./scripts/install.sh --clipboard enable
```

This checks active niri.service before `enable --now`; it never starts niri. To switch
an already running watcher after code changes, explicitly use
`systemctl --user restart clavis-clipboard.service`. The existing singleton lock prevents
duplicate capture; no pkill is used. Clavis restart remains your separate choice.
Clipboard capture survives Shell restarts.

```bash
./scripts/install.sh --dev-services disable
systemctl --user daemon-reload
```

Only manifest-owned, unchanged files are removed. Other user drop-ins remain. If this
tool supplied the only clipboard base unit, install a source/distribution unit before
restarting capture. A separately linked Clavis base unit remains Clavis-owned. Review
fish PATH and restart selected processes to return to the installed version; no whole
fish_user_paths or unit directory is cleared.

## Source install, update and uninstall

```bash
./scripts/install.sh
```

Run as the desktop user, not `sudo ./scripts/install.sh`. The tool creates a temporary
build environment, resolves/builds wheels as the user, then elevates only deployment.
It uses a fresh no-cache build of this checkout, including same-version edits. It never
executes source builds as root or uses --break-system-packages. Install Python with
venv/ensurepip support first; native evdev builds may require a compiler, Python headers
and Linux input headers. Missing external feature commands are reported separately.
No distribution dependency installation is automated.

The final venv is created at its final path; it is neither editable nor moved from a
temporary directory. Root-owned runtime files are installed with non-writable modes
for other users. The CLI and all watchers still run as the desktop user.

| Resource | Default location |
| --- | --- |
| Dedicated environment | `/usr/local/lib/key-cli/venv/` |
| Stable entry symlink | `/usr/local/bin/key` |
| Clipboard base unit | `/usr/local/lib/systemd/user/clavis-clipboard.service` |
| Fish completion | `/usr/local/share/fish/vendor_completions.d/key.fish` |
| Installer, uninstaller and resource sources | `/usr/local/share/key-cli/` |
| Program ownership manifest | `/usr/local/share/key-cli/install-manifest.json` |
| Independent authorization manifest | `/usr/local/share/key-cli/keyboard-manifest.json` |
| Optional rule | `/etc/udev/rules.d/71-clavis-keyboard-leds.rules` |
| Development ownership manifest | `$XDG_CONFIG_HOME/systemd/user/key-cli-development.json` (default `~/.config`) |

Update by rerunning `./scripts/install.sh`. It recreates only its owned venv after wheels are ready and installs those fresh wheels,
without restarting anything or reasking optional choices. Dependency build failure
leaves the current installation intact. Deployment failure returns nonzero and names
the failed step; a partial deployment may remain. There is no automatic rollback or
version-slot system. Retry after inspecting the manifest and resolving the error.

Uninstall as the ordinary user:

```bash
./scripts/uninstall.sh
```

After removing the checkout:

```bash
/usr/local/share/key-cli/uninstall.sh
```

Stop the selected clipboard watcher first if it uses the installation being removed:
`systemctl --user disable --now clavis-clipboard.service`. Neither uninstall nor update
stops ongoing recordings, Shell or other processes automatically. After removal run
`systemctl --user daemon-reload`. Programs already running may still hold loaded code.

Manifests record fixed allowed paths, hashes/link targets, root, mode and program
version. Unknown collisions and modified resources are preserved and reported. Paths
outside the allowed layout and symlink parents are rejected. The dedicated venv is
managed as one program directory; shared directories are never recursively removed.
Uninstall preserves clipboard history, user config, recordings and optional authorization.
`--root /absolute/test-root` is available for isolated deployment testing, not a relocatable
DESTDIR image: generated venv paths reference that final test root.

## Optional authorization

This is independent of source program installation and works from an editable checkout:

```bash
./scripts/install.sh --keyboard enable --acknowledge-keyboard-access --apply
```

The acknowledgement grants the active user's processes access to the **whole keyboard
event device**, including raw input, not only LEDs or Clavis. No input-group membership,
chmod 666, root daemon or polling fallback is added. Without `--apply`, devices are not
reloaded/triggered. With it, reload/trigger occurs only for newly written/changed rules.
Existing equivalent external rules are retained without copying or adopting them;
different rules or masks require manual review. Ordinary code upgrades do not touch rules.

```bash
./scripts/install.sh --keyboard disable
```

Or after deleting the checkout:

```bash
python3 /usr/local/share/key-cli/installer.py --keyboard disable
```

Revoke before uninstalling the saved tool if you want to remove both. Deleting this
persistent rule does not immediately remove current ACLs or already open descriptors.
Other rules/input-group membership may still grant access. Stop the owning subscriber
when appropriate, reload rules, reconnect the device and relogin (or reboot), then check
`getfacl /dev/input/eventN` for the actual keyboard node and `key keyboard status --format json`.
Do not treat removal as a universal ACL revocation.

## Existing installations and diagnostics

Start with `key doctor --json`, `type -a key` and
`systemctl --user cat clavis-clipboard.service clavis-shell.service`.
Doctor separately reports invocation, resolved current key, Python interpreter, actual
module path, PATH default, inherited CLAVIS_KEY, effective unit paths/drop-ins/ExecStart,
and known rule precedence. Its inherited CLAVIS_KEY is not an inspection of another
running Shell's environment. `runtimeReady=false` can mean optional features are off;
the existing exit-code/dependency contract is preserved.

`/usr/local/bin/key` can coexist with pacman's `/usr/bin/key`; PATH and user drop-ins
select which runs. Use `pacman -Qo /usr/bin/key` on Arch to identify ownership. Never
manually overwrite/delete package-owned files. Existing keyboard access packages may
stay installed: equivalent `/usr/lib/udev/rules.d` authorization is not duplicated in
`/etc`. Same-name rules in `/etc` override `/run`, `/usr/local/lib`, then `/usr/lib`.
User units override system units; `/usr/local/lib/systemd/user` takes precedence over
`/usr/lib/systemd/user`, but user drop-ins can still change ExecStart.

This implementation detects collisions; it does not remove any previous installation.
Review unidentified manual files and user edits yourself. To switch from development,
withdraw generated overrides, review fish PATH, reload user units and explicitly restart
only selected processes. No system package removal is required to begin development.

## Arch packages

`key-cli` installs into `/usr` using the system Python and declares `python-evdev`,
`python-pyudev`, `cliphist` and `wl-clipboard` dependencies. The optional
`key-cli-keyboard-access` split package supplies the existing uaccess rule. It is not a
base-package dependency. Neither package enables or starts a user service.

Both `key --version` and the wheel metadata read the single `src/key_cli/VERSION` resource.
After a metadata change, refresh an editable development environment explicitly; existing
watchers still require a separate restart. The release source/wheel do not depend on Git
at runtime. `scripts/build-packages.sh` prepares a checksummed local source and PKGBUILD;
[release workflows](releasing.md) publish immutable source URLs and synchronize AUR.
