complete -c key -f -n '__fish_use_subcommand' -a shell -d 'start or inspect Apollo Quickshell'
complete -c key -f -n '__fish_use_subcommand' -a ipc -d 'route Apollo IPC'
complete -c key -f -n '__fish_use_subcommand' -a record -d 'record the screen'
complete -c key -f -n '__fish_use_subcommand' -a audio -d 'record audio to M4A'
complete -c key -f -n '__fish_use_subcommand' -a clipboard -d 'operate on clipboard history'
complete -c key -f -n '__fish_use_subcommand' -a doctor -d 'check runtime dependencies'
complete -c key -f -n '__fish_use_subcommand' -a version -d 'show version metadata'

complete -c key -f -n '__fish_seen_subcommand_from shell' -l daemon -s d -d 'start qs detached'
complete -c key -f -n '__fish_seen_subcommand_from shell' -l kill -s k -d 'stop the apollo configuration'
complete -c key -f -n '__fish_seen_subcommand_from shell' -l log -s l -d 'print the qs log'
complete -c key -f -n '__fish_seen_subcommand_from shell' -l show -s s -d 'show IPC methods'

complete -c key -f -n '__fish_seen_subcommand_from ipc' -a 'show list call'
complete -c key -f -n '__fish_seen_subcommand_from record' -a 'start status stop pause resume watch'
complete -c key -f -n '__fish_seen_subcommand_from audio' -a 'start status stop watch'
complete -c key -f -n '__fish_seen_subcommand_from clipboard' -a 'list inspect restore delete clear status config'
complete -c key -f -n '__fish_seen_subcommand_from record audio; and not __fish_seen_subcommand_from watch' -l json -d 'write JSON'
complete -c key -f -n '__fish_seen_subcommand_from clipboard' -l format -a json -d 'JSON response'

complete -c key -f -n '__fish_seen_subcommand_from clipboard; and __fish_seen_subcommand_from config' -l max-items -x -a '50 100 150 200 250 300 350 400 450 500 550 600 650 700 750' -d 'Saved history limit; trims on next save'
complete -c key -f -n '__fish_seen_subcommand_from clipboard; and __fish_seen_subcommand_from list' -l limit -x -d 'Maximum entries to return (1–750)'

complete -c key -f -n '__fish_use_subcommand' -a keyboard -d 'keyboard lock LED state'
complete -c key -f -n '__fish_seen_subcommand_from keyboard' -a 'status watch'
complete -c key -f -n '__fish_seen_subcommand_from keyboard; and __fish_seen_subcommand_from status' -l format -a json
complete -c key -f -n '__fish_seen_subcommand_from keyboard record audio; and __fish_seen_subcommand_from watch' -l format -a jsonl

complete -c key -f -n '__fish_use_subcommand' -a file -d 'search, open or reveal local files'
complete -c key -n '__fish_seen_subcommand_from file' -a 'status search open reveal'
complete -c key -f -n '__fish_seen_subcommand_from file' -l format -a json
complete -c key -f -n '__fish_seen_subcommand_from file; and __fish_seen_subcommand_from search' -l limit -x -d 'Maximum results (1–50)'
complete -c key -n '__fish_seen_subcommand_from file; and __fish_seen_subcommand_from search' -l root -r -d 'Search root (repeatable; defaults to HOME)'

complete -c key -f -n '__fish_use_subcommand' -a tool -d 'Spotlight calculator, currency and time tools'
complete -c key -f -n '__fish_seen_subcommand_from tool; and not __fish_seen_subcommand_from status catalog calculator currency time' -a 'status catalog calculator currency time'
complete -c key -f -n '__fish_seen_subcommand_from tool; and __fish_seen_subcommand_from catalog' -a 'calculator currency time'
complete -c key -f -n '__fish_seen_subcommand_from tool' -l format -a json
complete -c key -f -n '__fish_seen_subcommand_from tool; and __fish_seen_subcommand_from calculator currency time' -l expression -x -d 'Expression (use --expression=VALUE for a leading minus)'
complete -c key -f -n '__fish_seen_subcommand_from tool; and __fish_seen_subcommand_from time' -l fold -x -a '0 1' -d 'Confirm a repeated local time'
