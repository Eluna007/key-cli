# key-cli machine protocol

`key-cli` owns the machine-facing JSON emitted by the `key` command. This document
describes the stable external contract consumed by Clavis. A breaking response change
requires updates here and a corresponding public-contract test; Python module layout and
function names are not part of the protocol.

## Envelope

JSON output is requested with `--json` or `--format json` where the command supports the
latter. Responses contain these common fields:

- `schemaVersion`: integer, currently `1`;
- `command`: the public operation name, such as `record.status` or `clipboard.list`;
- `ok`: boolean matching whether the command succeeded;
- `error`: `null` on success, otherwise an object with at least `code` and `message`;
- `exitCode` may be present when a delegated process has its own result code.

Consumers must reject an unknown `schemaVersion` instead of guessing field meanings. Error
objects may include a `details` mapping with command-specific information.

## Commands and state

The stable command names currently exposed by JSON responses are:

- `version` and `doctor` for metadata and dependency diagnostics;
- `shell.start`, `shell.kill`, `shell.log` and `shell.ipc` for Quickshell lifecycle actions;
- `ipc.show` and `ipc.call` for public Quickshell IPC forwarding;
- `record.start`, `record.status`, `record.pause`, `record.resume`, `record.stop` and `record.watch`;
- `audio.start`, `audio.status`, `audio.stop` and `audio.watch`;
- `clipboard.status`, `clipboard.list`, `clipboard.inspect`, `clipboard.restore`,
  `clipboard.delete`, `clipboard.clear`, `clipboard.config`, `clipboard.watch` and `clipboard.store`.

Recording and audio responses include a versioned state object. Stable state fields include
`state`, `sessionId`, `pid`, `processStartTicks`, `processStartedAtMs`, `startedAtMs`,
`completedAtMs`, `updatedAtMs`, `temporaryPath`, `outputPath` and `error` when applicable.
The recording command additionally reports `type`, `target`, `fps` and `audio`; audio
reports the selected source and final duration when available. Paths are external paths,
not implementation-specific temporary object names.

Clipboard history responses report the selected operation, dependency/capability information,
watcher state and, for entries, the stable `id`, MIME/payload classification and decoded
metadata. Binary payload data is not embedded in the normal JSON response.

Text entries are exposed as literal plain text. When a clipboard offer contains both
`text/plain` and `text/html`, the plain-text representation is stored. HTML-only source is
stored byte-for-byte and exposed as literal text within the normal preview/search limits; it
is not rendered, stripped, entity-decoded or promoted to an embedded image. Markdown,
CSS, CSV, XML, JSON and other supported text follow the same literal-content rule.
Restoring UTF-8 text publishes `text/plain;charset=utf-8`. No charset transcoding
is performed; bytes that cannot be safely interpreted as UTF-8 remain binary.

## Clipboard capabilities and representation

The clipboard capability object retains the existing fields and adds explicit
representation limits, without changing `schemaVersion: 1`:

```json
{
  "inspect": true,
  "preview": true,
  "mimeRestore": true,
  "mimeAwareStore": true,
  "singleRepresentation": true,
  "multiMime": false,
  "originalMimePreserved": false
}
```

`mimeAwareStore` means MIME-guided selection of one representation. cliphist owns
history, deduplication, limits, deletion and the saved payload bytes. key-cli does
not persist the original MIME, the other offered representations, or a MIME sidecar.
`selectedMime` describes only that store operation, not persistent entry metadata.

`mimeRestore` means semantic restoration: key-cli classifies decoded bytes using
image signatures, supported file-list syntax or safe UTF-8 text, then publishes one
appropriate type through wl-copy. It does not reproduce the original MIME offer.
Image data and GNOME copy/cut/file-list payloads retain their bytes; textual formats
are displayed literally and restored as plain text. Preview truncation and display
summaries never modify the saved payload. The classification may differ from the
original type, especially when text itself contains valid file-list syntax.

Consumers such as Clavis should keep validating the envelope and the capabilities
they use, accept additive capability fields, and display clipboard text with an
explicit plain-text mode. Missing new fields on older key-cli builds do not imply
support for multi-MIME or original MIME preservation.

## Clipboard history configuration and list limits

`key clipboard config --format json` reads the saved history limit.
`key clipboard config --max-items 500 --format json` changes it. Both return:

```json
{"schemaVersion":1,"command":"clipboard.config","ok":true,"error":null,"maxItems":500}
```

