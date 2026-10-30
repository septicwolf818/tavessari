import os

import gi  # type: ignore
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
try:
    gi.require_version('GtkSource', '5')
    from gi.repository import GtkSource  # type: ignore
    HAS_GTKSOURCE = True
except (ImportError, ValueError):
    HAS_GTKSOURCE = False
from gi.repository import Gtk, Adw, Gio, GLib  # type: ignore

from ollama import OllamaClient
from ui_utils import _new_dialog, _show_dialog, _set_accessible_label
from editor_tab import EditorTab
from ai_controller import AICtrl
from sidebar import FileBrowser
from file_ops import FileOps
from find_replace import FindReplace


class EditorWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("TAVESSARI")
        self.set_default_size(1000, 650)
        self.ollama = OllamaClient()

        # --- state ---
        self._temp_tabs = set()  # kept for sidebar.py compatibility
        self.file_ops = FileOps(self)  # delegation object for file I/O

        # --- layout ---
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Set up toast overlay so we can use Adw.Toast for non-blocking messages
        if not getattr(self, 'toast_overlay', None):
            overlay = Adw.ToastOverlay()
            overlay.set_child(vbox)
            self.set_content(overlay)
            self.toast_overlay = overlay


        self.header_bar = Adw.HeaderBar()
        vbox.append(self.header_bar)

        new_btn = Gtk.Button.new_from_icon_name("document-new-symbolic")
        new_btn.set_tooltip_text("New file (Ctrl+N)")
        _set_accessible_label(new_btn, "New file")
        new_btn.connect("clicked", self.file_ops.on_new)
        self.header_bar.pack_start(new_btn)

        open_btn = Gtk.Button.new_from_icon_name("document-open-symbolic")
        open_btn.set_tooltip_text("Open file (Ctrl+O)")
        _set_accessible_label(open_btn, "Open file")
        open_btn.connect("clicked", self.file_ops.on_open)
        self.header_bar.pack_start(open_btn)

        save_btn = Gtk.Button.new_from_icon_name("document-save-symbolic")
        save_btn.set_tooltip_text("Save (Ctrl+S)")
        _set_accessible_label(save_btn, "Save file")
        save_btn.connect("clicked", self.file_ops.on_save)
        self.header_bar.pack_start(save_btn)

        save_as_btn = Gtk.Button.new_from_icon_name("document-save-as-symbolic")
        save_as_btn.set_tooltip_text("Save As (Ctrl+Shift+S)")
        _set_accessible_label(save_as_btn, "Save file as")
        save_as_btn.connect("clicked", self.file_ops.on_save_as)
        self.header_bar.pack_start(save_as_btn)

        folder_btn = Gtk.Button.new_from_icon_name("folder-open-symbolic")
        folder_btn.set_tooltip_text("Open folder (Ctrl+Shift+O)")
        _set_accessible_label(folder_btn, "Open folder")
        folder_btn.connect("clicked", lambda *_: self.file_browse.open_folder())
        self.header_bar.pack_start(folder_btn)

        self.side_toggle = Gtk.ToggleButton()
        img_side = Gtk.Image.new_from_icon_name("view-paged-symbolic")
        lbl_side = Gtk.Label(label="Sidebar")
        side_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        side_box.append(img_side)
        side_box.append(lbl_side)
        self.side_toggle.set_child(side_box)
        self.side_toggle.set_tooltip_text("Show/hide file browser")
        _set_accessible_label(self.side_toggle, "Show or hide file browser")
        self.side_toggle.set_active(True)
        self.side_toggle.connect("toggled", lambda *args: self.file_browse.on_side_toggle(*args))
        self.side_toggle.set_visible(False)
        self.header_bar.pack_start(self.side_toggle)

        self.ln_toggle = Gtk.ToggleButton(label="1\u2261")
        self.ln_toggle.set_tooltip_text("Show/hide line numbers")
        self.ln_toggle.set_active(True)
        self.ln_toggle.connect("toggled", self.on_toggle_line_numbers)
        self.header_bar.pack_end(self.ln_toggle)

        self.wrap_toggle = Gtk.ToggleButton(label="↵")
        self.wrap_toggle.set_tooltip_text("Toggle word wrap")
        self.wrap_toggle.set_active(True)
        self.wrap_toggle.connect("toggled", self.on_toggle_wrap)
        self.header_bar.pack_end(self.wrap_toggle)

        # AI menu built by AICtrl
        self._ai_ctrl = AICtrl(self)
        self._ai_ctrl.build_ai_menu(self.header_bar)

        # --- content: single container, swapped between editor-only and paned ---
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.main_box.set_vexpand(True)
        self.main_box.set_hexpand(True)
        vbox.append(self.main_box)

        # sidebar widget (not yet in any parent)
        self.side_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.side_box.set_size_request(200, -1)
        self.file_browse = FileBrowser(self)
        self.side_box.append(self.file_browse)

        # --- editor (tab bar + tab view) ---
        self.editor_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.editor_box.set_hexpand(True)
        self.editor_box.set_vexpand(True)

        self.tab_view = Adw.TabView()
        self.tab_view.set_vexpand(True)
        self.tab_view.set_hexpand(True)
        self.tab_view.connect("notify::selected-page",
                              self._on_selected_page_changed)
        self.tab_view.connect("notify::n-pages", self._on_n_pages_changed)
        self.tab_view.connect("close-page", self._on_close_page)

        self.tab_bar = Adw.TabBar()
        self.tab_bar.set_view(self.tab_view)
        tab_plus = Gtk.Button.new_from_icon_name("list-add-symbolic")
        tab_plus.set_tooltip_text("New file (Ctrl+N)")
        _set_accessible_label(tab_plus, "New tab")
        tab_plus.connect("clicked", self.file_ops.on_new)
        self.tab_bar.set_end_action_widget(tab_plus)
        self.editor_box.append(self.tab_bar)
        self.editor_box.append(self.tab_view)

        # start with editor only (no folder open)
        self.main_box.append(self.editor_box)

        # --- status bar ---
        status = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        status.set_margin_start(12)
        status.set_margin_end(12)
        status.set_margin_top(4)
        status.set_margin_bottom(4)
        vbox.append(status)

        self.dirty_label = Gtk.Label(label="")
        self.cursor_label = Gtk.Label(label="Ln 1, Col 1")
        self.stats_label = Gtk.Label(label="Lines 1  Words 0")
        self.stats_label.set_hexpand(True)
        self.stats_label.set_halign(Gtk.Align.END)
        self.lang_label = Gtk.Label(label="")
        self.lang_label.set_tooltip_text("Detected file type")

        status.append(self.dirty_label)
        status.append(self.cursor_label)
        status.append(self.stats_label)
        status.append(self.lang_label)

        if HAS_GTKSOURCE:
            self.style_manager = Adw.StyleManager.get_default()
            self.style_manager.connect("notify::dark", self._on_theme_changed)

        self._new_tab()

        # --- Find & Replace -------------------------------------------
        self.find_btn = Gtk.Button.new_from_icon_name("edit-find-symbolic")
        self.find_btn.set_tooltip_text("Find & Replace (Ctrl+F)")
        _set_accessible_label(self.find_btn, "Find and replace")
        self.find_btn.set_sensitive(False)
        self.header_bar.pack_end(self.find_btn)

        self.find_replace = FindReplace(self)
        self.find_popover.set_parent(self.find_btn)
        self.find_btn.connect("clicked", lambda *_: self.find_replace.open())

        self.update_title()
        self.update_status()
        self._update_lang_label()

        self.connect("close-request", self._on_close_request)

        # shortcuts
        for name, callback, accel in [
            ("new-file", self.file_ops.on_new, "<Control>n"),
            ("open", self.file_ops.on_open, "<Control>o"),
            ("save", self.file_ops.on_save, "<Control>s"),
            ("save-as", self.file_ops.on_save_as, "<Control><Shift>s"),
            ("close-tab", self.on_close_tab, "<Control>w"),
            ("open-folder", self.file_browse.open_folder, "<Control><Shift>o"),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
            app.set_accels_for_action(f"win.{name}", [accel])

        # Find action
        find_action = Gio.SimpleAction.new("find", None)
        find_action.connect("activate", self.on_find)
        self.add_action(find_action)
        app.set_accels_for_action("win.find", ["<Control>f"])

        # query Ollama for models at startup (async, no UI block)
        self._ai_ctrl.refresh_models()

        # Focus the editor on startup
        GLib.idle_add(self._focus_editor)

    def _focus_editor(self):
        if self.view is not None:
            self.view.grab_focus()
        return False

    # --- active tab helpers (single-tab API over the tab view) ---
    def _active_tab(self):
        page = self.tab_view.get_selected_page()
        return page.get_child() if page else None

    def _find_page(self, tab):
        """Return the TabPage for a tab, or None if not in the view."""
        for i in range(self.tab_view.get_n_pages()):
            page = self.tab_view.get_nth_page(i)
            if page.get_child() is tab:
                return page
        return None

    @property
    def buffer(self):
        tab = self._active_tab()
        return tab.buffer if tab else None

    @property
    def view(self):
        tab = self._active_tab()
        return tab.view if tab else None

    # --- tabs ---
    def _new_tab(self, path=None, text=""):
        tab = EditorTab(
            path=path, text=text,
            show_line_numbers=self.ln_toggle.get_active(),
            word_wrap=self.wrap_toggle.get_active(),
        )
        tab._loading = True

        if HAS_GTKSOURCE:
            if path:
                tab.buffer.set_language(self._detect_language(path, text))
            self._apply_style_to(tab.buffer)
        tab.buffer.connect("changed", self._on_tab_changed, tab)
        tab.buffer.connect("mark-set", self._on_tab_mark_set, tab)
        tab.buffer.connect("modified-changed", self._on_tab_modified, tab)
        tab.buffer.set_modified(False)
        tab._loading = False
        page = self.tab_view.append(tab)
        self._refresh_tab_title(tab)
        self.tab_view.set_selected_page(page)
        self.update_title()
        self.update_status()
        self._update_lang_label()
        return tab

    def _load_into_tab(self, tab, path, text):
        tab.file_path = path
        tab.close_confirmed = False
        tab._loading = True
        tab.buffer.set_text(text)
        tab.buffer.set_modified(False)
        tab._loading = False
        if HAS_GTKSOURCE:
            tab.buffer.set_language(self._detect_language(path, text))
        tab.buffer.place_cursor(tab.buffer.get_start_iter())
        self._refresh_tab_title(tab)
        page = self._find_page(tab)
        if page is not None:
            self.tab_view.set_selected_page(page)
        self.update_title()
        self.update_status()
        self._update_lang_label()

    def _refresh_tab_title(self, tab):
        name = os.path.basename(tab.file_path) if tab.file_path else "Untitled"
        page = self._find_page(tab)
        if page is None:
            return
        # Use page title prefix as source of truth for temp status
        if page.get_title().startswith('~ '):
            name = f"~ {name}"
        page.set_title(name)
        page.set_tooltip(tab.file_path or "Untitled")
        page.set_needs_attention(tab.buffer.get_modified())

    def _on_selected_page_changed(self, *args):
        tab = self._active_tab()
        if tab is not None and HAS_GTKSOURCE:
            self.ln_toggle.set_active(tab.view.get_show_line_numbers())
            self.wrap_toggle.set_active(
                tab.view.get_wrap_mode() == Gtk.WrapMode.WORD
            )
        self.update_title()
        self.update_status()
        self._update_lang_label()
        GLib.idle_add(self._update_find_btn_state)

    def _on_n_pages_changed(self, *args):
        self.tab_bar.set_visible(self.tab_view.get_n_pages() > 1)
        if self.tab_view.get_n_pages() == 0:
            self._new_tab()

    def _on_close_page(self, _view, page):
        tab = page.get_child()
        if tab.buffer.get_modified() and not tab.close_confirmed:
            GLib.idle_add(self._confirm_discard_tab, page)
            return True
        return False

    def on_close_tab(self, *args):
        page = self.tab_view.get_selected_page()
        if page is not None:
            self.tab_view.close_page(page)

    def open_path_in_tab(self, path):
        """Open a file in a tab, focusing it if already open."""
        norm = os.path.realpath(path)
        for i in range(self.tab_view.get_n_pages()):
            page = self.tab_view.get_nth_page(i)
            tab = page.get_child()
            if tab.file_path and os.path.realpath(tab.file_path) == norm:
                self.tab_view.set_selected_page(page)
                return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError as e:
            self._error(f"Could not open file:\n{e}")
            return
        active = self._active_tab()
        if (active is not None and active.file_path is None
                and not active.buffer.get_modified()
                and active.buffer.get_char_count() == 0):
            self._load_into_tab(active, path, text)
        else:
            self._new_tab(path, text)

    def _on_tab_changed(self, _buf, tab):
        if not tab._loading and tab.buffer.get_modified():
            self._make_tab_permanent(tab)
        if tab is self._active_tab():
            self.update_status()

    def _on_tab_mark_set(self, _buf, *args):
        tab = args[-1]
        if tab is self._active_tab():
            self.update_status()

    def _on_tab_modified(self, _buf, tab):
        self._refresh_tab_title(tab)
        if tab is self._active_tab():
            self.update_title()

    # --- sidebar: show/hide layout ---
    def _set_main_layout(self, show_sidebar):
        for widget in (self.editor_box, self.side_box):
            parent = widget.get_parent()
            if parent is None:
                continue
            if isinstance(parent, Gtk.Paned):
                if parent.get_start_child() is widget:
                    parent.set_start_child(None)
                if parent.get_end_child() is widget:
                    parent.set_end_child(None)
            else:
                parent.remove(widget)
        child = self.main_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.main_box.remove(child)
            child = nxt
        if show_sidebar:
            paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
            paned.set_wide_handle(True)
            paned.set_start_child(self.side_box)
            paned.set_end_child(self.editor_box)
            paned.set_position(250)
            self.main_box.append(paned)
        else:
            self.main_box.append(self.editor_box)

    def _show_sidebar(self):
        self._set_main_layout(True)

    def _show_editor_only(self):
        self._set_main_layout(False)

    def _make_tab_permanent(self, tab):
        """Promote a temp tab to permanent on edit or double-click."""
        if tab not in self._temp_tabs:
            return
        self._temp_tabs.discard(tab)
        self.update_title()
        page = self._find_page(tab)
        if page is not None:
            page.set_title(os.path.basename(tab.file_path) or "Untitled")
            page.set_tooltip(tab.file_path or "Untitled")
            page.set_needs_attention(False)

    # --- view options ---
    def on_toggle_line_numbers(self, btn):
        if self.view is not None and HAS_GTKSOURCE:
            self.view.set_show_line_numbers(btn.get_active())

    def on_toggle_wrap(self, btn):
        if self.view is not None:
            mode = Gtk.WrapMode.WORD if btn.get_active() else Gtk.WrapMode.NONE
            self.view.set_wrap_mode(mode)

    def on_find(self, *_):
        if self.buffer is None:
            return
        if self.find_replace.is_open:
            self.find_replace.close()
        else:
            self.find_replace.open()

    def _update_find_btn_state(self):
        if hasattr(self, 'find_btn') and self.find_btn:
            self.find_btn.set_sensitive(bool(self.buffer))

    # --- syntax highlight + theme ---
    def _detect_language(self, path, text=""):
        """Guess the GtkSource language from filename + content sniffing."""
        lm = GtkSource.LanguageManager.get_default()
        content_type = None
        try:
            data = text.encode("utf-8", "ignore")[:4096]
            content_type, _ = Gio.content_type_guess(path, data)
        except Exception:
            try:
                content_type, _ = Gio.content_type_guess(path, None)
            except Exception:
                content_type = None
        try:
            return lm.guess_language(path, content_type)
        except Exception:
            return None

    def _update_lang_label(self):
        buf = self.buffer
        if not HAS_GTKSOURCE or buf is None:
            self.lang_label.set_text("")
            return
        lang = buf.get_language()
        self.lang_label.set_text(lang.get_name() if lang else "Plain text")

    def _apply_style_to(self, buf):
        dark = self.style_manager.get_dark()
        sm = GtkSource.StyleSchemeManager.get_default()
        scheme = sm.get_scheme("Adwaita-dark" if dark else "Adwaita")
        if scheme is None:
            scheme = sm.get_scheme("classic-dark" if dark else "classic")
        if scheme is not None:
            buf.set_style_scheme(scheme)

    def _update_source_style(self):
        if not HAS_GTKSOURCE:
            return
        for i in range(self.tab_view.get_n_pages()):
            self._apply_style_to(self.tab_view.get_nth_page(i).get_child().buffer)

    def _on_theme_changed(self, *args):
        self._update_source_style()

    # --- status / title ---
    def update_status(self, *args):
        buf = self.buffer
        if buf is None:
            return
        start, end = buf.get_bounds()
        text = buf.get_text(start, end, False)
        lines = buf.get_line_count()
        words = len(text.split())
        it = buf.get_iter_at_mark(buf.get_insert())
        ln, col = it.get_line() + 1, it.get_line_offset() + 1
        self.cursor_label.set_text(f"Ln {ln}, Col {col}")
        self.stats_label.set_text(f"Lines {lines}  Words {words}")
        self.dirty_label.set_text("●" if buf.get_modified() else "")
        self._ai_ctrl._update_ai_sensitivity()

    def update_title(self, *args):
        tab = self._active_tab()
        if tab is None:
            self.set_title("TAVESSARI")
            return
        self._refresh_tab_title(tab)
        name = os.path.basename(tab.file_path) if tab.file_path else "Untitled"
        if tab in self._temp_tabs:
            name = f"~ {name}"
        dirty = " •" if tab.buffer.get_modified() else ""
        self.set_title(f"{name}{dirty} - TAVESSARI")

    # --- helpers ---
    def _error(self, msg):
        d = _new_dialog(self, "Error", msg)
        d.add_response("ok", "OK")
        _show_dialog(d, self, lambda r: None)

    def _confirm_discard_tab(self, page):
        tab = page.get_child()
        name = os.path.basename(tab.file_path) if tab.file_path else "Untitled"
        d = _new_dialog(
            self,
            "Unsaved changes",
            f'"{name}" has unsaved changes. Discard them?',
        )
        d.add_response("cancel", "Cancel")
        d.add_response("discard", "Discard")
        d.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_default_response("cancel")
        d.set_close_response("cancel")

        def _on_response(r):
            if r == "discard":
                tab.close_confirmed = True
                self.tab_view.close_page_finish(page, True)

        _show_dialog(d, self, _on_response)

    def _on_close_request(self, *_args):
        dirty_pages = []
        for i in range(self.tab_view.get_n_pages()):
            page = self.tab_view.get_nth_page(i)
            tab = page.get_child()
            if tab.buffer.get_modified() and not tab.close_confirmed:
                dirty_pages.append(page)
        if not dirty_pages:
            return False
        self._close_queue = list(dirty_pages)
        self._confirm_next_dirty_page()
        return True

    def _confirm_next_dirty_page(self):
        if not self._close_queue:
            self.close()
            return
        page = self._close_queue.pop(0)
        tab = page.get_child()
        name = os.path.basename(tab.file_path) if tab.file_path else "Untitled"
        d = _new_dialog(
            self,
            "Unsaved changes",
            f'"{name}" has unsaved changes. Save before closing?',
        )
        d.add_response("cancel", "Cancel")
        d.add_response("discard", "Discard")
        d.add_response("save", "Save")
        d.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("save")
        d.set_close_response("cancel")

        def _on_response(r):
            if r == "discard":
                tab.close_confirmed = True
                self.tab_view.close_page(page)
                self._confirm_next_dirty_page()
            elif r == "save":
                if tab.file_path:
                    saved = self.file_ops._write_to(tab.file_path, tab)
                    self._finish_close_after_save(page, tab, saved)
                else:
                    self.file_ops.save_as_tab(
                        tab,
                        lambda saved: self._finish_close_after_save(
                            page, tab, saved))
            else:
                self._close_queue.clear()

        _show_dialog(d, self, _on_response)

    def _finish_close_after_save(self, page, tab, saved):
        if not saved:
            self._close_queue.clear()
            return
        tab.close_confirmed = True
        self.tab_view.close_page(page)
        self._confirm_next_dirty_page()


class MyApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="pl.septicwolf818.tavessari")

    def do_activate(self):
        win = self.props.active_window or EditorWindow(self)
        win.present()


if __name__ == "__main__":
    app = MyApp()
    app.run(None)
