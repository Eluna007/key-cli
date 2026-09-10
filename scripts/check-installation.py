#!/usr/bin/env python3
"""Exercise editable/regular installs, same-version update and checkout-free uninstall."""

import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import venv


def run(argv):
    subprocess.run([str(x) for x in argv], check=True)


def output(python, expression):
    return subprocess.check_output([str(python), "-c", expression], text=True).strip()


def main():
    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("source_installer", repo / "scripts/installer.py")
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    with tempfile.TemporaryDirectory(prefix="key-cli-install-test-") as temporary:
        temp = Path(temporary)
        root = temp / "final root with spaces"
        root.mkdir()
        args = SimpleNamespace(
            root=root, uninstall=False, wheelhouse=str(Path(sys.argv[1]).resolve().parent)
        )
        installer.deploy(args)
        python = root / "usr/local/lib/key-cli/venv/bin/python"
        imported = output(python, "import key_cli; print(key_cli.__file__)")
        assert str(root) in imported and str(repo) not in imported
        unit = root / "usr/local/lib/systemd/user/clavis-clipboard.service"
        assert str(root / "usr/local/bin/key") in unit.read_text()
        assert not (root / "etc/udev/rules.d" / installer.RULE).exists()
        assert not (root / "usr/local/share/key-cli/keyboard-manifest.json").exists()
        data = root / "home/test/.config/key/clipboard.json"
        data.parent.mkdir(parents=True)
        data.write_text("user data")

        checkout = temp / "editable checkout"
        shutil.copytree(
            repo,
            checkout,
            ignore=shutil.ignore_patterns(
                ".git",
                ".venv",
                "build",
                "dist",
                "*.egg-info",
                "__pycache__",
                ".pytest_cache",
                ".ruff_cache",
            ),
        )
        init = checkout / "src/key_cli/__init__.py"
        init.write_text(init.read_text() + '\nSOURCE_INSTALL_PROBE = "before"\n')
        development = temp / "development"
        venv.EnvBuilder(with_pip=True).create(development)
        devpython = development / "bin/python"
        run([devpython, "-m", "pip", "install", "setuptools>=68"])
        run(
            [devpython, "-m", "pip", "install", "--no-deps", "--no-build-isolation", "-e", checkout]
        )
        assert output(devpython, "import key_cli; print(key_cli.SOURCE_INSTALL_PROBE)") == "before"
        init.write_text(init.read_text().replace('"before"', '"after ordinary source edit"'))
        assert (
            output(devpython, "import key_cli; print(key_cli.SOURCE_INSTALL_PROBE)")
            == "after ordinary source edit"
        )
        wheels = temp / "updated-wheels"
        run(
            [
                devpython,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--no-build-isolation",
                "--no-cache-dir",
                "--wheel-dir",
                wheels,
                checkout,
            ]
        )
        args.wheelhouse = str(wheels)
        installer.deploy(args)
        shutil.rmtree(checkout)
        assert (
            output(python, "import key_cli; print(key_cli.SOURCE_INSTALL_PROBE)")
            == "after ordinary source edit"
        )
        run([root / "usr/local/bin/key", "version"])
        # Retained script and sources work with the original checkout unavailable to them.
        saved = root / "usr/local/share/key-cli/installer.py"
        run(
            [
                sys.executable,
                saved,
                "--keyboard",
                "enable",
                "--acknowledge-keyboard-access",
                "--root",
                root,
            ]
        )
        run([sys.executable, saved, "--keyboard", "disable", "--root", root])
        run([root / "usr/local/share/key-cli/uninstall.sh", "--root", root])
        assert not (root / "usr/local/bin/key").exists()
        assert not python.exists()
        assert data.read_text() == "user data"
    print("Isolated installation behavior checks passed")


if __name__ == "__main__":
    main()
