import json
import os
import threading
import urllib.request
import urllib.error

import gi # type: ignore
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Pango', '1.0')
try:
    gi.require_version('GtkSource', '5')
    from gi.repository import GtkSource # type: ignore
    HAS_GTKSOURCE = True
except (ImportError, ValueError):
    HAS_GTKSOURCE = False
from gi.repository import Gtk, Adw, Gio, GLib, Pango # type: ignore


OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
TONES = ["Professional", "Friendly", "Formal", "Casual", "Concise", "Confident"]
_HAS_ALERT_DIALOG = hasattr(Adw, "AlertDialog")


def _new_dialog(parent, heading, body):
    if _HAS_ALERT_DIALOG:
        return Adw.AlertDialog(heading=heading, body=body)
    return Adw.MessageDialog(transient_for=parent, heading=heading, body=body)


def _show_dialog(dlg, parent, on_response):
    """Present a dialog and call on_response(response_str) when done."""
    if _HAS_ALERT_DIALOG:
        def _on_choose(dlg, result):
            try:
                resp = dlg.choose_finish(result)
            except GLib.Error:
                resp = "cancel"
            on_response(resp)
        dlg.choose(parent, None, _on_choose)
    else:
        def _legacy(_d, r):
            _d.disconnect(handler_id)
            on_response(r or "cancel")
        handler_id = dlg.connect("response", _legacy)
        dlg.present()


