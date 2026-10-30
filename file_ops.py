"""File I/O operations for the text editor (tab-based)."""

from gi.repository import Gtk, GLib, Gio  # type: ignore


class FileOps:
    """Encapsulates file open/save/new operations delegated to win."""

    def __init__(self, win):
        self.win = win

    # ------------------------------------------------------------------
    # New file
    # ------------------------------------------------------------------

    def on_new(self, *args):
        self.win._new_tab()
        if self.win.view is not None:
            self.win.view.grab_focus()

    # ------------------------------------------------------------------
    # Open file (dialog-driven)
    # ------------------------------------------------------------------

    def on_open(self, *args):
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

    def on_save(self, *args):
        tab = self.win._active_tab()
        if tab is None:
            return
        if tab.file_path:
            self._write_to(tab.file_path, tab)
        else:
            self.on_save_as()

    def on_save_as(self, *args):
        tab = self.win._active_tab()
        if tab is None:
            return
        self.save_as_tab(tab)

    def save_as_tab(self, tab, on_complete=None):
        """Save a specific tab, optionally reporting whether it was saved."""
        dlg = Gtk.FileDialog(title="Save file")
        if tab.file_path:
            dlg.set_initial_file(Gio.File.new_for_path(tab.file_path))
        dlg.save(
            self.win, None,
            lambda dialog, result: self._on_save_done(
                dialog, result, tab, on_complete))

    def _on_save_done(self, dlg, result, tab, on_complete=None):
        try:
            f = dlg.save_finish(result)
        except GLib.Error:
            if on_complete is not None:
                on_complete(False)
            return
        path = f.get_path()
        saved = bool(path and self._write_to(path, tab))
        if on_complete is not None:
            on_complete(saved)

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
            return False
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
        return True
