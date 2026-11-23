import os
import sys
import json
import time
from datetime import datetime
import wx
import addonHandler
import globalPluginHandler
import scriptHandler
import ui
import tones
import gui
import api
import globalVars

from .object_locator import FocusMode, ObjectLocator, generate_fingerprint

# NVDA çeviri altyapısını başlat
addonHandler.initTranslation()

ADDON_DIR = os.path.dirname(__file__)
LIB_DIR = os.path.join(ADDON_DIR, "lib")
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

try:
    import markdown
except ImportError:
    markdown = None


class NoteDatabase:
    """JSON tabanlı ve RAM önbellekli veri yöneticisi."""
    def __init__(self, db_path):
        self.db_path = db_path
        self.cache = {}
        self._load_cache()

    def _load_cache(self):
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    self.cache = json.load(f)
            except Exception:
                self.cache = {}

    def _save_to_disk(self):
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=2)

    def get_note(self, fingerprint):
        return self.cache.get(fingerprint)

    def save_note(self, fingerprint, app_name, window_title, control_name, content):
        if not content.strip():
            self.delete_note(fingerprint)
            return

        self.cache[fingerprint] = {
            "app_name": app_name,
            "window_title": window_title,
            "control_name": control_name,
            "content": content,
            "updated_at": datetime.now().isoformat()
        }
        self._save_to_disk()

    def delete_note(self, fingerprint):
        if fingerprint in self.cache:
            del self.cache[fingerprint]
            self._save_to_disk()

    def get_notes_for_app(self, app_name):
        return [
            (fp, data) for fp, data in self.cache.items()
            if data.get("app_name") == app_name
        ]