class OllamaClient:
    """Minimal Ollama client using only stdlib urllib."""

    def __init__(self, host=OLLAMA_HOST):
        self.host = host

    def list_models(self, timeout=5):
        req = urllib.request.Request(f"{self.host}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [m["name"] for m in data.get("models", []) if "name" in m]

    def generate(self, model, prompt, timeout=3600, check_cancelled=None):
        """Stream Ollama ``/api/generate`` line-by-line with instant cancellation.

        Each yielded line is NDJSON. We parse it and accumulate ``response`` fields
        until ``done` is true, or the user cancels.  Cancellation fires within one
        I/O timeout window (~2 s by default).
        """
        import time

        payload = json.dumps(
            {"model": model, "prompt": prompt, "stream": True}
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.host}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        result_parts: list[str] = []
        start_time = time.time()
        
        with urllib.request.urlopen(req, timeout=10) as resp:
            for line in resp:
                if (time.time() - start_time) > timeout:
                    raise InterruptedError("Timed out")

                if check_cancelled and check_cancelled():
                    raise InterruptedError("Cancelled by user")

                try:
                    obj = json.loads(line.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

                if obj.get("done"):
                    return "".join(result_parts).strip()

                result_parts.append(obj.get("response", ""))

        raise InterruptedError("Timed out")


class EditorTab(Gtk.Box):
    """One tab page: scrolled source view + its file state."""

    def __init__(self, path=None, text="", show_line_numbers=True, word_wrap=True):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.file_path = path
        self.close_confirmed = False
        self._loading = True  # suppress change-during-load promotion

        if HAS_GTKSOURCE:
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


class EditorWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("Text Editor")
        self.set_default_size(1000, 650)
        self.ollama = OllamaClient()
        self._ai_busy = False
        self.folder_root = None
        self._temp_tabs = set()  # set of EditorTab refs for sidebar temp-opened

        # --- layout ---
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(vbox)

        header = Adw.HeaderBar()
        vbox.append(header)

        new_btn = Gtk.Button.new_from_icon_name("document-new-symbolic")
        new_btn.set_tooltip_text("New file (Ctrl+N)")
        new_btn.connect("clicked", self.on_new)
        header.pack_start(new_btn)

        open_btn = Gtk.Button.new_from_icon_name("document-open-symbolic")
        open_btn.set_tooltip_text("Open file (Ctrl+O)")
        open_btn.connect("clicked", self.on_open)
        header.pack_start(open_btn)

        save_btn = Gtk.Button.new_from_icon_name("document-save-symbolic")
        save_btn.set_tooltip_text("Save (Ctrl+S)")
        save_btn.connect("clicked", self.on_save)
        header.pack_start(save_btn)

        save_as_btn = Gtk.Button.new_from_icon_name("document-save-as-symbolic")
        save_as_btn.set_tooltip_text("Save As (Ctrl+Shift+S)")
        save_as_btn.connect("clicked", self.on_save_as)
        header.pack_start(save_as_btn)

        folder_btn = Gtk.Button.new_from_icon_name("folder-open-symbolic")
        folder_btn.set_tooltip_text("Open folder (Ctrl+Shift+O)")
        folder_btn.connect("clicked", self.on_open_folder)
        header.pack_start(folder_btn)

        self.side_toggle = Gtk.ToggleButton(icon_name="view-paged-symbolic")
        self.side_toggle.set_tooltip_text("Show/hide file browser")
        self.side_toggle.set_active(True)
        self.side_toggle.connect("toggled", self.on_side_toggle)
        self.side_toggle.set_visible(False)
        header.pack_start(self.side_toggle)

        self.ln_toggle = Gtk.ToggleButton(label="1≡")
        self.ln_toggle.set_tooltip_text("Show/hide line numbers")
        self.ln_toggle.set_active(True)
        self.ln_toggle.connect("toggled", self.on_toggle_line_numbers)
        header.pack_end(self.ln_toggle)

        self.wrap_toggle = Gtk.ToggleButton(label="↵")
        self.wrap_toggle.set_tooltip_text("Toggle word wrap")
        self.wrap_toggle.set_active(True)
        self.wrap_toggle.connect("toggled", self.on_toggle_wrap)
        header.pack_end(self.wrap_toggle)

        self._build_ai_menu(header)

        # --- content: single container, swapped between editor-only and paned ---
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.main_box.set_vexpand(True)
        self.main_box.set_hexpand(True)
        vbox.append(self.main_box)

        # --- sidebar (kept as a reusable widget, not yet in any parent) ---
        self.side_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.side_box.set_size_request(200, -1)

        side_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        side_header.set_margin_start(8)
        side_header.set_margin_end(8)
        side_header.set_margin_top(8)
        side_header.set_margin_bottom(4)
        self.side_box.append(side_header)
        self.folder_label = Gtk.Label(label="No folder")
        self.folder_label.set_hexpand(True)
        self.folder_label.set_xalign(0.0)
        self.folder_label.set_ellipsize(Pango.EllipsizeMode.END)
        side_header.append(self.folder_label)
        side_refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        side_refresh.set_tooltip_text("Refresh file tree")
        side_refresh.connect("clicked", lambda *_: self._rebuild_file_tree())
        side_header.append(side_refresh)
        side_close = Gtk.Button.new_from_icon_name("window-close-symbolic")
        side_close.set_tooltip_text("Close folder")
        side_close.connect("clicked", lambda *_: self._close_folder())
        side_header.append(side_close)

        side_scrolled = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        self.side_box.append(side_scrolled)
        self.file_list = Gtk.ListView()
        self._click_gesture = Gtk.GestureClick()
        self._click_gesture.set_button(1)
        self._click_gesture.connect("pressed", self._on_file_pressed)
        self._click_gesture.connect("released", self._on_file_released)
        self.file_list.add_controller(self._click_gesture)
        self._last_click_time_ms = 0
        self._single_click_pending_id = None
        self._last_click_time = 0
        self._click_pending = None  # Gtk.SingleSelection from the click press
        self._tree_factory = Gtk.SignalListItemFactory()
        self._tree_factory.connect("setup", self._on_tree_setup)
        self._tree_factory.connect("bind", self._on_tree_bind)
        self.file_list.set_factory(self._tree_factory)
        side_scrolled.set_child(self.file_list)
        self._rebuild_file_tree()

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
        tab_plus.connect("clicked", self.on_new)
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

        self.update_title()
        self.update_status()
        self._update_lang_label()

        self.connect("close-request", self._on_close_request)

        # shortcuts
        for name, callback, accel in [
            ("new-file", self.on_new, "<Control>n"),
            ("open", self.on_open, "<Control>o"),
            ("save", self.on_save, "<Control>s"),
            ("save-as", self.on_save_as, "<Control><Shift>s"),
            ("close-tab", self.on_close_tab, "<Control>w"),
            ("open-folder", self.on_open_folder, "<Control><Shift>o")
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
            app.set_accels_for_action(f"win.{name}", [accel])

        # query Ollama for models at startup (async, no UI block)
        self.refresh_models()

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

    @property
    def current_path(self):
        tab = self._active_tab()
        return tab.file_path if tab else None

    # --- tabs ---
    def _new_tab(self, path=None, text=""):
        tab = EditorTab(
            path=path, text=text,
            show_line_numbers=self.ln_toggle.get_active(),
            word_wrap=self.wrap_toggle.get_active(),
        )
        tab._loading = True  # guard against changed-during-init promotion
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

    def _on_n_pages_changed(self, *args):
        self.tab_bar.set_visible(self.tab_view.get_n_pages() > 1)
        if self.tab_view.get_n_pages() == 0:
            self._new_tab()

    def _on_close_page(self, _view, page):
        tab = page.get_child()
        if tab.buffer.get_modified() and not tab.close_confirmed:
            self._confirm_discard_tab(page)
            return True  # veto until user confirms
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
        # any edit in a temp tab makes it permanent
        if not tab._loading:
            self._make_tab_permanent(tab)
        if tab is self._active_tab():
            self.update_status()

    def _on_tab_mark_set(self, _buf, *args):
        # args: (iter, mark, tab) - tab is the user_data appended last
        tab = args[-1]
        if tab is self._active_tab():
            self.update_status()

    def _on_tab_modified(self, _buf, tab):
        self._refresh_tab_title(tab)
        if tab is self._active_tab():
            self.update_title()

    # --- folder sidebar ---
    def on_open_folder(self, *args):
        dlg = Gtk.FileDialog(title="Open folder")
        dlg.select_folder(self, None, self._on_folder_done)

    def _on_folder_done(self, dlg, result):
        try:
            folder = dlg.select_folder_finish(result)
        except GLib.Error:
            return  # dismissed
        self.folder_root = folder
        self.folder_label.set_text(folder.get_basename() or folder.get_path())
        self._rebuild_file_tree()
        self.side_toggle.set_visible(True)
        self.side_toggle.set_active(True)
        self._show_sidebar()

    def _close_folder(self):
        self.folder_root = None
        self.folder_label.set_text("No folder")
        self._rebuild_file_tree()
        self.side_toggle.set_visible(False)
        self.side_toggle.set_active(False)
        self._show_editor_only()

    def on_side_toggle(self, btn):
        if btn.get_active():
            self._show_sidebar()
        else:
            self._show_editor_only()

    def _show_sidebar(self):
        """Swap main_box to paned (resizable sidebar + editor)."""
        # detach editor_box and side_box from any parent
        ep = self.editor_box.get_parent()
        if ep is not None:
            if type(ep).__name__ == "Paned":
                ep.set_start_child(None)
                ep.set_end_child(None)
            else:
                ep.remove(self.editor_box)
        sp = self.side_box.get_parent()
        if sp is not None:
            if type(sp).__name__ == "Paned":
                sp.set_start_child(None)
                sp.set_end_child(None)
            else:
                sp.remove(self.side_box)
        # remove whatever is currently in main_box
        child = self.main_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.main_box.remove(child)
            child = nxt
        # build paned
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_wide_handle(True)
        paned.set_start_child(self.side_box)
        paned.set_end_child(self.editor_box)
        paned.set_position(250)
        self.main_box.append(paned)

    def _show_editor_only(self):
        """Swap main_box to editor only (no sidebar)."""
        ep = self.editor_box.get_parent()
        if ep is not None:
            if type(ep).__name__ == "Paned":
                ep.set_start_child(None)
                ep.set_end_child(None)
            else:
                ep.remove(self.editor_box)
        sp = self.side_box.get_parent()
        if sp is not None:
            if type(sp).__name__ == "Paned":
                sp.set_start_child(None)
                sp.set_end_child(None)
            else:
                sp.remove(self.side_box)
        child = self.main_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.main_box.remove(child)
            child = nxt
        self.main_box.append(self.editor_box)

    def _list_dir_children(self, gfile):
        try:
            enumerator = gfile.enumerate_children(
                "standard::name,standard::type",
                Gio.FileQueryInfoFlags.NONE, None)
        except GLib.Error:
            return []
        dirs, files = [], []
        try:
            while True:
                info = enumerator.next_file(None)
                if info is None:
                    break
                name = info.get_name()
                if name.startswith("."):
                    continue
                if info.get_file_type() == Gio.FileType.DIRECTORY:
                    dirs.append(name)
                else:
                    files.append(name)
        except GLib.Error:
            pass
        try:
            enumerator.close(None)
        except GLib.Error:
            pass
        children = [gfile.get_child(n) for n in sorted(dirs, key=str.casefold)]
        children += [gfile.get_child(n) for n in sorted(files, key=str.casefold)]
        return children

    def _create_dir_model(self, item):
        try:
            is_dir = (item.query_file_type(
                Gio.FileQueryInfoFlags.NONE, None)
                == Gio.FileType.DIRECTORY)
        except GLib.Error:
            return None
        if not is_dir:
            return None
        store = Gio.ListStore.new(Gio.File)
        for child in self._list_dir_children(item):
            store.append(child)
        return store

    def _rebuild_file_tree(self):
        root_store = Gio.ListStore.new(Gio.File)
        if self.folder_root is not None:
            for child in self._list_dir_children(self.folder_root):
                root_store.append(child)
        self.tree_model = Gtk.TreeListModel.new(
            root_store, False, False, self._create_dir_model)
        sel = Gtk.SingleSelection.new(self.tree_model)
        self.file_list.set_model(sel)

    def _on_tree_setup(self, _factory, list_item):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        icon = Gtk.Image()
        label = Gtk.Label(xalign=0.0, hexpand=True)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        box.append(icon)
        box.append(label)
        expander = Gtk.TreeExpander()
        expander.set_child(box)
        expander._icon = icon
        expander._label = label
        list_item.set_child(expander)

    def _on_tree_bind(self, _factory, list_item):
        row = list_item.get_item()  # Gtk.TreeListRow
        expander = list_item.get_child()
        expander.set_list_row(row)
        gfile = row.get_item()
        name = gfile.get_basename() or gfile.get_path() or "?"
        expander._label.set_text(name)
        expander._label.set_tooltip_text(gfile.get_path() or name)
        is_dir = row.is_expandable()
        expander.set_hide_expander(not is_dir)
        expander._icon.set_from_icon_name(
            "folder-symbolic" if is_dir else "text-x-generic-symbolic")

    # --- folder sidebar click logic ---
    def _find_file_at_offset(self, x, y):
        """Find Gio.File and whether it is expandable at (x,y) in file_list coordinates."""
        child = self.file_list.get_child() or self.side_box
        sel_model = self.file_list.get_model()
        if sel_model is None:
            return None, False
        
        root = sel_model.get_model()  # TreeListModel wrapping Gio.ListStore of Gio.File
        n_items = root.get_n_items()

        # Try get_path_at_offset on the scrolled window (parent) -> listview rows
        path_result, gtk_path = child.get_path_at_offset(int(x), int(y))
        if path_result != Gtk.PathResult.SUCCESS or gtk_path is None:
            return None, False

        gtk_idx = gtk_path.get_indices()[0]  # 1-based
        row_obj = root.get_item(gtk_idx - 1)
        info = row_obj.get_child()
        
        is_dir = row_obj.is_expandable()
        return info, is_dir

    def _on_file_pressed(self, gesture, n_press, x, y):
        """Handle left-click on sidebar items."""
        self._clear_pending_click()
        
        info, is_dir = self._find_file_at_offset(x, y)
        if info is None:
            return
        gfile = info if hasattr(info, 'get_file') else info
        path = gfile.get_path() if hasattr(gfile, 'get_path') else None
        if not path:
            return
            
        self._pending_click_path = path

        if is_dir:
            # Toggle expand/collapse directly via gtk_path
            gesture.disconnect_by_func(self._on_file_pressed)
            gesture.ungrab()
            gesture.connect("released", lambda *_: ())  # prevent further fires
            result, p = self.side_box.get_path_at_offset(int(x), int(y))
            if result == Gtk.PathResult.SUCCESS and p is not None:
                idx = p.get_indices()[0] - 1
                sel = self.file_list.get_model()
                row = sel.get_model().get_item(idx)
                cur_exp = row.get_expanded()
                row.set_expanded(not cur_exp)
            gesture.connect("released", self._on_file_released)
            return

        # Same file as previous click → double-click candidate
        if self._pending_click_path == getattr(self, "_prev_click_path", None):
            now = int(GLib.get_monotonic_time() * 1000)
            diff = now - getattr(self, "_prev_click_time_ms", 0)
            if 200 <= diff < 700:
                # Valid double-click timing
                self._on_file_doubleclick(path)
                return

        # First click on this file → schedule single-click
        self._prev_click_path = path
        self._prev_click_time_ms = int(GLib.get_monotonic_time() * 1000)
        self._single_click_pending_id = GLib.timeout_add(
            350, self._on_single_click_timeout, path
        )

    def _on_file_released(self, gesture, n_press, x, y):
        """Handle release — do nothing extra."""
        pass

    def _clear_pending_click(self):
        eid = getattr(self, "_single_click_pending_id", None)
        if eid is not None:
            GLib.source_remove(eid)
            self._single_click_pending_id = None

    def _on_single_click_timeout(self, path):
        """Called after 350ms with no second click (single-click)."""
        self._clear_pending_click()
        
        # Check if it's still a temp tab → promote
        norm = os.path.realpath(path)
        for i in range(self.tab_view.get_n_pages()):
            page = self.tab_view.get_nth_page(i)
            tab = page.get_child()
            if tab in self._temp_tabs and tab.file_path and os.path.realpath(tab.file_path) == norm:
                self._make_tab_permanent(tab)
                return
    
        # Open as temp, closing previous temps first
        self._sidebar_open_file(path)

    def _sidebar_open_file(self, path):
        """Open a file in sidebar (temp open / single-click)."""
        norm = os.path.realpath(path)
        
        # already open as permanent? focus it
        for i in range(self.tab_view.get_n_pages()):
            page = self.tab_view.get_nth_page(i)
            tab = page.get_child()
            if tab.file_path and os.path.realpath(tab.file_path) == norm:
                if tab not in self._temp_tabs:
                    self.tab_view.set_selected_page(page)
                    return

        # already open as temp? focus it, close other temps
        for i in range(self.tab_view.get_n_pages()):
            page = self.tab_view.get_nth_page(i)
            tab = page.get_child()
            if tab in self._temp_tabs and tab.file_path and os.path.realpath(tab.file_path) == norm:
                self.tab_view.set_selected_page(page)
                return

        # Not open → close temps, open fresh
        self._close_all_temp_tabs()
        
        gfile = Gio.File.new_for_path(path)
        if not gfile.get_is_valid():
            return
        
        try:
            with open(path, "rb") as _f:
                chunk = _f.read(8192)
        except OSError as e:
            self._error(f"Could not read file:\n{e}")
            return

        # Binary check
        if b"\x00" in chunk:
            dlg = _new_dialog(self, "Binary File", 
                              f"'{os.path.basename(path)}' is a binary file and cannot be opened.")
            dlg.add_response("ok", "OK")
            _show_dialog(dlg, self, lambda r: None)
            return

        gfile = row.get_item()
        path = gfile.get_path()
        if not path:
            return
        self._last_click_time_ms = 0

        # check if it's expandable (a directory)
        if row.is_expandable():
        if row.is_expandable():
            row.set_expanded(not row.get_expanded())
            return

        norm = os.path.realpath(path)

        # already open as permanent? just focus it
        for i in range(self.tab_view.get_n_pages()):
            page = self.tab_view.get_nth_page(i)
            tab = page.get_child()
            if tab.file_path and os.path.realpath(tab.file_path) == norm:
                if tab not in self._temp_tabs:
                    self.tab_view.set_selected_page(page)
                    return

        # already open as temp? promote it to permanent, close all other temp tabs
        for i in range(self.tab_view.get_n_pages()):
            page = self.tab_view.get_nth_page(i)
            tab = page.get_child()
            if tab in self._temp_tabs and tab.file_path and os.path.realpath(tab.file_path) == norm:
                self._make_tab_permanent(tab)
                self.tab_view.set_selected_page(page)
                return

        # not open at all - close temp tabs, open fresh permanent
        self._close_all_temp_tabs()
        self.open_path_in_tab(path)

    def _open_temp_tab(self, path):
        """Open a file as a temporary tab (sidebar single-click).

        If already open as permanent, just focus it.
        If already open as temp, just focus it.
        Otherwise close existing temp tabs, then open fresh.
        """
        norm = os.path.realpath(path)
        # already open as permanent?
        for i in range(self.tab_view.get_n_pages()):
            page = self.tab_view.get_nth_page(i)
            tab = page.get_child()
            if tab.file_path and os.path.realpath(tab.file_path) == norm:
                if tab not in self._temp_tabs:
                    self.tab_view.set_selected_page(page)
                    return
        # already open as temp?
        for i in range(self.tab_view.get_n_pages()):
            page = self.tab_view.get_nth_page(i)
            tab = page.get_child()
            if tab in self._temp_tabs and tab.file_path and os.path.realpath(tab.file_path) == norm:
                self.tab_view.set_selected_page(page)
                return
        # close previous temp tabs
        self._close_all_temp_tabs()
        # open new - check if text file, then read
        try:
            with open(path, "rb") as _f:
                chunk = _f.read(8192)
                _f.seek(0)
        except OSError as e:
            self._error(f"Could not open file:\n{e}")
            return

        # Check if binary (contains null bytes)
        if b"\x00" in chunk:
            dlg = _new_dialog(self, "Binary File", "This file is a binary and cannot be opened as text.")
            dlg.add_response("ok", "OK")
            _show_dialog(dlg, self, lambda r: None)
            return

        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError as e:
            self._error(f"Could not open file:\n{e}")
            return
        # reuse pristine untitled tab if possible
        active = self._active_tab()
        if (active is not None and active not in self._temp_tabs
                and active.file_path is None
                and not active.buffer.get_modified()
                and active.buffer.get_char_count() == 0):
            tab = active
            self._load_into_tab(tab, path, text)
        else:
            tab = self._new_tab(path, text)
        self._temp_tabs.add(tab)
        page = self._find_page(tab)
        if page is not None:
            page.set_title(f"~ {os.path.basename(path)}")
            page.set_needs_attention(True)
        page = self._find_page(tab)
        if page is not None:
            self.tab_view.set_selected_page(page)

    def _close_all_temp_tabs(self):
        """Close all sidebar-temp-opened tabs (no unsaved prompt)."""
        to_close = []
        for tab in list(self._temp_tabs):
            if not tab.buffer.get_modified():
                page = self._find_page(tab)
                if page is not None:
                    to_close.append(page)
        for page in to_close:
            tab = page.get_child()
            self._temp_tabs.discard(tab)
            self.tab_view.close_page(page)

    def _make_tab_permanent(self, tab):
        """Promote a temp tab to permanent on edit or double-click."""
        if tab not in self._temp_tabs:
            return
        self._temp_tabs.discard(tab)
        page = self._find_page(tab)
        if page is not None:
            page.set_title(os.path.basename(tab.file_path) or "Untitled")
            page.set_needs_attention(False)

    # --- AI menu ---
    def _build_ai_menu(self, header):
        self.ai_button = Gtk.MenuButton(label="✨ AI")
        self.ai_button.set_tooltip_text("Connecting to Ollama…")
        self.ai_button.set_sensitive(False)
        header.pack_end(self.ai_button)

        pop = Gtk.Popover()
        self.ai_button.set_popover(pop)
        self.ai_popover = pop
        self._ai_pending = None  # selection snapshot taken when menu opens
        pop.connect("show", self._on_ai_popover_shown)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        pop.set_child(box)

        model_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(model_row)
        model_row.append(Gtk.Label(label="Model:"))
        self.model_store = Gtk.StringList()
        self.model_dropdown = Gtk.DropDown(model=self.model_store)
        self.model_dropdown.set_hexpand(True)
        model_row.append(self.model_dropdown)
        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Refresh models")
        refresh_btn.connect("clicked", lambda *_: self.refresh_models())
        model_row.append(refresh_btn)

        box.append(Gtk.Separator())

        self.ai_hint = Gtk.Label(label="Select text in the editor to enable AI actions.")
        self.ai_hint.set_wrap(True)
        box.append(self.ai_hint)

        self.ai_action_buttons = []
        summarize_btn = Gtk.Button(label="Summarize")
        summarize_btn.connect("clicked", lambda *_: self._ai_action("summarize"))
        summarize_btn.set_sensitive(False)
        box.append(summarize_btn)
        self.ai_action_buttons.append(summarize_btn)

        grammar_btn = Gtk.Button(label="Rewrite with proper grammar")
        grammar_btn.connect("clicked", lambda *_: self._ai_action("grammar"))
        grammar_btn.set_sensitive(False)
        box.append(grammar_btn)
        self.ai_action_buttons.append(grammar_btn)

        extend_btn = Gtk.Button(label="Extend")
        extend_btn.set_tooltip_text("Let the AI guess your intent and extend the selection")
        extend_btn.connect("clicked", lambda *_: self._ai_action("extend"))
        extend_btn.set_sensitive(False)
        box.append(extend_btn)
        self.ai_action_buttons.append(extend_btn)

        tone_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(tone_row)
        tone_row.append(Gtk.Label(label="Tone:"))
        self.tone_store = Gtk.StringList.new(TONES)
        self.tone_dropdown = Gtk.DropDown(model=self.tone_store)
        self.tone_dropdown.set_hexpand(True)
        self.tone_dropdown.set_tooltip_text("Pick a tone, then Rewrite")
        tone_row.append(self.tone_dropdown)
        tone_go_btn = Gtk.Button(label="Rewrite")
        tone_go_btn.set_tooltip_text("Rewrite selection in the selected tone")
        tone_go_btn.connect("clicked", self._on_tone_go)
        tone_go_btn.set_sensitive(False)
        tone_row.append(tone_go_btn)
        self.ai_action_buttons.append(tone_go_btn)

        extract_btn = Gtk.Button(label="Extract key information")
        extract_btn.set_tooltip_text("Extract key facts, entities, and summaries from the selection")
        extract_btn.connect("clicked", lambda *_: self._ai_action("extract"))
        extract_btn.set_sensitive(False)
        box.append(extract_btn)
        self.ai_action_buttons.append(extract_btn)

        custom_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.append(custom_row)
        custom_row.append(Gtk.Label(label="Custom:"))
        self.custom_entry = Gtk.Entry()
        self.custom_entry.set_hexpand(True)
        self.custom_entry.set_placeholder_text("Custom request...")
        self.custom_entry.set_tooltip_text("Free-form request to send to AI")
        self.custom_entry.connect("activate", lambda *_: self._on_custom_send())
        custom_row.append(self.custom_entry)
        self.custom_go_btn = Gtk.Button(label="Send")
        self.custom_go_btn.set_tooltip_text("Send custom request")
        self.custom_go_btn.connect("clicked", lambda *_: self._on_custom_send())
        custom_row.append(self.custom_go_btn)

        self._custom_prompt = ""  # buffer for multi-line input when user presses Ctrl+Return / Enter in entry

    def _on_tone_go(self, _btn):
        idx = self.tone_dropdown.get_selected()
        tone = (
            self.tone_store.get_string(idx)
            if idx != Gtk.INVALID_LIST_POSITION
            else TONES[0]
        )
        self._ai_action("tone", tone=tone)

    def _on_custom_send(self):
        user_text = self.custom_entry.get_text()
        if not user_text.strip():
            self.ai_hint.set_text("Type a custom request first.")
            return
        self._ai_action("custom", user_custom=user_text)
        self.custom_entry.set_text("")

    def _on_ai_popover_shown(self, _pop):
        """Snapshot the selection when the AI menu opens.

        Opening the menu moves focus out of the editor, which can hide or
        drop the visual selection - the snapshot lets actions still work.
        """
        self._ai_pending = self._ai_selection_snapshot()

    def selected_model(self):
        idx = self.model_dropdown.get_selected()
        if idx == Gtk.INVALID_LIST_POSITION or idx >= len(self.model_store):
            return None
        return self.model_store.get_string(idx)

    def refresh_models(self):
        self.ai_button.set_tooltip_text("Connecting to Ollama…")
        threading.Thread(target=self._fetch_models_worker, daemon=True).start()

    def _fetch_models_worker(self):
        try:
            models = self.ollama.list_models()
        except Exception as e:
            GLib.idle_add(self._on_models_failed, str(e))
        else:
            GLib.idle_add(self._on_models_loaded, models)

    def _on_models_loaded(self, models):
        self.model_store.splice(0, len(self.model_store), models)
        if models:
            self.model_dropdown.set_selected(0)
            self.ai_button.set_sensitive(True)
            self.ai_button.set_tooltip_text("AI actions (Ollama)")
        else:
            self.ai_button.set_sensitive(False)
            self.ai_button.set_tooltip_text("No models found.")
        self._update_ai_sensitivity()
        return False

    def _on_models_failed(self, err):
        self.ai_button.set_sensitive(False)
        self.ai_button.set_tooltip_text("Ollama is unavailable")
        self._update_ai_sensitivity()
        return False

    # --- AI actions (operate on the active tab) ---
    def _update_ai_sensitivity(self):
        """Enable AI action items only when text is selected (and idle)."""
        if not hasattr(self, "ai_action_buttons"):
            return
        buf = self.buffer
        enabled = (
            buf is not None
            and buf.get_has_selection()
            and not self._ai_busy
            and self.ai_button.get_sensitive()
        )
        for b in self.ai_action_buttons:
            b.set_sensitive(enabled)
        if hasattr(self, "tone_dropdown"):
            self.tone_dropdown.set_sensitive(enabled)
        if hasattr(self, "custom_go_btn"):
            self.custom_go_btn.set_sensitive(enabled)
        if hasattr(self, "custom_entry"):
            self.custom_entry.set_sensitive(enabled)

    def _ai_selection_snapshot(self):
        """Snapshot selection as (full_text, start, end, sel_text) or None."""
        buf = self.buffer
        if buf is None or not buf.get_has_selection():
            return None
        bstart, bend = buf.get_bounds()
        full = buf.get_text(bstart, bend, False)
        start, end = buf.get_selection_bounds()
        so, eo = start.get_offset(), end.get_offset()
        return (full, so, eo, buf.get_text(start, end, False))

    def _ai_resolve_selection(self):
        """Live selection, falling back to the menu-open snapshot.

        Returns (sel_text, start_off, end_off) or None. The snapshot is only
        trusted if the buffer text is unchanged since the menu opened.
        """
        snap = self._ai_selection_snapshot()
        if snap is not None:
            _, so, eo, text = snap
            return (text, so, eo)
        pending = getattr(self, "_ai_pending", None)
        buf = self.buffer
        if pending is not None and buf is not None:
            full, so, eo, text = pending
            bstart, bend = buf.get_bounds()
            cur = buf.get_text(bstart, bend, False)
            if cur == full and 0 <= so < eo <= len(cur) and cur[so:eo] == text:
                return (text, so, eo)
        return None

    def _ai_action(self, kind, tone="", user_custom=""):
        if self._ai_busy:
            return
        resolved = self._ai_resolve_selection()
        if resolved is None:
            self.ai_hint.set_text("Select text in the editor first.")
            return
        text, start_off, end_off = resolved
        if not text.strip():
            self._error("The selection is empty.")
            return
        model = self.selected_model()
        if not model:
            self._error("No Ollama model selected.")
            return
        if kind == "summarize":
            prompt = (
                "Summarize the following text concisely. "
                "Return only the summary, no preamble:\n\n" + text
            )
            title = "Summary"
        elif kind == "grammar":
            prompt = (
                "Rewrite the following text with correct grammar and spelling. "
                "Keep the original meaning and tone. "
                "Return only the rewritten text, no explanation:\n\n" + text
            )
            title = "Grammar fix"
        elif kind == "extend":
            prompt = (
                "The user selected the following text in a document. "
                "Infer the user's intent - what are they writing about, "
                "and what would logically come next? "
                "Continue writing from where the selection ends, "
                "matching the style, tone, and language. "
                "Return only the continuation (the new text to append), "
                "no explanation:\n\n" + text
            )
            title = "Extend"
        elif kind == "extract":
            prompt = (
                "Extract the key information, facts, entities, and important points "
                "from the following text. Present the result as a clear bulleted list. "
                "Return only the extracted content:\n\n" + text
            )
            title = "Extract key info"
        elif kind == "custom":
            prompt = (
                "The user selected the following text in a document.\n"
                "His request related to this text is: {user_custom}\n"
                "Return response that fullfills the request.\n"
                "No explanation, no preamble.\n"
                "Text the user has selected:\n\n" + text
            ).replace("{user_custom}", user_custom)
            title = f"Custom: {user_custom[:30]}"
        else:
            prompt = (
                f"Rewrite the following text in a {tone.lower()} tone. "
                "Keep the meaning. Return only the rewritten text:\n\n" + text
            )
            title = f"Tone: {tone}"
        self.ai_popover.popdown()
        state = self._open_ai_dialog(title, text, start_off, end_off)
        self._ai_busy = True
        self._update_ai_sensitivity()
        threading.Thread(
            target=self._ai_worker,
            args=(model, prompt, state),
            daemon=True,
        ).start()

    def _open_ai_dialog(self, title, orig_text, start_off, end_off):
        """Popup showing the original selection plus a live result area."""
        state = {"cancelled": False, "result": None}
        d = _new_dialog(
            self,
            f"AI - {title}",
            "Replace the selection, append the result after it, or cancel.",
        )
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        orig_label = Gtk.Label(label="Original selection:")
        orig_label.set_halign(Gtk.Align.START)
        orig_label.add_css_class("dim-label")
        content.append(orig_label)
        orig_tv = Gtk.TextView()
        orig_tv.get_buffer().set_text(orig_text)
        orig_tv.set_wrap_mode(Gtk.WrapMode.WORD)
        orig_tv.set_editable(False)
        orig_tv.set_cursor_visible(False)
        orig_sc = Gtk.ScrolledWindow()
        orig_sc.set_size_request(440, 120)
        orig_sc.set_propagate_natural_height(True)
        orig_sc.set_child(orig_tv)
        content.append(orig_sc)

        res_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        res_label = Gtk.Label(label="AI result:")
        res_label.set_halign(Gtk.Align.START)
        res_label.add_css_class("dim-label")
        res_row.append(res_label)
        spinner = Gtk.Spinner(spinning=True)
        spinner.set_tooltip_text("Working on it…")
        res_row.append(spinner)
        content.append(res_row)

        res_tv = Gtk.TextView()
        res_tv.get_buffer().set_text("Working on it…")
        res_tv.set_wrap_mode(Gtk.WrapMode.WORD)
        res_tv.set_editable(False)
        res_tv.set_cursor_visible(False)
        res_sc = Gtk.ScrolledWindow()
        res_sc.set_size_request(440, 180)
        res_sc.set_propagate_natural_height(True)
        res_sc.set_child(res_tv)
        content.append(res_sc)

        d.set_extra_child(content)
        d.add_response("cancel", "Cancel")
        d.add_response("append", "Append")
        d.add_response("replace", "Replace")
        d.set_response_enabled("append", False)
        d.set_response_enabled("replace", False)
        d.set_response_appearance("replace", Adw.ResponseAppearance.SUGGESTED)
        d.set_close_response("cancel")
        state["dialog"] = d
        state["spinner"] = spinner
        state["result_tv"] = res_tv
        _show_dialog(d, self, lambda r: self._on_ai_dialog_response(
            r, state, start_off, end_off
        ))
        return state

    def _ai_worker(self, model, prompt, state):
        try:
            result = self.ollama.generate(
                model, prompt,
                check_cancelled=lambda: state.get("cancelled", False),
            )
        except InterruptedError:
            GLib.idle_add(self._on_ai_cancelled, state)
        except Exception as e:
            GLib.idle_add(self._on_ai_finished, state, "", str(e))
        else:
            GLib.idle_add(self._on_ai_finished, state, result, "")

    def _on_ai_cancelled(self, state):
        self._ai_busy = False
        self._update_ai_sensitivity()
        return False

    def _on_ai_finished(self, state, result, err):
        self._ai_busy = False
        self._update_ai_sensitivity()
        if state.get("cancelled"):
            return False
        state["spinner"].stop()
        if err or not result.strip():
            state["result_tv"].get_buffer().set_text(
                f"Error: {err or 'Ollama returned an empty response.'}"
            )
            return False
        state["result"] = result
        state["result_tv"].get_buffer().set_text(result)
        state["dialog"].set_response_enabled("append", True)
        state["dialog"].set_response_enabled("replace", True)
        return False

    def _restore_selection(self, start_off, end_off):
        buf = self.buffer
        if buf is None:
            return
        end_off = min(end_off, buf.get_end_iter().get_offset())
        if start_off < end_off:
            buf.select_range(
                buf.get_iter_at_offset(start_off),
                buf.get_iter_at_offset(end_off),
            )
        if self.view is not None:
            self.view.grab_focus()

    def _on_ai_dialog_response(self, response, state, start_off, end_off):
        buf = self.buffer
        result = state.get("result") or ""
        dlg = state.get("dialog")
        if response == "replace" and result and buf is not None:
            end_off = min(end_off, buf.get_end_iter().get_offset())
            buf.delete(
                buf.get_iter_at_offset(start_off),
                buf.get_iter_at_offset(end_off),
            )
            buf.insert(buf.get_iter_at_offset(start_off), result)
            new_end = start_off + len(result)
            buf.select_range(
                buf.get_iter_at_offset(start_off),
                buf.get_iter_at_offset(new_end),
            )
            if dlg:
                dlg.close()
            if self.view is not None:
                self.view.grab_focus()
        elif response == "append" and result and buf is not None:
            end_off = min(end_off, buf.get_end_iter().get_offset())
            buf.insert(buf.get_iter_at_offset(end_off), result)
            buf.select_range(
                buf.get_iter_at_offset(end_off),
                buf.get_iter_at_offset(end_off + len(result)),
            )
            if dlg:
                dlg.close()
            if self.view is not None:
                self.view.grab_focus()
        else:  # cancel: keep the original selection highlighted
            state["cancelled"] = True
            if dlg:
                dlg.close()
            self._restore_selection(start_off, end_off)

    # --- file ops (active tab) ---
    def on_new(self, *args):
        self._new_tab()
        if self.view is not None:
            self.view.grab_focus()

    def on_open(self, *args):
        dlg = Gtk.FileDialog(title="Open file")
        dlg.open(self, None, self._on_open_done)

    def _on_open_done(self, dlg, result):
        try:
            f = dlg.open_finish(result)
        except GLib.Error:
            return  # dismissed
        path = f.get_path()
        if path:
            self.open_path_in_tab(path)

    def on_save(self, *args):
        tab = self._active_tab()
        if tab is None:
            return
        if tab.file_path:
            self._write_to(tab.file_path, tab)
        else:
            self.on_save_as()

    def on_save_as(self, *args):
        tab = self._active_tab()
        if tab is None:
            return
        dlg = Gtk.FileDialog(title="Save file")
        if tab.file_path:
            dlg.set_initial_file(Gio.File.new_for_path(tab.file_path))
        dlg.save(self, None, self._on_save_done)

    def _on_save_done(self, dlg, result):
        try:
            f = dlg.save_finish(result)
        except GLib.Error:
            return
        path = f.get_path()
        tab = self._active_tab()
        if path and tab is not None:
            self._write_to(path, tab)

    def _write_to(self, path, tab):
        start, end = tab.buffer.get_bounds()
        text = tab.buffer.get_text(start, end, False)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as e:
            self._error(f"Could not save file:\n{e}")
            return
        tab.file_path = path
        tab.close_confirmed = False
        tab.buffer.set_modified(False)
        self._make_tab_permanent(tab)
        if HAS_GTKSOURCE:
            tab.buffer.set_language(self._detect_language(path, text))
        self._refresh_tab_title(tab)
        self._update_lang_label()
        self.update_title()
        self.update_status()

    # --- view options ---
    def on_toggle_line_numbers(self, btn):
        if self.view is not None and HAS_GTKSOURCE:
            self.view.set_show_line_numbers(btn.get_active())

    def on_toggle_wrap(self, btn):
        if self.view is not None:
            mode = Gtk.WrapMode.WORD if btn.get_active() else Gtk.WrapMode.NONE
            self.view.set_wrap_mode(mode)

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
        """Match code colors of all tabs to the libadwaita light/dark theme."""
        if not HAS_GTKSOURCE:
            return
        for i in range(self.tab_view.get_n_pages()):
            self._apply_style_to(self.tab_view.get_nth_page(i).get_child().buffer)

    def _on_theme_changed(self, *args):
        self._update_source_style()

    # --- status / title ---
    def on_mark_set(self, *args):
        self.update_status()

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
        self._update_ai_sensitivity()

    def update_title(self, *args):
        tab = self._active_tab()
        if tab is None:
            self.set_title("Text Editor")
            return
        self._refresh_tab_title(tab)
        name = os.path.basename(tab.file_path) if tab.file_path else "Untitled"
        if tab in self._temp_tabs:
            name = f"~ {name}"
        dirty = " •" if tab.buffer.get_modified() else ""
        self.set_title(f"{name}{dirty} - Text Editor")

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
                self.tab_view.close_page(page)

        _show_dialog(d, self, _on_response)

    def _on_close_request(self, *_args):
        """Check all tabs for unsaved changes before closing the window."""
        dirty_pages = []
        for i in range(self.tab_view.get_n_pages()):
            page = self.tab_view.get_nth_page(i)
            tab = page.get_child()
            if tab.buffer.get_modified() and not tab.close_confirmed:
                dirty_pages.append(page)
        if not dirty_pages:
            return False  # allow close
        self._close_queue = list(dirty_pages)
        self._confirm_next_dirty_page()
        return True  # veto close for now

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
            f'"{name}" has unsaved changes. Discard them?',
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
                    self._write_to(tab.file_path, tab)
                    if not tab.buffer.get_modified():
                        tab.close_confirmed = True
                        self.tab_view.close_page(page)
                self._confirm_next_dirty_page()
            else:
                self._close_queue.clear()

        _show_dialog(d, self, _on_response)


class MyApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="com.example.TextEditor")

    def do_activate(self):
        win = self.props.active_window or EditorWindow(self)
        win.present()


if __name__ == "__main__":
    app = MyApp()
    app.run(None)
