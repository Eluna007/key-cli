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

## Clipboard inspection details

`clipboard.inspect` adds compatible fields for text, without increasing the
lightweight list's text content or changing schemaVersion/capability requirements:

- `searchText`: untouched original prefix, at most `DETAIL_TEXT_LIMIT = 262144`
  Python Unicode code points. This existing search field also serves as the Details
  body; no second large body field is emitted. Whitespace and literal markup remain.
- `characterCount`: `len(text)` of the complete decoded saved text, including
  whitespace, punctuation and newline code points; not UTF-8 bytes, UTF-16 code
  units, words or graphemes.
- `textLineCount`: zero for empty text, otherwise one plus CRLF/lone CR/lone LF
  separator count, including blank and trailing lines. The old `lineCount`
  remains a nonblank summary count and is not changed.
- `textTruncated`: true exactly when the text exceeds that limit.
- `detailTextLimit`: 262144, in code points. `byteSize` remains the complete
  saved representation's byte count, never preview size or process memory.

Reliable text statistics are absent from lightweight rows and nontext records.
Consumers of older inspect responses should omit missing statistics and label
uncertain completeness as Preview. Restoration always decodes and publishes the
complete saved bytes, never the search prefix or 4096-character list preview.

File metadata adds `sizeKnown`, `metadataAvailable`, `metadataStatus` and
`modifiedTime`. `metadataStatus` is `available`, `missing`, `unreadable`, `remote`
or `unavailable`. `metadataAvailable` means stat succeeded; `sizeKnown` is true
only for a readable regular file, including a genuine zero-byte file. The legacy
`files[].byteSize` stays zero when size is unknown or inapplicable: consumers must
check `sizeKnown`. Directory content sizes are not calculated. Top-level byteSize
is the saved URI representation size, distinct from referenced file bytes.
`modifiedTime` is a nullable Unix timestamp in **seconds**, from the same stat,
matching file-search metadata. These fields describe current inspection-time
state, never copying time. Remote references are not read or mounted.

Local raster preview URLs are restricted to PNG/JPEG/GIF/WebP, readable regular
files within the existing payload/dimension bounds, with a bounded header check.
Unknown dimensions are omitted or zero and must not be displayed as 0×0. No SVG
or remote URI is exposed as a preview. File references remain file/file-list
payloads, preserving copy/cut restore semantics; source files are not archived.
Image payload caches contain the original saved bytes without transcoding.
A consumer may show frame zero of animated data without altering restoration.

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

## File search and desktop actions

All four commands use schemaVersion 1, `command`, `ok`, `error` and the existing
exit codes: 0 success, 2 invalid arguments, 3 missing dependency, 5 backend/state
failure. stdout contains one JSON object, including file argument failures.

```sh
key file status --format json
key file search --format json --limit 50 --root /absolute/root -- 'QUERY'
key file open --format json -- '/absolute/path'
key file reveal --format json -- '/absolute/path'
```

`file.status` is a capability probe (exit 0). `capabilities` declares `search`,
`open`, `reveal`; `canSearch`, `canOpen`, `canReveal` report availability.
`dependencies` contains `fd`, `gio`, `xdgTerminalExec`, `fileManager1` and the
retained diagnostic `xdgOpen` field. Open availability now depends on `gio`,
not `xdgOpen`; terminal selection is delegated to GIO. `reasons` gives null or
a diagnostic code for each operation. Missing fd does not disable open/reveal.
The D-Bus probe checks registered and activatable services without starting a
file manager. `doctor.file` exposes the same data and file feature availability.
Older key versions without `file.status` do not support the search contract.

### Search

