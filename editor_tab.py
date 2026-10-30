import gi # type: ignore
gi.require_version('Gtk', '4.0')
try:
    gi.require_version('GtkSource', '5')
    from gi.repository import GtkSource # type: ignore
    HAS_GTKSOURCE = True
except (ImportError, ValueError):
    HAS_GTKSOURCE = False
    GtkSource = None # type: ignore

from gi.repository import Gtk # type: ignore

class EditorTab(Gtk.Box):
    """One tab page: scrolled source view + its file state."""

    def __init__(self, path=None, text="", show_line_numbers=True, word_wrap=True):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.file_path = path
        self.close_confirmed = False
        self._loading = True  # suppress change-during-load promotion

        if HAS_GTKSOURCE and GtkSource is not None:
            self.buffer = GtkSource.Buffer()
            self.view = GtkSource.View(buffer=self.buffer)
            self.view.set_show_line_numbers(show_line_numbers)
            self.view.set_monospace(True)
            self.view.set_highlight_current_line(True)
            self.view.set_tab_width(4)
            self.buffer.set_highlight_syntax(True)
            self.buffer.set_highlight_matching_brackets(True)
        else:
            self.buffer = Gtk.TextBuffer()
            self.view = Gtk.TextView(buffer=self.buffer)
            self.view.set_monospace(True)
            self.view.set_wrap_mode(
                Gtk.WrapMode.WORD if word_wrap else Gtk.WrapMode.NONE
            )

        if text:
            self.buffer.set_text(text)
        scrolled = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scrolled.set_child(self.view)
        self.append(scrolled)
        self._loading = False