class NoteEditDialog(wx.Dialog):
    """Markdown not ekleme ve düzenleme iletişim kutusu."""
    def __init__(self, parent, control_name, current_content, on_save_callback, on_delete_callback):
        # Translators: Default name when a control has no accessible name
        display_ctrl = control_name or _("Unnamed Control")
        # Translators: Title of the note editing dialog. {control} is replaced with the control's name.
        title = _("Edit Sticky Note: {control}").format(control=display_ctrl)
        super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.on_save_callback = on_save_callback
        self.on_delete_callback = on_delete_callback

        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Translators: Label for the multiline Markdown note input field
        lbl = wx.StaticText(self, label=_("Note Content (Markdown supported):"))
        main_sizer.Add(lbl, 0, wx.ALL, 8)

        self.text_ctrl = wx.TextCtrl(
            self,
            value=current_content,
            style=wx.TE_MULTILINE,
            size=(450, 220)
        )
        main_sizer.Add(self.text_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        btn_sizer = wx.StdDialogButtonSizer()
        # Translators: Label for the Save button
        save_btn = wx.Button(self, wx.ID_OK, label=_("&Save"))
        # Translators: Label for the Cancel button
        cancel_btn = wx.Button(self, wx.ID_CANCEL, label=_("&Cancel"))
        btn_sizer.AddButton(save_btn)
        btn_sizer.AddButton(cancel_btn)

        if current_content:
            # Translators: Label for the Delete Note button
            delete_btn = wx.Button(self, label=_("&Delete Note"))
            delete_btn.Bind(wx.EVT_BUTTON, self._on_delete)
            main_sizer.Add(delete_btn, 0, wx.LEFT | wx.TOP, 8)

        btn_sizer.Realize()
        main_sizer.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        self.SetSizerAndFit(main_sizer)
        self.Bind(wx.EVT_BUTTON, self._on_save, id=wx.ID_OK)
        self.text_ctrl.SetFocus()

    def _on_save(self, event):
        self.on_save_callback(self.text_ctrl.GetValue())
        self.Destroy()

    def _on_delete(self, event):
        self.on_delete_callback()
        self.Destroy()


def _extract_note_summary(content):
    lines = (content or "").strip().splitlines()
    if not lines:
        return ""
    return lines[0].lstrip("#*-> ")


class NoteListDialog(wx.Dialog):
    """Uygulamadaki notları listeleyen ve Enter ile nesneye odaklanma sunan pencere."""
    def __init__(self, parent, app_name, notes_list, on_focus_note, on_edit_note, on_view_html):
        # Translators: Title of the note list dialog. {app} is application name, {count} is number of notes.
        title = _("{app} - Saved Notes ({count})").format(app=app_name, count=len(notes_list))
        super().__init__(
            parent,
            title=title,
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
        )
        self.notes_list = notes_list
        self.on_focus_note = on_focus_note
        self.on_edit_note = on_edit_note
        self.on_view_html = on_view_html

        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Translators: Instruction label above the list of notes
        lbl = wx.StaticText(self, label=_("Press Enter on a note to focus its control, or F2 to edit it:"))
        main_sizer.Add(lbl, 0, wx.ALL, 8)

        choices = []
        for fp, data in self.notes_list:
            # Translators: Fallback label when control name is empty in the list
            ctrl = data.get("control_name") or _("Unnamed Control")
            first_line = _extract_note_summary(data.get("content", ""))
            choices.append(f"{ctrl}: {first_line[:60]}")

        self.list_box = wx.ListBox(self, choices=choices, style=wx.LB_SINGLE | wx.WANTS_CHARS, size=(520, 250))
        if choices:
            self.list_box.SetSelection(0)
        main_sizer.Add(self.list_box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        # Translators: Button to focus the control associated with the selected note
        focus_btn = wx.Button(self, label=_("&Focus (Enter)"))
        # Translators: Button to edit the selected note
        edit_btn = wx.Button(self, label=_("&Edit (F2)"))
        # Translators: Button to view the selected note in browse mode
        view_btn = wx.Button(self, label=_("&Browse Mode View"))
        # Translators: Button to close the list dialog
        close_btn = wx.Button(self, wx.ID_CANCEL, label=_("&Close"))

        btn_sizer.Add(focus_btn, 0, wx.RIGHT, 6)
        btn_sizer.Add(edit_btn, 0, wx.RIGHT, 6)
        btn_sizer.Add(view_btn, 0, wx.RIGHT, 6)
        btn_sizer.Add(close_btn, 0)
        main_sizer.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        self.SetSizerAndFit(main_sizer)

        self.list_box.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self.list_box.Bind(wx.EVT_LISTBOX_DCLICK, self._trigger_focus)
        focus_btn.Bind(wx.EVT_BUTTON, self._trigger_focus)
        edit_btn.Bind(wx.EVT_BUTTON, self._trigger_edit)
        view_btn.Bind(wx.EVT_BUTTON, self._trigger_view)

        self.list_box.SetFocus()

    def _on_key_down(self, event):
        key = event.GetKeyCode()
        ctrl_down = event.ControlDown()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._trigger_focus(None)
        elif key == wx.WXK_F2 or (ctrl_down and key in (ord("E"), ord("e"))):
            self._trigger_edit(None)
        elif ctrl_down and key in (ord("B"), ord("b")):
            self._trigger_view(None)
        elif key == wx.WXK_ESCAPE:
            self.Destroy()
        else:
            event.Skip()

    def _trigger_focus(self, event):
        sel = self.list_box.GetSelection()
        if sel != wx.NOT_FOUND:
            fp, data = self.notes_list[sel]
            self.Destroy()
            # Brief delay lets Windows restore focus to the target window before focusing the control
            wx.CallLater(120, self.on_focus_note, fp, data)

    def _trigger_edit(self, event):
        sel = self.list_box.GetSelection()
        if sel != wx.NOT_FOUND:
            fp, data = self.notes_list[sel]
            self.Destroy()
            wx.CallAfter(self.on_edit_note, fp, data)

    def _trigger_view(self, event):
        sel = self.list_box.GetSelection()
        if sel != wx.NOT_FOUND:
            fp, data = self.notes_list[sel]
            self.Destroy()
            wx.CallAfter(self.on_view_html, data)


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    # Translators: Category name for input gestures
    scriptCategory = _("Virtual Sticky Notes")

    def __init__(self):
        super().__init__()
        config_dir = globalVars.appArgs.configPath
        db_path = os.path.join(config_dir, "sticky_notes.json")
        self.db = NoteDatabase(db_path)
        self.locator = ObjectLocator()
        self._last_announced = (None, 0.0)
        self._last_navigated_fp = None

    def _generate_fingerprint(self, obj, foreground_title=None):
        return generate_fingerprint(obj, foreground_title=foreground_title)

    def _render_markdown_to_html(self, md_text):
        if markdown:
            return markdown.markdown(md_text, extensions=["tables", "fenced_code", "nl2br"])
        escaped = md_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f"<pre>{escaped}</pre>"

    def _record_announcement(self, fp):
        self._last_announced = (fp, time.monotonic())

    def _was_recently_announced(self, fp, window_seconds=0.6):
        last_fp, last_time = self._last_announced
        return last_fp == fp and (time.monotonic() - last_time) < window_seconds

    def _open_edit_dialog(self, fp, app_name, win_title, ctrl_name, current_content, target_obj=None):
        def on_save(new_content):
            self.db.save_note(fp, app_name, win_title, ctrl_name, new_content)
            if new_content.strip():
                if target_obj is not None:
                    self.locator.cache_object(fp, target_obj)
            else:
                self.locator.invalidate(fp)
            # Translators: Spoken confirmation when a note is saved
            ui.message(_("Note saved."))

        def on_delete():
            self.db.delete_note(fp)
            self.locator.invalidate(fp)
            # Translators: Spoken confirmation when a note is deleted
            ui.message(_("Note deleted."))

        dlg = NoteEditDialog(gui.mainFrame, ctrl_name, current_content, on_save, on_delete)
        gui.mainFrame.prePopup()
        dlg.Show()
        gui.mainFrame.postPopup()

    def _focus_note_object(self, fp, note_data, target_fg, target_ti=None, prefound_obj=None, wrapped=False):
        if target_fg is None:
            target_fg = api.getForegroundObject()

        app_name = note_data.get("app_name") if note_data else None
        target_obj = prefound_obj
        if target_obj is None:
            target_obj = self.locator.find_object(
                fp,
                target_fg,
                tree_interceptor=target_ti,
                expected_app=app_name,
            )

        if target_obj is None:
            tones.beep(220, 120)
            # Translators: Spoken message when the control linked to a note cannot be found in the active window
            ui.message(_("Control for this note was not found in the active window."))
            return False

        mode = self.locator.focus_object(target_obj)
        if mode == FocusMode.FAILED:
            tones.beep(220, 120)
            # Translators: Spoken message when focusing the control linked to a note fails
            ui.message(_("Could not focus the control for this note."))
            return False

        self._last_navigated_fp = fp
        ctrl_name = getattr(target_obj, "name", None) or (note_data.get("control_name") if note_data else "") or _("Unnamed Control")
        summary = _extract_note_summary(note_data.get("content", "") if note_data else "")

        if wrapped:
            tones.beep(520, 35)

        if mode == FocusMode.SYSTEM:
            # System focus fires event_gainFocus, which plays the tone and reads the note summary.
            return True

        if mode == FocusMode.BROWSE_MODE:
            tones.beep(880, 45)
            self._record_announcement(fp)
            if summary:
                # Translators: Spoken message after moving browse mode cursor to a noted control. {control} is control name, {summary} is note's first line.
                ui.message(_("{control}. Note: {summary}").format(control=ctrl_name, summary=summary))
            else:
                ui.message(ctrl_name)
            return True

        if mode == FocusMode.NAVIGATOR:
            tones.beep(660, 45)
            self._record_announcement(fp)
            if summary:
                # Translators: Spoken message when moving NVDA navigator object to a non-focusable noted control. {control} is control name, {summary} is note's first line.
                ui.message(_("Moved navigator object to {control}. Note: {summary}").format(control=ctrl_name, summary=summary))
            else:
                # Translators: Spoken message when moving NVDA navigator object to a non-focusable control.
                ui.message(_("Moved navigator object to {control}.").format(control=ctrl_name))
            return True

        if mode == FocusMode.ALREADY_FOCUSED:
            tones.beep(880, 45)
            self._record_announcement(fp)
            if summary:
                # Translators: Spoken message when the selected note's control is already focused.
                ui.message(_("Already on {control}. Note: {summary}").format(control=ctrl_name, summary=summary))
            else:
                # Translators: Spoken message when already on the selected control.
                ui.message(_("Already on {control}.").format(control=ctrl_name))
            return True

        return True

    def _navigate_noted_objects(self, direction):
        focus_obj = api.getFocusObject()
        fg = api.getForegroundObject()
        app_name = focus_obj.appModule.appName if focus_obj and focus_obj.appModule else "unknown"
        app_notes = self.db.get_notes_for_app(app_name)

        if not app_notes:
            # Translators: Spoken message when no notes exist for the active application
            ui.message(_("No notes saved for {app}.").format(app=app_name))
            return

        notes_by_fp = dict(app_notes)
        target_ti = getattr(focus_obj, "treeInterceptor", None)
        found = self.locator.find_all_noted_objects(set(notes_by_fp.keys()), fg, tree_interceptor=target_ti)

        if not found:
            tones.beep(220, 120)
            # Translators: Spoken message when no controls with saved notes are found in the active window
            ui.message(_("No noted controls found in the active window."))
            return

        fg_title = fg.name if fg and fg.name else ""
        nav_obj = api.getNavigatorObject()

        current_idx = None
        if nav_obj is not None:
            for idx, (fp, obj) in enumerate(found):
                if obj == nav_obj and (obj == focus_obj or fp == self._last_navigated_fp):
                    current_idx = idx
                    break
        if current_idx is None and focus_obj is not None:
            for idx, (fp, obj) in enumerate(found):
                if obj == focus_obj:
                    current_idx = idx
                    break
        if current_idx is None and nav_obj is not None:
            for idx, (fp, obj) in enumerate(found):
                if obj == nav_obj:
                    current_idx = idx
                    break
        if current_idx is None and focus_obj is not None:
            try:
                cur_fp = self._generate_fingerprint(focus_obj, foreground_title=fg_title)
            except Exception:
                cur_fp = None
            for idx, (fp, _obj) in enumerate(found):
                if fp == cur_fp:
                    current_idx = idx
                    break
        if current_idx is None and self._last_navigated_fp is not None:
            for idx, (fp, _obj) in enumerate(found):
                if fp == self._last_navigated_fp:
                    current_idx = idx
                    break

        if current_idx is None:
            next_idx = 0 if direction > 0 else len(found) - 1
            wrapped = False
        else:
            raw_next = current_idx + direction
            wrapped = len(found) > 1 and (raw_next < 0 or raw_next >= len(found))
            next_idx = raw_next % len(found)

        target_fp, target_obj = found[next_idx]
        self._focus_note_object(
            target_fp,
            notes_by_fp.get(target_fp, {}),
            fg,
            target_ti=target_ti,
            prefound_obj=target_obj,
            wrapped=wrapped,
        )

    def event_gainFocus(self, obj, nextHandler):
        try:
            fp = self._generate_fingerprint(obj)
            note = self.db.get_note(fp)
            if note:
                self.locator.cache_object(fp, obj)
                self._last_navigated_fp = fp
                if not self._was_recently_announced(fp):
                    tones.beep(880, 45)
                    first_line = _extract_note_summary(note["content"])
                    # Translators: Spoken alert when focusing a control that has a sticky note. {summary} is the first line of the note.
                    ui.message(_("Note: {summary}").format(summary=first_line))
        except Exception:
            pass
        nextHandler()

    @scriptHandler.script(
        # Translators: Description for the add/edit note script
        description=_("Add or edit a sticky note for the focused control."),
        gesture="kb:NVDA+shift+n"
    )
    def script_editNote(self, gesture):
        obj = api.getFocusObject()
        fp = self._generate_fingerprint(obj)
        existing = self.db.get_note(fp)
        current_content = existing["content"] if existing else ""
        app_name = obj.appModule.appName if obj.appModule else "unknown"
        fg = api.getForegroundObject()
        win_title = fg.name if fg and fg.name else ""
        ctrl_name = obj.name or ""

        wx.CallAfter(self._open_edit_dialog, fp, app_name, win_title, ctrl_name, current_content, obj)

    @scriptHandler.script(
        # Translators: Description for the list notes script
        description=_("Open the list of saved notes for the active application."),
        gesture="kb:NVDA+alt+n"
    )
    def script_listAppNotes(self, gesture):
        obj = api.getFocusObject()
        target_fg = api.getForegroundObject()
        target_ti = getattr(obj, "treeInterceptor", None)
        app_name = obj.appModule.appName if obj.appModule else "unknown"
        notes_list = self.db.get_notes_for_app(app_name)

        if not notes_list:
            # Translators: Spoken message when no notes exist for the active application
            ui.message(_("No notes saved for {app}.").format(app=app_name))
            return

        def on_focus_from_list(fp, data):
            self._focus_note_object(fp, data, target_fg, target_ti=target_ti)

        def on_edit_from_list(fp, data):
            self._open_edit_dialog(
                fp,
                data.get("app_name", app_name),
                data.get("window_title", ""),
                data.get("control_name", ""),
                data.get("content", "")
            )

        def on_view_from_list(data):
            html_body = self._render_markdown_to_html(data.get("content", ""))
            # Translators: Default title for browse mode view when control has no name
            ctrl_title = data.get("control_name") or _("Control Note")
            # Translators: Title of the browse mode window displaying the note
            window_title = _("Sticky Note - {control}").format(control=ctrl_title)
            ui.browseableMessage(message=html_body, title=window_title, isHtml=True)

        def show_list():
            dlg = NoteListDialog(
                gui.mainFrame,
                app_name,
                notes_list,
                on_focus_from_list,
                on_edit_from_list,
                on_view_from_list,
            )
            gui.mainFrame.prePopup()
            dlg.Show()
            gui.mainFrame.postPopup()

        wx.CallAfter(show_list)

    @scriptHandler.script(
        # Translators: Description for focusing the next noted control
        description=_("Focus the next control with a sticky note in the active window."),
        gesture="kb:NVDA+alt+downArrow"
    )
    def script_nextNotedObject(self, gesture):
        self._navigate_noted_objects(direction=1)

    @scriptHandler.script(
        # Translators: Description for focusing the previous noted control
        description=_("Focus the previous control with a sticky note in the active window."),
        gesture="kb:NVDA+alt+upArrow"
    )
    def script_previousNotedObject(self, gesture):
        self._navigate_noted_objects(direction=-1)

    @scriptHandler.script(
        # Translators: Description for the view note in browse mode script
        description=_("View the sticky note of the focused control in browse mode."),
        gesture="kb:NVDA+control+n"
    )
    def script_viewCurrentNoteHtml(self, gesture):
        obj = api.getFocusObject()
        fp = self._generate_fingerprint(obj)
        note = self.db.get_note(fp)

        if not note:
            # Translators: Spoken message when the focused control has no note
            ui.message(_("No note saved for this control."))
            return

        html_body = self._render_markdown_to_html(note["content"])
        ctrl_title = note["control_name"] or _("Control Note")
        window_title = _("Sticky Note - {control}").format(control=ctrl_title)
        ui.browseableMessage(message=html_body, title=window_title, isHtml=True)