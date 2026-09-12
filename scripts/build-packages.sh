#!/usr/bin/env bash
set -euo pipefail
repo_root=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
package_dir=$(mktemp -d "${TMPDIR:-/tmp}/key-cli-packages.XXXXXX")
python3 "$repo_root/scripts/release.py" source --working-tree --output "$package_dir"
version=$(python3 "$repo_root/scripts/release.py" version)
python3 "$repo_root/scripts/release.py" render --output "$package_dir" --archive "$package_dir/key-cli-$version.tar.gz"
printf 'Building packages in %s (no installation or service activation by default)\n' "$package_dir"
cd "$package_dir"
makepkg "$@"
mapfile -t packages < <(makepkg --packagelist)
python3 "$repo_root/scripts/check-package.py" "${packages[@]}"