This command needs no clipboard tools or running watcher. The sole persistent setting
is `maxItems` in `$XDG_CONFIG_HOME/key/clipboard.json`, falling back to
`~/.config/key/clipboard.json` when XDG_CONFIG_HOME is unset or empty. A missing file
means 500 and reading it does not create a file. Writes accept only integers 50–750
in steps of 50, use an atomic replacement, and return the saved value. Invalid input
returns exit 2 with `invalid_clipboard_limit`; unreadable or corrupt existing files
return exit 1 with `clipboard_config_read_failed`, and write failures return exit 1
with `clipboard_config_write_failed`. Failed writes do not replace the old configuration.
A corrupt file is never silently reset, including when a new value is supplied.

Changing the limit applies trimming on the next actual save of a new record.
Configuration reads/writes and list queries never prune history. Every existing
watcher's `key clipboard store --stdin` callback reads the current configuration before
calling `cliphist -max-items N store`; cliphist retains the newest N records using its
native trimming. Other cliphist settings (database path, deduplication, size limits,
etc.) remain in force. Sensitive, cleared, empty and otherwise rejected events do not
trigger extra cleanup. Increasing the limit cannot restore previously removed entries.
No shell or watcher restart is required.

`clipboard.list --limit N` continues to default to 100 and clamps requests to 1–750
lightweight records, skipping invalid lines. This query limit is independent of the
saved history limit. Spotlight explicitly requests 750, then inspects details on demand;
a list query does not decode every entry. Inspection's extended `searchText` and the
original payload restoration protocol are unchanged.

## Clipboard capture

`key clipboard watch` keeps one `wl-paste --watch` process. Each callback applies
key's MIME priority to the current offer: file lists, supported images, plain text,
then Markdown, HTML, other `text/*`, and the known textual application types
`application/json`, `application/xml`, `application/xhtml+xml`. MIME matching is
case-insensitive and accepts parameters; UTF-8 variants are preferred within a
type, and the original offered name is passed to wl-paste. A matching, supported `CLIPBOARD_TYPE` reuses the callback's stdin bytes;
a preferred representation is read explicitly with `wl-paste --no-newline --type`.
Direct `clipboard store` uses the same priority and never appends a newline.

If the offer query fails, the captured MIME disappears, or the preferred read
fails, a supported stdin representation is retained. Without usable captured data,
unsupported offers and read failures return an error. Sensitive, cleared and empty
events are not stored. Payload size limits still apply before writing to cliphist.

The watch callback and a subsequent `wl-paste` query are not an atomic snapshot.
A rapid copy can replace the offer between those operations, even when MIME names
are unchanged. This adapter does not promise original-offer identity or implement
its own Wayland data-control client to eliminate that race.

## Exit codes

The process exit code is part of the contract:

- `0`: success;
- `1`: general backend failure;
- `2`: usage or argument error;
- `3`: required dependency unavailable;
- `4`: another recording/session operation is active;
- `5`: invalid or unavailable saved state;
- `6`: recorder failed to start;
- `7`: recorder failed to stop safely;
- `8`: recording/audio post-processing failed.

The JSON `ok` value and the exit code must agree. Dependency and state errors still return
the standard envelope so callers can report a useful error without parsing human text.

## Keyboard LED state

`key keyboard status --format json` returns one envelope. `key keyboard watch --format jsonl`
flushes an initial envelope, then emits only state/availability or device snapshot events.
Each line uses `schemaVersion: 1`, `command: keyboard.watch` (or `keyboard.status`),
`ok`, `error`, `event`, `available`, `capsLock`, and `numLock`.

```json
{"schemaVersion":1,"command":"keyboard.watch","ok":true,"event":"snapshot","available":true,"capsLock":false,"numLock":true,"error":null}
```

- `snapshot`: startup, topology/permission rescan, lost-frame recovery. Update the UI
  baseline without announcing a toggle. Recovery is always a fresh baseline.
- `changed`: a normal LED state change. OSD may announce it according to user settings.
- Unavailable: `ok: false`, `available: false`, both lock values `null`, structured
  `error` (`code`, `message`, optional `details`). Unknown must not be presented as off.
- No heartbeat or inactivity deadline. A quiet stream is healthy. Device permission
  failures keep watch waiting for udev recovery. Fatal initialization errors emit one
  unavailable snapshot and exit. EOF is unavailable; a new process starts with a snapshot.

Values aggregate LED states across keyboards using OR. EV_KEY is never interpreted as
lock state and ordinary keys are never output. SYN_DROPPED discards events until SYN_REPORT,
then reads authoritative LEDs. No sysfs polling fallback or clipboard side effects.
`status` returns 0 if available, 3 for missing Python dependencies, 5 for unavailable devices
or monitor errors. `watch` uses 3/5 for fatal errors, 130 for Ctrl-C, and exits cleanly on a
closed output pipe. A recoverable unavailable message does not terminate watch.

