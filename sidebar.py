import os

from gi.repository import Gtk, Adw, Gio, GLib, Pango  # type: ignore

from ollama import OllamaClient
from ui_utils import _new_dialog, _show_dialog


class FileBrowser(Gtk.Box):
    """Sidebar file browser with folder tree view."""

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.folder_root = None
        self._last_activate_path = None

        # --- header row ---
        header_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header_bar.set_margin_start(8)
        header_bar.set_margin_end(8)
        header_bar.set_margin_top(8)
        header_bar.set_margin_bottom(4)
        self.append(header_bar)

        self.folder_label = Gtk.Label(label="No folder")
        self.folder_label.set_hexpand(True)
        self.folder_label.set_xalign(0.0)
        self.folder_label.set_ellipsize(Pango.EllipsizeMode.END)
        header_bar.append(self.folder_label)

        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Refresh file tree")
        refresh_btn.connect("clicked", lambda *_: self.rebuild_file_tree())
        header_bar.append(refresh_btn)

        close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close_btn.set_tooltip_text("Close folder")
        close_btn.connect("clicked", lambda *_: self.close_folder())
        header_bar.append(close_btn)

        # --- scrolled file tree ---
        side_scrolled = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        self.append(side_scrolled)

        self.file_list = Gtk.ListView()
        self.file_list.set_single_click_activate(True)
        self._tree_factory = Gtk.SignalListItemFactory()
        self._tree_factory.connect("setup", self._on_tree_setup)
        self._tree_factory.connect("bind", self._on_tree_bind)
        self.file_list.set_factory(self._tree_factory)
        side_scrolled.set_child(self.file_list)

        self.file_list.connect("activate", self._on_list_activate)
        self._rebuild_file_tree()

    # --- public API -----------------------------------------------------------

    def open_folder(self):
        """Show folder picker dialog; call on result."""
        dlg = Gtk.FileDialog(title="Open folder")
        dlg.select_folder(self.win, None, self._on_folder_done)

    def _on_folder_done(self, dlg, result):
        try:
            gfile = dlg.select_folder_finish(result)
        except GLib.Error:
            return  # dismissed
        self.folder_root = gfile
        self.folder_label.set_text(gfile.get_basename() or gfile.get_path())
        self._rebuild_file_tree()
        self.win.side_toggle.set_visible(True)
        self.win.side_toggle.set_active(True)
        self.win._show_sidebar()

    def close_folder(self):
        """Clear root folder and inform the window how to restore layout."""
        self.folder_root = None
        self.folder_label.set_text("No folder")
        self._rebuild_file_tree()
        self.win.side_toggle.set_visible(False)
        self.win.side_toggle.set_active(False)
        self.win._show_editor_only()

    def rebuild_file_tree(self):
        root_store = Gio.ListStore.new(Gio.File)
        if self.folder_root is not None:
            for child in self._list_dir_children(self.folder_root):
                root_store.append(child)
        self.win.tree_model = Gtk.TreeListModel.new(
            root_store, False, False, self._create_dir_model)
        sel = Gtk.SingleSelection.new(self.win.tree_model)
        self.file_list.set_model(sel)

    def on_side_toggle(self, btn):
        if btn.get_active():
            self.win._show_sidebar()
        else:
            self.win._show_editor_only()

    # --- folder sidebar operations ---

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
        self.win.tree_model = Gtk.TreeListModel.new(
            root_store, False, False, self._create_dir_model)
        sel = Gtk.SingleSelection.new(self.win.tree_model)
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

    def _sidebar_find_path_at(self):
        """Get the Gio.File path of the currently selected item."""
        sel = self.file_list.get_model()
        if sel is None:
            return None
        pos = sel.get_selected()
        if pos < 0:
            return None
        root_model = sel.get_model()
        if root_model is None:
            return None
        row = root_model.get_item(pos)
        gfile = row.get_item() if hasattr(row, 'get_item') else row
        return gfile.get_path() if hasattr(gfile, 'get_path') else None

    def _on_list_activate(self, _list, _position):
        """Handle click: toggle folder, single-click opens temp file, double-click promotes."""
        path = self._sidebar_find_path_at()
        if path is None:
            return
        if os.path.isdir(path):
            sel = self.file_list.get_model()
            pos = sel.get_selected()
            if pos < 0:
                return
            root_model = sel.get_model()
            if root_model is None:
                return
            row = root_model.get_item(pos)
            if hasattr(row, 'is_expandable') and row.is_expandable():
                row.set_expanded(not row.get_expanded())
            return
        norm = os.path.realpath(path)
        last = getattr(self, '_last_activate_path', None)
        if last and os.path.realpath(last) == norm:
            self._last_activate_path = None
            for i in range(self.win.tab_view.get_n_pages()):
                page = self.win.tab_view.get_nth_page(i)
                tab = page.get_child()
                if tab in self.win._temp_tabs and tab.file_path and os.path.realpath(tab.file_path) == norm:
                    self.win._make_tab_permanent(tab)
                    self.win.tab_view.set_selected_page(page)
                    return
        self._last_activate_path = path
        self.close_all_temp_tabs()
        self._open_temp_tab(path)

    def _on_file_doubleclick(self, path):
        """Handle double-click: open file permanently."""
        if not path or os.path.isdir(path):
            return
        self.close_all_temp_tabs()
        self.win.open_path_in_tab(path)

    def _open_temp_tab(self, path):
        """Open a file as a temporary tab (sidebar single-click)."""
        norm = os.path.realpath(path)
        # already open as permanent?
        for i in range(self.win.tab_view.get_n_pages()):
            page = self.win.tab_view.get_nth_page(i)
            tab = page.get_child()
            if tab.file_path and os.path.realpath(tab.file_path) == norm:
                if tab not in self.win._temp_tabs:
                    self.win.tab_view.set_selected_page(page)
                    return
        # already open as temp? Remember path for next click (promote on 2nd click)
        for i in range(self.win.tab_view.get_n_pages()):
            page = self.win.tab_view.get_nth_page(i)
            tab = page.get_child()
            if tab in self.win._temp_tabs and tab.file_path and os.path.realpath(tab.file_path) == norm:
                self.win.tab_view.set_selected_page(page)
                return
        # close previous temp tabs
        self.close_all_temp_tabs()
        # open new - check if text file, then read
        try:
            with open(path, "rb") as _f:
                chunk = _f.read(8192)
                _f.seek(0)
        except OSError as e:
            self.win._error(f"Could not open file:\n{e}")
            return

        # Check if binary (contains null bytes)
        if b"\x00" in chunk:
            dlg = _new_dialog(self.win, "Binary File",
                              "This file is a binary and cannot be opened as text.")
            dlg.add_response("ok", "OK")
            _show_dialog(dlg, self.win, lambda r: None)
            return

        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError as e:
            self.win._error(f"Could not open file:\n{e}")
            return

        active = self.win._active_tab()
        if (active is not None and active not in self.win._temp_tabs
                and active.file_path is None
                and not active.buffer.get_modified()
                and active.buffer.get_char_count() == 0):
            tab = active
            self.win._load_into_tab(tab, path, text)
        else:
            tab = self.win._new_tab(path, text)
        self.win._temp_tabs.add(tab)
        self.win.update_title()
        page = self.win._find_page(tab)
        if page is not None:
            page.set_title(f"~ {os.path.basename(path)}")
            page.set_needs_attention(True)
        page = self.win._find_page(tab)
        if page is not None:
            self.win.tab_view.set_selected_page(page)

    def close_all_temp_tabs(self):
        """Close all sidebar-temp-opened tabs (no unsaved prompt)."""
        to_close = []
        for tab in list(self.win._temp_tabs):
            if not tab.buffer.get_modified():
                page = self.win._find_page(tab)
                if page is not None:
                    to_close.append(page)
        for page in to_close:
            tab = page.get_child()
            self.win._temp_tabs.discard(tab)
            self.win.tab_view.close_page(page)