`--root` is repeatable; omitted roots default to the current user's HOME.
Roots must be absolute existing directories. fd (or Debian's fdfind) is an
external executable, not included in the wheel. Defaults retain fd's hidden,
ignore and gitignore rules (including fd's normal repository detection), do not
follow directory symlinks and include regular files, directories and links.
There are no hardcoded build/dist/Backup exclusions or extra system roots.

Queries are case-insensitive literal filename substrings (`--fixed-strings`).
A slash switches to literal matching against absolute paths (`--full-path`).
No glob/regex, shell expansion or command substitution occurs. Whitespace-only
queries return an empty complete response without spawning fd; all other input
is preserved, including leading dashes, whitespace and single Chinese characters.
Paths use NUL output, argv arrays and no color or long-listing parsing.

`file.search` returns `query`, `roots`, `entries`, `complete`, `limited`,
`limitReasons` and `skippedNonUtf8`. Up to 50 results (CLI limit 1–50) are selected
from at most 400 unique candidates with a 3-second fd time budget. Ranking within
that pool is name equality, name prefix, name substring, then path matches;
ties use case-folded name/path and original path. This is not a guarantee of the
most relevant matches across an entire directory tree. No total count is claimed.

`limitReasons` contains `candidates`, `time`, or `results` when curtailed;
`complete` is false and `limited` true even if a timed-out search found nothing.
A complete empty response is the only definitive no-match state. fd failure is
`file_search_failed` (5), missing fd is `fd_unavailable` (3), invalid input is
`invalid_search` (2). SIGTERM/SIGINT cancels the owned fd process group and reaps
it before Python exits (`file_search_cancelled`, 5). UI requests use SIGTERM;
unrecoverable external SIGKILL cannot run Python cleanup.

Each entry contains:

| Field | Meaning |
| --- | --- |
| `name`, `path` | Original name and absolute operational UTF-8 path |
| `parentPath`, `parentName` | Containing directory path/name; root uses `/` |
| `kind` | `file`, `directory`, or `symlink` (link identity retained) |
| `mimeType` | Lightweight Python mimetypes filename guess, not content detection; unknown `application/octet-stream`, directory `inode/directory` |
| `extension` | Lowercase last suffix without dot; empty for folders/no suffix |
| `size` | Target regular-file bytes, including zero; null for folders/unavailable |
| `modifiedTime` | Unix seconds, fractional precision, from entry lstat mtime |
| `isDirectory` | Whether the entry/accessible link target is a directory |
| `isSymlink` | Whether the entry itself is a link |
| `isExecutable` | Regular target has execute access; directories always false |
| `icon` | MIME theme icon name or `folder`; UI supplies a generic fallback |
| `targetAvailable` | Stat succeeded on the entry/target |

Links retain their own path, kind and modification time. Size, directory and
executable flags describe the target when available; MIME uses the link's name.
Dangling links remain revealable, with null size and targetAvailable false.
Disappeared/inaccessible entries can be skipped independently. No recursive
size computation or per-file external probes occur. Metadata is read only for
bounded sorted candidates until enough displayable results exist.

JSON preserves Chinese, spaces, quotes, newline/tab and URI-special characters.
Non-UTF-8 filenames are skipped and counted, never lossy-decoded into another
operational path. Explicit non-UTF-8 action arguments are rejected. Paths are not
shell-escaped, home-abbreviated or resolved to symlink targets for operations.

### Open and Reveal

Successful requests retain `path`, `fileExists`, `mode` (`open`, `reveal`,
`directory`) from the previous saved-file action envelope. Success means the
system accepted the request, not proof that a window is visible.

Open queries the selected file's GIO `standard::content-type`, selects the default
application with `g_app_info_get_default_for_type`, and submits that file through
`g_app_info_launch`. Directories use `inode/directory`. An isolated Python helper
uses the typed GIO C API through stdlib ctypes; no PyGObject dependency is required.
This deliberately bypasses `x-scheme-handler/file`, which `gio open` prioritizes
over MIME associations. Existing user associations are never rewritten. Open
waits for GIO to confirm launch acceptance (not application exit), and never directly executes a file or parses desktop
Exec. Executable regular files and desktop/application launcher content are
blocked with `file_execution_blocked`; Reveal remains available. Broken links
return `file_missing`. Apps remains the launcher for executable content.

Reveal first waits for session D-Bus `org.freedesktop.FileManager1.ShowItems`
at `/org/freedesktop/FileManager1`, signature `ass`, with a one-element array of
`Path.as_uri()` and empty startup ID. `mode: reveal` means that method accepted
the selection request. It selects the directory entry or link itself, not a
resolved target. Missing service, timeout or method failure falls back to
the same MIME-based GIO opener on the parent (`mode: directory`), which does not promise selection.
An already missing entry also falls back to its existing parent with
`fileExists: false`. Missing parent gives `directory_missing`.

This replaces the former per-manager desktop-entry adapters. The FileManager1
provider can differ from the default directory handler. Neither MIME associations
nor D-Bus configuration is changed. TUI managers rely on users' existing system
association/terminal launcher setup. GIO honors `Terminal=true` and uses the
system terminal launcher (`xdg-terminal-exec` is preferred by current GLib),
so both terminal editors and file managers receive a terminal. key does not parse
Exec or launch a naked yazi/nvim process. The xdg-open generic fallback is not
used: it can ignore Terminal=true, wait for application exit and mask failures.
Missing associations or launch failures reported by GIO are errors. Acceptance
cannot prove the terminal/application will subsequently display or stay running.

Runtime tools: fd/fdfind, GLib (`gio`), systemd (`busctl`, optional for
selection when the parent-directory fallback is available). The wheel cannot
install these OS packages. D-Bus waits at most 3 seconds, open acceptance waits
5 seconds. `file_action_timeout` reports unconfirmed acceptance; it does not kill
an application that may already have been opened. Other action failures return
`file_action_failed`; missing opener returns `dependency_missing` (3). Search
cancellation never terminates applications opened by these independent requests.

### Clipboard file theme icons

Clipboard `files[]` elements now additionally include `themeIcon`: a semantic
freedesktop theme icon name, using the same filename-based MIME policy as Files
metadata's `icon` (`video-mp4`, `application-pdf`, or `folder` for directories).
Unknown MIME types use `application-octet-stream` for this theme hint, while the
existing Clipboard `mimeType` fallback remains unchanged. This is independent of
Clipboard's existing `icon` / `category`: `icon` remains a Material Symbol name
(e.g. `video_file`) and must not be used as a theme icon name. No envelope or
schema version changes. Older responses may omit `themeIcon`; clients can derive
a MIME hint and use generic theme / Material fallbacks.

Theme hints require no file-content reads, search process, theme-directory scan
or network access. The desktop resolves its current theme and handles missing or
unloadable resources. File URIs, errors, copy/cut and restore bytes are unchanged.
