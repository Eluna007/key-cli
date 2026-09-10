#!/usr/bin/env bash
set -euo pipefail
repo_root=$(git -C "$(dirname -- "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)
package_dir=$(mktemp -d "${TMPDIR:-/tmp}/key-cli-packages.XXXXXX")
python3 - "${repo_root}" "${package_dir}" <<'PY'
import pathlib, subprocess, sys, tarfile, tomllib
root, target = map(pathlib.Path, sys.argv[1:])
version = tomllib.loads((root / 'pyproject.toml').read_text())['project']['version']
paths = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z', '--cached', '--others', '--exclude-standard']).split(b'\0')
with tarfile.open(target / f'key-cli-{version}.tar.gz', 'w:gz') as archive:
    for raw in sorted(set(paths)):
        if raw:
            relative = pathlib.Path(raw.decode())
            path = root / relative
            if path.is_file():
                archive.add(path, arcname=str(pathlib.Path(f'key-cli-{version}') / relative))
(target / 'PKGBUILD').write_bytes((root / 'packaging/arch/PKGBUILD').read_bytes())
PY
printf 'Building packages in %s (no installation or service activation)\n' "${package_dir}"
cd "${package_dir}"
makepkg "$@"
python3 "${repo_root}/scripts/check-packages.py" \
    "${package_dir}"/key-cli-[0-9]*.pkg.tar.* \
    "${package_dir}"/key-cli-keyboard-access-[0-9]*.pkg.tar.*
