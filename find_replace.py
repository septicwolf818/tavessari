"""Find & Replace popover for the GTK4/GtkSourceView5 text editor."""

from gi.repository import Gtk, GLib, Adw  # type: ignore


class FindReplace:
    """A Find & Replace toolbar embedded in a Gtk.Popover.

    Created with ``FindReplace(editor_window)`` where *editor_window*
    is an instance of ``EditorWindow`` (main.py).  The constructor builds
    the popover UI and registers it as attributes on the window so that
    main.py can reference them directly.
    """

    def __init__(self, win):
        """Build the find/replace popover and attach to *win*.

        Parameters
        ----------
        win : EditorWindow
            The application window that owns this find-and-replace UI.
            ``find_popover``, ``find_entry``, and ``replace_entry`` will be
            stored as attributes on it.
        """
        self.win = win
        self.find_popover = Gtk.Popover()

        # Build the popover content ---------------------------------------
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=12, spacing=6)
        self.find_popover.set_child(box)

        # ---- Find row ---------------------------------------------------
        find_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        find_lbl = Gtk(label="Find:", width_chars=5, halign=Gtk.Align.START)
        self.find_entry = Gtk.Entry(margin_bottom=0, hexpand=True)
        self.find_entry.set_placeholder_text("Search...")
        self.find_entry.connect("changed", self._on_find_changed)
        find_box.append(find_lbl)
        find_box.append(self.find_entry)
        box.append(find_box)

        # ---- Replace row (initially hidden) -----------------------------
        rep_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        rep_lbl = Gtk(label="Replace:", width_chars=5, halign=Gtk.Align.START)
        self.replace_entry = Gtk.Entry(margin_bottom=0, hexpand=True)
        self.replace_entry.set_placeholder_text("Replace with")
        # "activate" fires when the user presses Enter inside the entry.
        self.replace_entry.connect("activate", self._replace_current)
        rep_box.append(rep_lbl)
        rep_box.append(self.replace_entry)
        box.append(rep_box)
        self._replace_row = rep_box          # keep handle for hide/show

        # ---- Options row ------------------------------------------------
        opts_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        self.case_checkbox = Gtk.CheckButton(icon_name="case-sensitive-symbolic")
        self.case_checkbox.set_tooltip_text("Case-sensitive search")
        opts_box.append(self.case_checkbox)

        self.ww_checkbox = Gtk.CheckButton(icon_name="whole-word-symbolic")
        self.ww_checkbox.set_tooltip_text("Whole word only")
        opts_box.append(self.ww_checkbox)

        # Direction dropdown (Gtk.ComboBoxText — simple string list)
        dir_model = Gtk.StringList.new(["Next", "Previous"])
        self.dir_combo = Gtk.ComboBox.new_with_model(dir_model)
        self.dir_combo.set_active(0)       # default: Next
        self.dir_combo.set_tooltip_text("Search direction")
        opts_box.append(self.dir_combo)

        box.append(opts_box)

        # ---- Buttons row ------------------------------------------------
        btns_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        self.find_next_btn = Gtk.Button(label="Find Next", hexpand=False)
        self.find_next_btn.set_sensitive(False)
        self.find_next_btn.add_css_class("suggested-action")
        self.find_next_btn.connect("clicked", self._find_next)
        btns_box.append(self.find_next_btn)

        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep.set_margin_start(4)
        sep.set_margin_end(4)
        btns_box.append(sep)

        self.replace_btn = Gtk.Button(label="Replace", hexpand=False)
        self.replace_btn.set_sensitive(False)
        self.replace_btn.add_css_class("accent")
        self.replace_btn.connect("clicked", self._replace_current)
        btns_box.append(self.replace_btn)

        self.replace_all_btn = Gtk.Button(label="Replace All", hexpand=False)
        self.replace_all_btn.set_sensitive(False)
        self.replace_all_btn.add_css_class("accent")
        self.replace_all_btn.connect("clicked", self._replace_all)
        btns_box.append(self.replace_all_btn)

        # Stretching spacer
        btns_box.append(Gtk.Box(hexpand=True))

        # Close button
        close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close_btn.set_tooltip_text("Close (Esc)")
        close_btn.set_size_request(28, 28)
        close_btn.connect("clicked", self._close_popover)
        btns_box.append(close_btn)

        box.append(btns_box)

        # ---- Popover positioning & show handler -------------------------
        self.find_popover.set_parent(self.win)
        # Position the popover near the header bar find button area.
        self.find_popover.set_has_arrow(False)
        self.find_popover.add_css_class("inline")

        # When the popover becomes visible, auto-find the previous search term
        # (so reopening with Ctrl+F re-highlights the last query).
        self.find_popover.connect("show", self._on_popover_show)

        # Expose attributes on win so main.py can reach them directly.
        self.win.find_popover = self.find_popover
        self.win.find_entry = self.find_entry
        self.win.replace_entry = self.replace_entry

        # Store self-reference on the window for convenience from outside.
        self.win.find_replace = self

    # ------------------------------------------------------------------
    # Public helpers (used by Gio actions in main.py)
    # ------------------------------------------------------------------

    def show(self):
        """Show the find popover (convenience wrapper)."""
        buf = self.win.buffer
        if buf is None:
            # No tab open — brief visual feedback that there's nothing to
            # search.  Don't crash; just return silently so main.py can
            # still wire up a disabled find button without error.
            return
        self.find_popover.pop_up()

    def hide(self):
        """Hide the find popover."""
        if self.find_popover.get_visible():
            self.find_popover.popdown()

    # ------------------------------------------------------------------
    # Popover show / close helpers
    # ------------------------------------------------------------------

    def _close_popover(self, *_):
        """Close the popover and release focus."""
        self.win.find_entry.set_text("")
        self.win.find_entry.set_placeholder_text("Search...")
        self.win.replace_entry.set_text("")
        self._hide_replace_row()
        self.find_popover.popdown()

    def _on_popover_show(self, *_):
        """When shown, if there is previous search text, find it."""
        text = self.win.find_entry.get_text()
        if text:
            GLib.idle_add(self._find_next)

    # ------------------------------------------------------------------
    # Find logic
    # ------------------------------------------------------------------

    def _on_find_changed(self, entry):
        """Handle changes to the Find entry.

        Enables / disables buttons and toggles visibility of the Replace row.
        """
        text = entry.get_text()
        has_text = bool(text)

        # Enable/disable Find Next button
        self.find_next_btn.set_sensitive(has_text)

        # Show/hide replace row
        if has_text:
            self._show_replace_row()
        else:
            self._hide_replace_row()
            self.replace_entry.set_text("")

        # Enable/disable Replace buttons (need both Find and Replace text)
        rep_text = self.win.replace_entry.get_text()
        both = has_text and bool(rep_text)
        self.replace_btn.set_sensitive(both)
        self.replace_all_btn.set_sensitive(both)

    def _show_replace_row(self):
        """Make the replace row visible and map it to the popover."""
        if not self._replace_row.get_visible():
            # Insert between the find row (child 0) and options row (child 2)
            box = self.find_popover.get_child()
            box.set_child_nth(self._replace_row, 1)
            self._replace_row.set_visible(True)

    def _hide_replace_row(self):
        """Make the replace row invisible."""
        if self._replace_row.get_visible():
            self._replace_row.set_visible(False)

    # ------------------------------------------------------------------
    # Search flags helper
    # ------------------------------------------------------------------

    def _build_flags(self):
        """Return a Gtk.TextSearchFlags value from checkbox state."""
        flags = 0
        # CASE_INSENSITIVE when case-checkbox is NOT active (i.e. insensitive search).
        if not self.case_checkbox.get_active():
            flags |= Gtk.TextSearchFlags.CASE_INSENSITIVE
        if self.ww_checkbox.get_active():
            flags |= Gtk.TextSearchFlags.WHOLE_WORD
        return flags

    # ------------------------------------------------------------------
    # _find_next — core find operation
    # ------------------------------------------------------------------

    def _find_next(self, *_):
        """Search forward / backward for the current Find text and select it.

        Also updates the match count in the status bar.
        """
        buf = self.win.buffer
        if buf is None:
            return  # no tab open

        text = self.win.find_entry.get_text()
        if not text:
            return

        search_flags = self._build_flags()

        # Determine iteration direction from the combo box.
        active_dir = self.dir_combo.get_active()
        next_iter = True if active_dir == 0 else False  # Next / Previous

        it = buf.get_iter_at_mark(buf.get_insert())

        found = False
        match_iter = None

        if next_iter:
            result = it.forward_search(text, search_flags, len(text) + 1)
            if result:
                found, match_iter = result
        else:
            # backward_search returns (True/False, iter); check for truthy first element.
            result = it.backward_search(text, search_flags)
            if result and result[0]:
                found = True
                match_iter = result[1]

        if found and match_iter is not None:
            start_iter = match_iter.copy()
            end_iter = match_iter.copy()
            end_iter.forward_chars(len(text))

            # Select the match by moving both marks.
            buf.move_mark(buf.get_insert(), start_iter)
            buf.move_mark(buf.get_selection_bound(), end_iter)
            buf.place_cursor(start_iter)

            # Scroll the view so the selection is visible.
            self._scroll_to_selection(buf)

            # Update status bar with match count.
            match_count = self._count_matches(buf, text, search_flags)
            self._update_status_match(match_count)
        else:
            # Flash the find entry border red briefly.
            self._flash_red()

            # Show toast via Adw.Toast if available; fall back to a simple
            # label message on the window status bar otherwise.
            toast = Adw.Toast(title="Not found")
            toast.set_timeout(2)
            GLib.idle_add(self.win.toast_overlay.add_toast, toast)

    # ------------------------------------------------------------------
    # _count_matches — iterate through buffer and count occurrences
    # ------------------------------------------------------------------

    def _count_matches(self, buf, text, flags):
        """Return the total number of matches for *text* in *buf*.

        Iterates from start to end using successive ``forward_search`` calls.
        """
        it = buf.get_start_iter()
        count = 0
        max_iterations = buf.get_char_count() + 1  # safety cap

        while True:
            if not text:
                break
            result = it.forward_search(text, flags)
            if not result or not result[0]:
                break
            count += 1
            # Move past this match to find the next.
            it = result[1].copy()
            it.forward_chars(len(text))
            max_iterations -= 1
            if max_iterations <= 0:
                break

        return count

    # ------------------------------------------------------------------
    # Scroll helpers
    # ------------------------------------------------------------------

    def _scroll_to_selection(self, buf):
        """Scroll the active view so that the selection rectangle is visible."""
        # Use scroll_to_mark which works on both Gtk.TextBuffer and GtkSource.Buffer.
        # Avoid get_cell_area which only exists on Gtk.TextView, not GtkTextBuffer.
        mark = buf.get_insert()
        if self.win.view is not None:
            start_iter = buf.get_mark("selection_bound").get_iter() if buf.get_has_selection() else buf.get_iter_at_mark(mark)
            buf.scroll_to_mark(mark, 0.25)

    # ------------------------------------------------------------------
    # _replace_current — replace the current match
    # ------------------------------------------------------------------

    def _replace_current(self, *_):
        """Replace the currently selected text with the Replace entry value."""
        buf = self.win.buffer
        if buf is None:
            return

        find_text = self.win.find_entry.get_text()
        rep_text = self.win.replace_entry.get_text()
        if not find_text or not rep_text:
            return

        # Check that there is an active selection matching the find text.
        start_mark = buf.get_insert()
        end_mark = buf.get_selection_bound()
        selected_text = buf.get_text(start_mark.get_iter(), end_mark.get_iter(), False)

        if selected_text == find_text:
            # Delete the selection and insert replacement.
            iter_before = start_mark.get_iter().copy()
            buf.delete(start_mark.get_iter(), end_mark.get_iter())
            buf.insert(iter_before, rep_text)

            # Move cursor just after inserted text.
            new_end = iter_before.copy()
            new_end.forward_chars(len(rep_text))
            buf.move_mark(buf.get_insert(), new_end)
            buf.move_mark(buf.get_selection_bound(), new_end)

            # Immediately find the next occurrence (if any).
            GLib.idle_add(self._find_next_after_replace, buf, find_text)
        else:
            # Selection doesn't match — don't call _find_next here to avoid
            # recursion; just flash red and return silently.
            self._flash_red()

    # ------------------------------------------------------------------
    # _replace_all — replace every occurrence in the buffer
    # ------------------------------------------------------------------

    def _replace_all(self, *_):
        """Replace all occurrences of Find text with Replace text."""
        buf = self.win.buffer
        if buf is None:
            return

        find_text = self.win.find_entry.get_text()
        rep_text = self.win.replace_entry.get_text()
        if not find_text or not rep_text:
            return

        search_flags = self._build_flags()

        # Get full text and find all matches using character offsets
        full_text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        search_len = len(find_text)

        if Gtk.TextSearchFlags.CASE_INSENSITIVE in search_flags:
            search_lower = find_text.lower()
            full_lower = full_text.lower()
        else:
            search_lower = find_text
            full_lower = full_text

        matches = []  # list of (start_offset, end_offset) character indices
        pos = 0
        max_chars = buf.get_char_count() + 1
        while pos <= len(full_text) - search_len and max_chars > 0:
            idx = full_lower.find(search_lower, pos)
            if idx == -1:
                break
            actual_start = pos + (idx - pos)
            matches.append((actual_start, actual_start + search_len))
            pos = actual_start + 1
            max_chars -= 1

        if not matches:
            # Nothing to replace
            self._flash_red()
            toast = Adw.Toast(title="No matches found")
            toast.set_timeout(2)
            GLib.idle_add(self.win.toast_overlay.add_toast, toast)
            return

        buf.begin_revertable_change()

        for start_offset, end_offset in reversed(matches):
            start_iter = buf.get_iter_at_offset(start_offset)
            end_iter = buf.get_iter_at_offset(end_offset)
            buf.delete(start_iter, end_iter)
            insert_iter = buf.get_iter_at_offset(start_offset)
            buf.insert(insert_iter, rep_text)

        buf.end_revertable_change()
        buf.set_modified(True)

        # Update cursor to just after first replacement
        if matches:
            new_end = buf.get_iter_at_offset(matches[0][0])
            new_end.forward_chars(len(rep_text))
            buf.place_cursor(new_end)

        GLib.idle_add(self._update_status_match, len(matches))
        toast = Adw.Toast(title=f"Replaced {len(matches)} occurrence{'s' if len(matches) != 1 else ''}")
        toast.set_timeout(3)
        GLib.idle_add(self.win.toast_overlay.add_toast, toast)

    # ------------------------------------------------------------------
    # Status / visual helpers
    # ------------------------------------------------------------------

    def _update_status_match(self, count):
        """Update the editor's stats_label with match information."""
        if count:
            text = f"{count} match{'es' if count != 1 else ''}"
        else:
            text = "No matches"
        self.win.stats_label.set_text(text)

    def _flash_red(self):
        """Flash the find entry border red for a brief moment."""
        self.find_entry.add_css_class("error")
        GLib.timeout_add_seconds(1, self._unflash_error)

    def _find_next_after_replace(self, buf, find_text):
        """After a successful replacement, find the next occurrence (no recursion)."""
        if not find_text:
            return
        search_flags = self._build_flags()
        it = buf.get_iter_at_mark(buf.get_insert())

        found = False
        match_iter = None

        # Forward search from cursor position
        result = it.forward_search(find_text, search_flags, len(find_text) + 1)
        if result:
            found, match_iter = result

        if not found:
            # Wrap around and search from the beginning
            start_it = buf.get_start_iter()
            result = start_it.forward_search(find_text, search_flags,
                                             buf.get_end_iter().get_offset() - 1)
            if result:
                found, match_iter = result

        if found and match_iter is not None:
            start_iter = match_iter.copy()
            end_iter = match_iter.copy()
            end_iter.forward_chars(len(find_text))

            buf.move_mark(buf.get_insert(), start_iter)
            buf.move_mark(buf.get_selection_bound(), end_iter)
            buf.place_cursor(start_iter)

            # Scroll the view so the selection is visible.
            self._scroll_to_selection(buf)

            match_count = self._count_matches(buf, find_text, search_flags)
            GLib.idle_add(self._update_status_match, match_count)

    def _unflash_error(self):
        """Remove the error CSS class (always returns False to remove timeout)."""
        if "error" in self.find_entry.get_css_classes():
            self.find_entry.remove_css_class("error")
        return False  # one-shot callback: do not repeat.
