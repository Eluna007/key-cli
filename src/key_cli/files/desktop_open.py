"""One-shot GIO MIME dispatch, isolated from the CLI and application lifetime.

Use GIO's typed C API via stdlib ctypes. This needs the existing GLib runtime,
not PyGObject, and leaves desktop Exec expansion/Terminal handling to GIO.
"""

from __future__ import annotations

import ctypes as C
import os
import sys


class GError(C.Structure):
    _fields_ = [("domain", C.c_uint), ("code", C.c_int), ("message", C.c_char_p)]


class DesktopOpener:
    def __init__(self):
        self.gio = C.CDLL("libgio-2.0.so.0")
        self.glib = C.CDLL("libglib-2.0.so.0")
        self.gobject = C.CDLL("libgobject-2.0.so.0")
        pointer = C.c_void_p
        error_out = C.POINTER(C.POINTER(GError))
        signatures = [
            (self.gio, "g_file_new_for_path", pointer, [C.c_char_p]),
            (
                self.gio,
                "g_file_query_info",
                pointer,
                [pointer, C.c_char_p, C.c_int, pointer, error_out],
            ),
            (self.gio, "g_file_info_get_content_type", C.c_char_p, [pointer]),
            (self.gio, "g_app_info_get_default_for_type", pointer, [C.c_char_p, C.c_int]),
            (self.gio, "g_app_info_launch", C.c_int, [pointer, pointer, pointer, error_out]),
            (self.gobject, "g_object_unref", None, [pointer]),
            (self.glib, "g_list_append", pointer, [pointer, pointer]),
            (self.glib, "g_list_free", None, [pointer]),
            (self.glib, "g_error_free", None, [C.POINTER(GError)]),
        ]
        for library, name, restype, argtypes in signatures:
            function = getattr(library, name)
            function.restype = restype
            function.argtypes = argtypes

    def launch(self, path):
        encoded = path.encode("utf-8", errors="strict")
        if not os.path.isabs(path) or b"\0" in encoded:
            raise ValueError("An absolute UTF-8 file path is required")
        file = self.gio.g_file_new_for_path(encoded)
        info = app = files = None
        error = C.POINTER(GError)()
        try:
            info = self.gio.g_file_query_info(
                file, b"standard::content-type", 0, None, C.byref(error)
            )
            if not info:
                raise OSError("Unable to determine the file content type")
            content_type = self.gio.g_file_info_get_content_type(info)
            if not content_type:
                raise OSError("The file has no content type")
            # Deliberately do not use query_default_handler/launch_default_for_uri:
            # they prefer x-scheme-handler/file over the actual content type.
            app = self.gio.g_app_info_get_default_for_type(content_type, False)
            if not app:
                raise OSError("No default application for this file type")
            files = self.glib.g_list_append(None, file)
            if not self.gio.g_app_info_launch(app, files, None, C.byref(error)):
                raise OSError("The default application rejected the launch request")
        finally:
            if error:
                self.glib.g_error_free(error)
            if files:
                self.glib.g_list_free(files)
            for obj in (app, info, file):
                if obj:
                    self.gobject.g_object_unref(obj)


def main():
    try:
        opener = DesktopOpener()
    except (OSError, AttributeError):
        return 3
    try:
        if len(sys.argv) != 2:
            return 2
        opener.launch(sys.argv[1])
        return 0
    except (OSError, ValueError, UnicodeError):
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
