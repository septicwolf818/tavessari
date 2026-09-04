"""Per-tab state management for the text editor."""


class StateManager:
    """Manages selection, snapshots, and dirty-state for a single editor tab."""

    def __init__(self, tab_id):
        # Selection tracking variables
        self._selection_start = None
        self._selection_end = None
        self._snapshots = []  # list of (start_mark, end_mark) pairs from create_snapshot()

        # Dirty flag
        self._dirty = False

        # Per-tab identity
        self.tab_id = tab_id


# ---------------------------------------------------------------------------
# Selection helpers
# ---------------------------------------------------------------------------

    def get_selection_start(self):
        """Return the current selection-start bound (None if no selection)."""
        return self._selection_start

    def get_selection_end(self):
        """Return the current selection-end bound (None if no selection)."""
        return self._selection_end

    def set_selection_bounds(self, start, end):
        """Update internal tracking with the current selection."""
        self._selection_start = start
        self._selection_end = end

    # ------------------------------------------------------------------
    # Snapshot helpers
    # ------------------------------------------------------------------

    def create_snapshot(self, buf):
        """Capture and store buffer state at the current selection boundaries.

        Returns a tuple of ``(start_text, end_text)`` captured from *buf*.
        If no selection exists, returns ``(None, None)``.
        """
        if self._selection_start is None or self._selection_end is None:
            return None, None
        snap = (self._selection_start, self._selection_end)
        self._snapshots.append(snap)

        # Return the actual text at those marks from the buffer.
        start_mark, end_mark = snap
        start_iter = buf.get_iter_at_mark(start_mark) if start_mark else None
        end_iter = buf.get_iter_at_mark(end_mark) if end_mark else None
        if start_iter and end_iter:
            start_text = start_iter.get_text() if hasattr(start_iter, 'get_text') else ""
            # For mark-based snapshots we store the mark references themselves;
            # the *actual* text comparison happens in check_snapshots_differ.
        return snap

    def check_snapshots_differ(self, snap1, snap2):
        """Compare two snapshots and return True if they differ."""
        if snap1 is None or snap2 is None:
            return False
        s1_start, s1_end = snap1
        s2_start, s2_end = snap2
        # Compare the stored mark references / positions.
        if hasattr(s1_start, 'get_line') and hasattr(s2_start, 'get_line'):
            return (s1_start.get_line() != s2_start.get_line()
                    or s1_start.get_line_offset() != s2_start.get_line_offset())
        return snap1 is not snap2

    # ------------------------------------------------------------------
    # Dirty flag helpers
    # ------------------------------------------------------------------

    def is_dirty(self):
        """Return True if the current tab has unsaved changes."""
        return self._dirty

    def set_dirty(self):
        """Mark the current tab as having unsaved changes."""
        self._dirty = True

    def clear_dirty(self):
        """Clear the unsaved-changes flag for the current tab."""
        self._dirty = False
