from gi.repository import Adw, GLib  # type: ignore

_HAS_ALERT_DIALOG = hasattr(Adw, "AlertDialog")
TONES = ["Professional", "Friendly", "Formal", "Casual", "Concise", "Confident"]


def _new_dialog(parent, heading, body):
    if _HAS_ALERT_DIALOG:
        return Adw.AlertDialog(heading=heading, body=body)
    return Adw.MessageDialog(transient_for=parent, heading=heading, body=body)


def _show_dialog(dlg, parent, on_response):
    """Present a dialog and call on_response(response_str) when done."""
    if _HAS_ALERT_DIALOG:
        def _on_choose(dlg_obj, result):
            try:
                resp = dlg_obj.choose_finish(result)
            except GLib.Error:
                resp = "cancel"
            except Exception:
                resp = "cancel"
            on_response(resp)
        dlg.choose(parent, None, _on_choose)
    else:
        def _legacy(_d, r):
            _d.disconnect(handler_id)
            on_response(r or "cancel")
        handler_id = dlg.connect("response", _legacy)
        dlg.present(parent)


def _set_accessible_label(widget, label):
    """Set a screen-reader label where supported by the installed GTK version."""
    update_property = getattr(widget, "update_property", None)
    if update_property is None:
        return
    try:
        from gi.repository import Gtk  # type: ignore
        update_property([Gtk.AccessibleProperty.LABEL], [label])
    except Exception:
        pass