Doctor adds `keyboard` (the status envelope), `clipboard.watcherRunning`,
`clipboard.services`, `installation.keyPath`, `installation.overrides`, and `runtimeReady`.
Existing `features.clipboard-watch` and exit codes still describe executable dependencies;
`features.keyboard` includes actual device availability. Runtime readiness is separate from
whether a user chooses to enable capture or grant keyboard access.

## Recording subscriptions

`key record watch --format jsonl` and `key audio watch --format jsonl` subscribe to
screen and audio sessions respectively. Each line is a schemaVersion 1 envelope with
`command: record.watch` / `audio.watch`, `ok`, `error`, all common recording state
fields, any kind-specific fields (for example `source`, `type`, `target`), and
`event: snapshot | changed`. An absent session returns the complete idle base state
with empty session ID and `updatedAtMs: 0`.

The first line is a snapshot, including on reconnect. Subsequent lines carry a full
state only when the authoritative state changes. Consumers use snapshots as silent
baselines, and deduplicate command/watch results by `sessionId + updatedAtMs`.
Every persisted write advances `updatedAtMs` strictly, including across sessions and
multiple writes in the same millisecond. Older revisions must not replace newer ones.
Command errors without a complete state are operation failures, not session transitions.

The authoritative files remain `$XDG_RUNTIME_DIR/key/{record,audio}.json`. Linux
inotify watches their directory for atomic replacement; it supports independent
subscribers without socket ownership, writer notifications, or extra dependencies.
Events may coalesce; the next message always reflects the current authoritative file,
not a durable log of every intermediate state. Writers work without any subscriber.
There is no periodic status query, stat scan, heartbeat, or polling fallback.

A verified recorder is also monitored with `os.pidfd_open()` and a blocking selector.
PID, process start ticks, executable and output argument are verified before and after
opening the pidfd. On exit the watcher blocks on the recording operation lock and
rereads the file: a normal stop's completed/error result is preserved. Only the same
still-active session with a missing verified process becomes `recorder_exited`.
This prevents stop/finalization lock contention from becoming `recording_busy` failure.

Idle and terminal snapshots/changes end the stream with exit 0 (a session error remains
`ok: false` in its envelope). Missing kernel facilities, corrupt state or other watch
failures return a state-less `recording_watch_unavailable` envelope and exit 5; consumers
must preserve their session state. Ctrl-C exits 130, diagnostics go to stderr and a
closed output pipe exits cleanly. The watcher is session-scoped and is not a daemon;
it does not discover future sessions after exiting idle. A shell may query status once
at initialization, then subscribe when its command response establishes an active session.

## Saved-file actions

`key file reveal /absolute/path --format json` and `key file open /absolute/path --format json`
return the standard schemaVersion 1 envelope (`file.reveal` / `file.open`). They never change
recording state, create a missing file, or start a watcher. Successful dispatch includes
`path`, `fileExists`, and `mode` (`reveal`, `directory`, or `open`). Dispatch means the
launcher was started, not proof that a window appeared or received focus; later application
errors are outside this one-shot interface. Existing activation environment is inherited.

Reveal queries `xdg-mime` for the default `inode/directory` application and reads its desktop
entry using XDG data-directory precedence. Standard Yazi entries use `xdg-terminal-exec --
yazi -- PATH`; standard Dolphin and Nautilus entries use their `--select` interface. Custom
launchers and other applications fall back to opening the parent directory with `xdg-open`,
wrapped in `xdg-terminal-exec` for `Terminal=true`. No unrelated FileManager1 service is
activated in place of the user's chosen default. `mode: directory` does not promise selection.

If a file is missing but its parent exists, reveal opens the parent with `fileExists: false`.
Open uses `xdg-open` on the exact existing file. Relative paths are rejected (exit 2), missing
executables return exit 3, and missing paths, invalid desktop configuration, query timeout or
launch errors return exit 5. Paths are passed as individual arguments, never shell source.
`xdg-utils` is required; terminal file managers additionally require `xdg-terminal-exec`.

### Installation diagnostics

`key doctor --json` preserves `installation.keyPath` as the PATH-selected key and the
existing exit-code contract. Additional fields distinguish `invocation`, `currentKey`,
`pythonExecutable`, `modulePath`, inherited `clavisKey`, `userUnits` (effective
FragmentPath/DropInPaths/ExecStart), `keyboardRules` (precedence order), `sourceManifest`
and `developmentManifest`. `currentKey` is null for direct Python script/module invocation
without a CLI entry point. Expected source installs/development overrides are not
errors. `runtimeReady` still describes optional keyboard/clipboard runtime readiness,
not main-program installation success. No unrelated environment variables are emitted.
