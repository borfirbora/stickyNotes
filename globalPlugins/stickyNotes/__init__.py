import os
import sys
import json
import hashlib
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


class NoteListDialog(wx.Dialog):
    """Uygulamadaki notları listeleyen ve Enter ile düzenleme sunan pencere."""
    def __init__(self, parent, app_name, notes_list, on_edit_note, on_view_html):
        # Translators: Title of the note list dialog. {app} is application name, {count} is number of notes.
        title = _("{app} - Saved Notes ({count})").format(app=app_name, count=len(notes_list))
        super().__init__(
            parent,
            title=title,
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
        )
        self.notes_list = notes_list
        self.on_edit_note = on_edit_note
        self.on_view_html = on_view_html

        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Translators: Instruction label above the list of notes
        lbl = wx.StaticText(self, label=_("Press Enter on a note to edit it:"))
        main_sizer.Add(lbl, 0, wx.ALL, 8)

        choices = []
        for fp, data in self.notes_list:
            # Translators: Fallback label when control name is empty in the list
            ctrl = data.get("control_name") or _("Unnamed Control")
            first_line = data.get("content", "").strip().splitlines()[0].lstrip("#*-> ")
            choices.append(f"{ctrl}: {first_line[:60]}")

        self.list_box = wx.ListBox(self, choices=choices, style=wx.LB_SINGLE | wx.WANTS_CHARS, size=(500, 250))
        if choices:
            self.list_box.SetSelection(0)
        main_sizer.Add(self.list_box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        # Translators: Button to edit the selected note
        edit_btn = wx.Button(self, label=_("&Edit (Enter)"))
        # Translators: Button to view the selected note in browse mode
        view_btn = wx.Button(self, label=_("&Browse Mode View"))
        # Translators: Button to close the list dialog
        close_btn = wx.Button(self, wx.ID_CANCEL, label=_("&Close"))

        btn_sizer.Add(edit_btn, 0, wx.RIGHT, 6)
        btn_sizer.Add(view_btn, 0, wx.RIGHT, 6)
        btn_sizer.Add(close_btn, 0)
        main_sizer.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        self.SetSizerAndFit(main_sizer)

        self.list_box.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self.list_box.Bind(wx.EVT_LISTBOX_DCLICK, self._trigger_edit)
        edit_btn.Bind(wx.EVT_BUTTON, self._trigger_edit)
        view_btn.Bind(wx.EVT_BUTTON, self._trigger_view)

        self.list_box.SetFocus()

    def _on_key_down(self, event):
        key = event.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._trigger_edit(None)
        elif key == wx.WXK_ESCAPE:
            self.Destroy()
        else:
            event.Skip()

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

    def _generate_fingerprint(self, obj):
        app_name = obj.appModule.appName if obj.appModule else "unknown"
        role = str(obj.role)
        name = obj.name or ""
        win_class = obj.windowClassName or ""
        ctrl_id = str(obj.windowControlID) if getattr(obj, "windowControlID", 0) else ""

        ia2_attrs = getattr(obj, "IA2Attributes", None)
        if isinstance(ia2_attrs, dict):
            dom_id = ia2_attrs.get("id", "")
            tag = ia2_attrs.get("tag", "")
            xml_roles = ia2_attrs.get("xml-roles", "")
            web_sig = f"id:{dom_id}" if dom_id else f"tag:{tag}|xml:{xml_roles}|name:{name}"
            fg = api.getForegroundObject()
            win_title = fg.name if fg and fg.name else ""
            raw_sig = f"{app_name}|{win_title}|{role}|{web_sig}"
        else:
            raw_sig = f"{app_name}|{win_class}|{ctrl_id}|{role}|{name}"

        return hashlib.sha256(raw_sig.encode("utf-8", errors="ignore")).hexdigest()

    def _render_markdown_to_html(self, md_text):
        if markdown:
            return markdown.markdown(md_text, extensions=["tables", "fenced_code", "nl2br"])
        escaped = md_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f"<pre>{escaped}</pre>"

    def _open_edit_dialog(self, fp, app_name, win_title, ctrl_name, current_content):
        def on_save(new_content):
            self.db.save_note(fp, app_name, win_title, ctrl_name, new_content)
            # Translators: Spoken confirmation when a note is saved
            ui.message(_("Note saved."))

        def on_delete():
            self.db.delete_note(fp)
            # Translators: Spoken confirmation when a note is deleted
            ui.message(_("Note deleted."))

        dlg = NoteEditDialog(gui.mainFrame, ctrl_name, current_content, on_save, on_delete)
        gui.mainFrame.prePopup()
        dlg.Show()
        gui.mainFrame.postPopup()

    def event_gainFocus(self, obj, nextHandler):
        try:
            fp = self._generate_fingerprint(obj)
            note = self.db.get_note(fp)
            if note:
                tones.beep(880, 45)
                first_line = note["content"].strip().splitlines()[0].lstrip("#*-> ")
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

        wx.CallAfter(self._open_edit_dialog, fp, app_name, win_title, ctrl_name, current_content)

    @scriptHandler.script(
        # Translators: Description for the list notes script
        description=_("Open the list of saved notes for the active application."),
        gesture="kb:NVDA+alt+n"
    )
    def script_listAppNotes(self, gesture):
        obj = api.getFocusObject()
        app_name = obj.appModule.appName if obj.appModule else "unknown"
        notes_list = self.db.get_notes_for_app(app_name)

        if not notes_list:
            # Translators: Spoken message when no notes exist for the active application
            ui.message(_("No notes saved for {app}.").format(app=app_name))
            return

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
            dlg = NoteListDialog(gui.mainFrame, app_name, notes_list, on_edit_from_list, on_view_from_list)
            gui.mainFrame.prePopup()
            dlg.Show()
            gui.mainFrame.postPopup()

        wx.CallAfter(show_list)

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