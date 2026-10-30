"""Find & Replace popover for the GTK4 text editor."""

from gi.repository import Gtk, GLib, Adw, Gdk  # type: ignore


class FindReplace:
    """Simple Find & Replace toolbar in a Gtk.Popover."""

    def __init__(self, win):
        self.win = win

        popover = Gtk.Popover()
        popover.set_has_arrow(False)
        popover.add_css_class("toolbar")

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        vbox.set_margin_start(10)
        vbox.set_margin_end(10)
        vbox.set_margin_top(8)
        vbox.set_margin_bottom(8)
        popover.set_child(vbox)

        # --- Find row ---
        find_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.find_entry = Gtk.Entry(hexpand=True)
        self.find_entry.set_placeholder_text("Find...")
        self.find_entry.set_size_request(250, -1)
        self.find_entry.connect("activate", self._find_next)
        find_row.append(self.find_entry)
        vbox.append(find_row)

        # --- Replace row (always in layout, just hidden) ---
        self.replace_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.replace_entry = Gtk.Entry(hexpand=True)
        self.replace_entry.set_placeholder_text("Replace with...")
        self.replace_entry.set_size_request(250, -1)
        self.replace_entry.connect("activate", self._replace_current)
        self.replace_row.append(self.replace_entry)
        self.replace_row.set_visible(False)
        vbox.append(self.replace_row)

        # --- Options row ---
        opts = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        self.case_checkbox = Gtk.CheckButton(label="Match case")
        opts.append(self.case_checkbox)

        self.ww_checkbox = Gtk.CheckButton(label="Whole word")
        opts.append(self.ww_checkbox)

        self.dir_combo = Gtk.ComboBoxText.new()
        self.dir_combo.append_text("Forward")
        self.dir_combo.append_text("Backward")
        self.dir_combo.set_active(0)
        opts.append(self.dir_combo)

        vbox.append(opts)

        self.match_count_label = Gtk.Label(label="")
        self.match_count_label.set_xalign(0.0)
        self.match_count_label.add_css_class("dim-label")
        vbox.append(self.match_count_label)

        # --- Buttons row ---
        btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        self.find_next_btn = Gtk.Button(label="Find Next")
        self.find_next_btn.set_sensitive(False)
        self.find_next_btn.add_css_class("suggested-action")
        self.find_next_btn.connect("clicked", self._find_next)
        btns.append(self.find_next_btn)

        self.replace_btn = Gtk.Button(label="Replace")
        self.replace_btn.set_sensitive(False)
        self.replace_btn.connect("clicked", self._replace_current)
        btns.append(self.replace_btn)

        self.replace_all_btn = Gtk.Button(label="Replace All")
        self.replace_all_btn.set_sensitive(False)
        self.replace_all_btn.connect("clicked", self._replace_all)
        btns.append(self.replace_all_btn)

        btns.append(Gtk.Box(hexpand=True))

        close_btn = Gtk.Button(label="Close")
        close_btn.connect("clicked", self._close_popover)
        btns.append(close_btn)

        vbox.append(btns)

        # --- Signals ---
        self.find_entry.connect("changed", self._on_find_changed)
        self.replace_entry.connect("changed", self._on_find_changed)
        self.case_checkbox.connect("toggled", self._on_search_option_changed)
        self.ww_checkbox.connect("toggled", self._on_search_option_changed)
        popover.connect("closed", self._on_popover_closed)
        popover.connect("show", lambda *_: setattr(self, '_is_open', True))

        # Handle Ctrl+F inside the popover to toggle it closed
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        popover.add_controller(key_ctrl)

        self._is_open = False

        # Expose on win
        self.find_popover = popover
        self.win.find_popover = popover
        self.win.find_entry = self.find_entry
        self.win.replace_entry = self.replace_entry
        self.win.find_replace = self

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def open(self, select_all=False):
        """Open the popover, optionally pre-filling with the buffer selection."""
        if self.win.buffer is None:
            return

        # Pre-fill with selection
        buf = self.win.buffer
        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
            sel = buf.get_text(start, end, False)
            if sel.strip():
                self.find_entry.set_text(sel)
                if select_all:
                    self.find_entry.select_region(0, -1)

        self.find_popover.popup()
        self.find_entry.grab_focus()

    def close(self):
        self._is_open = False
        self.find_popover.popdown()

    @property
    def is_open(self):
        return self._is_open

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _close_popover(self, *_):
        self.find_popover.popdown()

    def _on_key_pressed(self, _controller, keyval, _keycode, state):
        if keyval == Gdk.KEY_f and state & Gdk.ModifierType.CONTROL_MASK:
            self.close()
            return True
        return False

    def _on_popover_closed(self, *_):
        self._is_open = False
        if self.win.view is not None:
            # Use idle_add so focus moves after GTK finishes cleanup
            GLib.idle_add(self._grab_editor_focus)

    def _grab_editor_focus(self):
        if self.win.view is not None:
            self.win.view.grab_focus()
        return False  # one-shot

    def _on_find_changed(self, entry):
        text = self.find_entry.get_text()
        has_text = bool(text)
        if entry is self.find_entry:
            self.match_count_label.set_text("")

        self.find_next_btn.set_sensitive(has_text)

        # Show replace row only when there is find text
        self.replace_row.set_visible(has_text)

        # An empty replacement is valid: it deletes matching text.
        self.replace_btn.set_sensitive(has_text)
        self.replace_all_btn.set_sensitive(has_text)

    def _on_search_option_changed(self, *_):
        if self.find_entry.get_text():
            self._update_match_count()

    # ------------------------------------------------------------------
    # Search helpers
    # ------------------------------------------------------------------

    def _build_flags(self):
        flags = 0
        if not self.case_checkbox.get_active():
            flags |= Gtk.TextSearchFlags.CASE_INSENSITIVE
        return flags

    def _forward_search(self, cursor, text, flags):
        whole_word = self.ww_checkbox.get_active()
        search_from = cursor.copy()
        while True:
            result = search_from.forward_search(text, flags)
            if result is None:
                return None
            start, end = result
            if not whole_word or (start.starts_word() and end.ends_word()):
                return result
            search_from = start.copy()
            if not search_from.forward_char():
                return None

    def _backward_search(self, cursor, text, flags):
        whole_word = self.ww_checkbox.get_active()
        search_from = cursor.copy()
        while True:
            result = search_from.backward_search(text, flags)
            if result is None:
                return None
            start, end = result
            if not whole_word or (start.starts_word() and end.ends_word()):
                return result
            search_from = start.copy()
            if not search_from.backward_char():
                return None

    def _find_next(self, *_):
        """Find the next match from cursor, wrapping around once if needed."""
        buf = self.win.buffer
        if buf is None:
            return
        text = self.find_entry.get_text()
        if not text:
            return

        flags = self._build_flags()
        forward = self.dir_combo.get_active() == 0

        # Adjust cursor to the correct edge when a match is already selected
        if buf.get_has_selection():
            sel_start, sel_end = buf.get_selection_bounds()
            if forward:
                buf.place_cursor(sel_end)
            else:
                buf.place_cursor(sel_start)

        cursor = buf.get_iter_at_mark(buf.get_insert())

        # 1) Search from cursor in the chosen direction
        result = (self._forward_search(cursor, text, flags) if forward
                  else self._backward_search(cursor, text, flags))

        if result is not None:
            self._highlight(buf, result[0], result[1], forward)
            self._update_match_count()
            return

        # 2) Wrap around: search from the opposite end
        if forward:
            result = self._forward_search(buf.get_start_iter(), text, flags)
            wrap_msg = "Wrapped to beginning"
        else:
            result = self._backward_search(buf.get_end_iter(), text, flags)
            wrap_msg = "Wrapped to end"

        if result is not None:
            self._highlight(buf, result[0], result[1], forward)
            self._update_match_count()
            toast = Adw.Toast(title=wrap_msg)
            toast.set_timeout(1)
            self.win.toast_overlay.add_toast(toast)
        else:
            self._update_match_count()
            self._flash_red()
            toast = Adw.Toast(title="Not found")
            toast.set_timeout(2)
            self.win.toast_overlay.add_toast(toast)

    def _highlight(self, buf, start, end, forward=True):
        """Select a range in the buffer and scroll to it."""
        if forward:
            buf.select_range(end, start)
        else:
            buf.select_range(start, end)
        self.win.view.scroll_to_iter(start, 0.25, True, 0.0, 0.0)

    def _replace_current(self, *_):
        buf = self.win.buffer
        if buf is None:
            return
        find_text = self.find_entry.get_text()
        rep_text = self.replace_entry.get_text()
        if not find_text:
            return

        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
            match = self._forward_search(start, find_text, self._build_flags())
            if (match is not None
                    and match[0].get_offset() == start.get_offset()
                    and match[1].get_offset() == end.get_offset()):
                buf.begin_user_action()
                try:
                    buf.delete(start, end)
                    buf.insert(start, rep_text)
                finally:
                    buf.end_user_action()
                GLib.idle_add(self._find_next)
                return
        self._flash_red()
        toast = Adw.Toast(title="Select a matching search result to replace")
        toast.set_timeout(2)
        self.win.toast_overlay.add_toast(toast)

    def _replace_all(self, *_):
        buf = self.win.buffer
        if buf is None:
            return
        find_text = self.find_entry.get_text()
        rep_text = self.replace_entry.get_text()
        if not find_text:
            return

        flags = self._build_flags()
        matches = self._find_matches(buf, find_text, flags)

        if not matches:
            self._flash_red()
            toast = Adw.Toast(title="No matches found")
            toast.set_timeout(2)
            self.win.toast_overlay.add_toast(toast)
            return

        buf.begin_user_action()
        try:
            for start_off, end_off in reversed(matches):
                s = buf.get_iter_at_offset(start_off)
                e = buf.get_iter_at_offset(end_off)
                buf.delete(s, e)
                buf.insert(buf.get_iter_at_offset(start_off), rep_text)
        finally:
            buf.end_user_action()

        self._update_match_count()
        toast = Adw.Toast(title=f"Replaced {len(matches)} occurrence{'s' if len(matches) != 1 else ''}")
        toast.set_timeout(3)
        self.win.toast_overlay.add_toast(toast)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_matches(self, buf, text, flags):
        matches = []
        cursor = buf.get_start_iter()
        while True:
            result = self._forward_search(cursor, text, flags)
            if result is None:
                return matches
            start, end = result
            matches.append((start.get_offset(), end.get_offset()))
            cursor = end

    def _update_match_count(self):
        buf = self.win.buffer
        text = self.find_entry.get_text()
        if buf is None or not text:
            self.match_count_label.set_text("")
            return
        count = len(self._find_matches(buf, text, self._build_flags()))
        self.match_count_label.set_text(
            f"{count} match{'es' if count != 1 else ''}" if count else "No matches")

    def _flash_red(self):
        self.find_entry.add_css_class("error")
        GLib.timeout_add_seconds(1, self._unflash_error)

    def _unflash_error(self):
        self.find_entry.remove_css_class("error")
        return False
