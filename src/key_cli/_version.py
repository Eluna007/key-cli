"""Read the version resource shared by source installs and built wheels."""

from importlib.resources import files

__version__ = files("key_cli").joinpath("VERSION").read_text(encoding="utf-8").strip()
