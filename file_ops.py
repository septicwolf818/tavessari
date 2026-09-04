"""File I/O operations for the text editor (tab-based)."""

import os

from gi.repository import Gtk, GLib, Gio  # type: ignore


class FileOps:
    """Encapsulates file open/save/new operations delegated to win."""

    def __init__(self, win):
        self.win = win

    # ------------------------------------------------------------------
    # New file
    # ------------------------------------------------------------------

    def on_new(self):
        self.win._new_tab()
        if self.win.view is not None:
            self.win.view.grab_focus()

    # ------------------------------------------------------------------
    # Open file (dialog-driven)
    # ------------------------------------------------------------------

    def on_open(self):
        dlg = Gtk.FileDialog(title="Open file")
        dlg.open(self.win, None, self._on_open_done)

    def _on_open_done(self, dlg, result):
        try:
            f = dlg.open_finish(result)
        except GLib.Error:
            return
        path = f.get_path()
        if path:
            self.win.open_path_in_tab(path)

    # ------------------------------------------------------------------
    # Save file (current-path or dialog-driven)
    # ------------------------------------------------------------------

    def on_save(self):
        tab = self.win._active_tab()
        if tab is None:
            return
        if tab.file_path:
            self._write_to(tab.file_path, tab)
        else:
            self.on_save_as()

    def on_save_as(self):
        tab = self.win._active_tab()
        if tab is None:
            return
        dlg = Gtk.FileDialog(title="Save file")
        if tab.file_path:
            dlg.set_initial_file(Gio.File.new_for_path(tab.file_path))
        dlg.save(self.win, None, self._on_save_done)

    def _on_save_done(self, dlg, result):
        try:
            f = dlg.save_finish(result)
        except GLib.Error:
            return
        path = f.get_path()
        tab = self.win._active_tab()
        if path and tab is not None:
            self._write_to(path, tab)

    # ------------------------------------------------------------------
    # Internal write helper
    # ------------------------------------------------------------------

    def _write_to(self, path, tab):
        start, end = tab.buffer.get_bounds()
        text = tab.buffer.get_text(start, end, False)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as e:
            self.win._error(f"Could not save file:\n{e}")
            return
        tab.file_path = path
        tab.close_confirmed = False
        tab.buffer.set_modified(False)
        self.win._make_tab_permanent(tab)
        # GTK Source availability is determined by whether win.style_manager exists.
        if hasattr(self.win, "style_manager"):
            tab.buffer.set_language(self.win._detect_language(path, text))
        self.win._refresh_tab_title(tab)
        self.win._update_lang_label()
        self.win.update_title()
        self.win.update_status()
