"""Filename-based MIME and semantic theme names, without reading file contents."""

import mimetypes


def file_mime(name: str, directory: bool = False) -> str:
    return "inode/directory" if directory else mimetypes.guess_type(name, strict=False)[0] or ""


def theme_icon(mime: str, directory: bool = False) -> str:
    return "folder" if directory else (mime or "application/octet-stream").replace("/", "-")
