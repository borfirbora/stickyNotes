import builtins
import hashlib
import os
import sys
import tempfile
import types
import unittest


def _install_nvda_mocks():
    """Install lightweight NVDA module stubs so the add-on can be tested outside NVDA."""
    builtins._ = lambda s: s

    state_ns = types.SimpleNamespace(
        FOCUSABLE=1,
        DEFUNCT=2,
        INVISIBLE=4,
    )
    control_types = types.ModuleType("controlTypes")
    control_types.State = state_ns

    win_user = types.ModuleType("winUser")
    win_user.GA_ROOT = 2
    win_user._valid_windows = set()
    win_user._root_map = {}
    win_user.isWindow = lambda hwnd: (not win_user._valid_windows) or (hwnd in win_user._valid_windows)
    win_user.getAncestor = lambda hwnd, flag: win_user._root_map.get(hwnd, hwnd)

    api_mod = types.ModuleType("api")
    api_mod._focus = None
    api_mod._fg = None
    api_mod._nav = None
    api_mod.getFocusObject = lambda: api_mod._focus
    api_mod.getForegroundObject = lambda: api_mod._fg
    api_mod.getNavigatorObject = lambda: api_mod._nav
    api_mod.setNavigatorObject = lambda obj: setattr(api_mod, "_nav", obj)

    ui_mod = types.ModuleType("ui")
    ui_mod.messages = []
    ui_mod.browsed = []
    ui_mod.message = lambda msg: ui_mod.messages.append(msg)
    ui_mod.browseableMessage = lambda message, title="", isHtml=False: ui_mod.browsed.append((title, message, isHtml))

    tones_mod = types.ModuleType("tones")
    tones_mod.beeps = []
    tones_mod.beep = lambda freq, dur: tones_mod.beeps.append((freq, dur))

    wx_mod = types.ModuleType("wx")
    wx_mod.Dialog = type("Dialog", (), {"__init__": lambda self, *a, **kw: None})
    wx_mod.DEFAULT_DIALOG_STYLE = 1
    wx_mod.RESIZE_BORDER = 2
    wx_mod.CallAfter = lambda fn, *a, **kw: fn(*a, **kw)
    wx_mod.CallLater = lambda delay, fn, *a, **kw: fn(*a, **kw)

    gui_mod = types.ModuleType("gui")
    gui_mod.mainFrame = types.SimpleNamespace(prePopup=lambda: None, postPopup=lambda: None)

    addon_handler = types.ModuleType("addonHandler")
    addon_handler.initTranslation = lambda: None

    gp_handler = types.ModuleType("globalPluginHandler")
    gp_handler.GlobalPlugin = type("GlobalPlugin", (), {"__init__": lambda self: None})

    script_handler = types.ModuleType("scriptHandler")
    script_handler.script = lambda **kw: (lambda fn: fn)

    global_vars = types.ModuleType("globalVars")
    global_vars.appArgs = types.SimpleNamespace(configPath=tempfile.mkdtemp(prefix="stickynotes_test_"))

    for name, mod in {
        "controlTypes": control_types,
        "winUser": win_user,
        "api": api_mod,
        "ui": ui_mod,
        "tones": tones_mod,
        "wx": wx_mod,
        "gui": gui_mod,
        "addonHandler": addon_handler,
        "globalPluginHandler": gp_handler,
        "scriptHandler": script_handler,
        "globalVars": global_vars,
    }.items():
        sys.modules[name] = mod

    return {
        "api": api_mod,
        "ui": ui_mod,
        "tones": tones_mod,
        "winUser": win_user,
        "controlTypes": control_types,
        "globalVars": global_vars,
    }


MOCKS = _install_nvda_mocks()

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from globalPlugins.stickyNotes import GlobalPlugin  # noqa: E402
from globalPlugins.stickyNotes.object_locator import (  # noqa: E402
    FocusMode,
    ObjectLocator,
    generate_fingerprint,
)


class FakeTextInfo:
    def __init__(self, obj):
        self.NVDAObjectAtStart = obj
        self.collapsed = False

    def collapse(self):
        self.collapsed = True


class FakeTreeInterceptor:
    def __init__(self, root, pass_through=False):
        self.rootNVDAObject = root
        self.passThrough = pass_through
        self.selection = None

    def makeTextInfo(self, obj):
        return FakeTextInfo(obj)


class FakeNVDAObject:
    def __init__(
        self,
        name="",
        role="button",
        app_name="testapp",
        window_class="Button",
        control_id=0,
        window_handle=100,
        ia2_attrs=None,
        ia2_unique_id=None,
        states=None,
        tree_interceptor=None,
    ):
        self.name = name
        self.role = role
        self.appModule = types.SimpleNamespace(appName=app_name)
        self.windowClassName = window_class
        self.windowControlID = control_id
        self.windowHandle = window_handle
        self.IA2Attributes = ia2_attrs
        self.IA2UniqueID = ia2_unique_id
        self.states = set(states) if states is not None else {MOCKS["controlTypes"].State.FOCUSABLE}
        self.treeInterceptor = tree_interceptor
        self.parent = None
        self.firstChild = None
        self.next = None
        self.focused_count = 0
        self.scrolled_count = 0
        self._children = []

    def add_child(self, child):
        child.parent = self
        if self._children:
            self._children[-1].next = child
        else:
            self.firstChild = child
        self._children.append(child)
        return child

    def setFocus(self):
        self.focused_count += 1
        MOCKS["api"]._focus = self

    def scrollIntoView(self):
        self.scrolled_count += 1


class TestObjectLocator(unittest.TestCase):
    def setUp(self):
        MOCKS["ui"].messages.clear()
        MOCKS["tones"].beeps.clear()
        MOCKS["winUser"]._valid_windows.clear()
        MOCKS["winUser"]._root_map.clear()
        MOCKS["api"]._focus = None
        MOCKS["api"]._fg = None
        MOCKS["api"]._nav = None

    def test_fingerprint_matches_legacy_native_and_ia2(self):
        native = FakeNVDAObject(name="Save", role="button", app_name="notepad", window_class="Button", control_id=101)
        expected_native = hashlib.sha256(b"notepad|Button|101|button|Save").hexdigest()
        self.assertEqual(generate_fingerprint(native), expected_native)

        fg = FakeNVDAObject(name="Dashboard - Chrome", app_name="chrome")
        MOCKS["api"]._fg = fg
        web_obj = FakeNVDAObject(
            name="Submit",
            role="button",
            app_name="chrome",
            ia2_attrs={"id": "submit-btn", "tag": "button"},
        )
        expected_web = hashlib.sha256(b"chrome|Dashboard - Chrome|button|id:submit-btn").hexdigest()
        self.assertEqual(generate_fingerprint(web_obj), expected_web)
        self.assertEqual(generate_fingerprint(web_obj, foreground_title="Dashboard - Chrome"), expected_web)

    def test_find_object_uses_cache_and_evicts_defunct(self):
        fg = FakeNVDAObject(name="Main Window", role="window", window_handle=10)
        btn = fg.add_child(FakeNVDAObject(name="OK", role="button", control_id=1, window_handle=10))
        fp = generate_fingerprint(btn, foreground_title=fg.name)

        locator = ObjectLocator()
        locator.cache_object(fp, btn)
        self.assertIs(locator.find_object(fp, fg), btn)

        # Mark cached object defunct and replace it in the tree with a fresh instance
        btn.states.add(MOCKS["controlTypes"].State.DEFUNCT)
        fresh_btn = FakeNVDAObject(name="OK", role="button", control_id=1, window_handle=10)
        fg.firstChild = fresh_btn
        fresh_btn.parent = fg

        found = locator.find_object(fp, fg)
        self.assertIs(found, fresh_btn)

    def test_find_object_prioritizes_tree_interceptor_and_handles_cycles(self):
        fg = FakeNVDAObject(name="Example Page", role="window", app_name="chrome", window_handle=20)
        doc = fg.add_child(FakeNVDAObject(name="Document", role="document", app_name="chrome", window_handle=20))
        heading = doc.add_child(
            FakeNVDAObject(
                name="Release Notes",
                role="heading",
                app_name="chrome",
                window_handle=20,
                ia2_attrs={"tag": "h2", "id": "release-notes"},
                states=set(),
            )
        )
        # Introduce a cycle in sibling link to ensure cycle protection holds
        heading.next = heading

        ti = FakeTreeInterceptor(doc, pass_through=False)
        heading.treeInterceptor = ti
        fp = generate_fingerprint(heading, foreground_title=fg.name)

        locator = ObjectLocator()
        found = locator.find_object(fp, fg, tree_interceptor=ti, expected_app="chrome")
        self.assertIs(found, heading)

    def test_smart_focus_modes(self):
        locator = ObjectLocator()

        # 1. Focusable native control -> SYSTEM
        btn = FakeNVDAObject(name="Save", states={MOCKS["controlTypes"].State.FOCUSABLE})
        self.assertEqual(locator.focus_object(btn), FocusMode.SYSTEM)
        self.assertEqual(btn.focused_count, 1)
        self.assertEqual(btn.scrolled_count, 1)
        self.assertIs(MOCKS["api"].getNavigatorObject(), btn)

        # 2. Already focused -> ALREADY_FOCUSED
        self.assertEqual(locator.focus_object(btn), FocusMode.ALREADY_FOCUSED)

        # 3. Non-focusable native control -> NAVIGATOR
        label = FakeNVDAObject(name="Status Text", role="staticText", states=set())
        self.assertEqual(locator.focus_object(label), FocusMode.NAVIGATOR)
        self.assertEqual(label.focused_count, 0)
        self.assertIs(MOCKS["api"].getNavigatorObject(), label)

        # 4. Browse mode element -> BROWSE_MODE
        doc = FakeNVDAObject(name="Doc", role="document", app_name="chrome")
        ti = FakeTreeInterceptor(doc, pass_through=False)
        heading = FakeNVDAObject(name="Section 1", role="heading", app_name="chrome", states=set(), tree_interceptor=ti)
        self.assertEqual(locator.focus_object(heading), FocusMode.BROWSE_MODE)
        self.assertIsNotNone(ti.selection)
        self.assertIs(ti.selection.NVDAObjectAtStart, heading)
        self.assertTrue(ti.selection.collapsed)
        self.assertIs(MOCKS["api"].getNavigatorObject(), heading)

    def test_next_previous_navigation_and_wrap_around(self):
        MOCKS["globalVars"].appArgs.configPath = tempfile.mkdtemp(prefix="stickynotes_nav_")
        plugin = GlobalPlugin()

        fg = FakeNVDAObject(name="Editor", role="window", app_name="editor", window_handle=50)
        c1 = fg.add_child(FakeNVDAObject(name="First", role="button", app_name="editor", control_id=1, window_handle=50))
        c2 = fg.add_child(FakeNVDAObject(name="Middle", role="staticText", app_name="editor", control_id=2, window_handle=50, states=set()))
        c3 = fg.add_child(FakeNVDAObject(name="Last", role="button", app_name="editor", control_id=3, window_handle=50))
        unnoted = fg.add_child(FakeNVDAObject(name="Other", role="button", app_name="editor", control_id=4, window_handle=50))

        for ctrl, text in [(c1, "Note 1"), (c2, "Note 2"), (c3, "Note 3")]:
            fp = generate_fingerprint(ctrl, foreground_title=fg.name)
            plugin.db.save_note(fp, "editor", fg.name, ctrl.name, text)

        MOCKS["api"]._fg = fg
        MOCKS["api"]._focus = unnoted
        MOCKS["api"]._nav = unnoted

        # Next from unnoted -> c1 (SYSTEM)
        plugin.script_nextNotedObject(None)
        self.assertIs(MOCKS["api"].getFocusObject(), c1)

        # Next from c1 -> c2 (NAVIGATOR, non-focusable)
        plugin.script_nextNotedObject(None)
        self.assertIs(MOCKS["api"].getNavigatorObject(), c2)
        self.assertTrue(any("Moved navigator object to Middle" in m for m in MOCKS["ui"].messages))

        # Next from c2 -> c3 (SYSTEM)
        plugin.script_nextNotedObject(None)
        self.assertIs(MOCKS["api"].getFocusObject(), c3)

        # Next from c3 -> wraps around to c1 with wrap tone (520 Hz)
        MOCKS["tones"].beeps.clear()
        plugin.script_nextNotedObject(None)
        self.assertIs(MOCKS["api"].getFocusObject(), c1)
        self.assertIn((520, 35), MOCKS["tones"].beeps)

        # Previous from c1 -> wraps backward to c3
        MOCKS["tones"].beeps.clear()
        plugin.script_previousNotedObject(None)
        self.assertIs(MOCKS["api"].getFocusObject(), c3)
        self.assertIn((520, 35), MOCKS["tones"].beeps)

    def test_missing_control_announces_error_and_suppresses_duplicate_gainfocus(self):
        MOCKS["globalVars"].appArgs.configPath = tempfile.mkdtemp(prefix="stickynotes_err_")
        plugin = GlobalPlugin()

        fg = FakeNVDAObject(name="Empty Window", role="window", app_name="demo", window_handle=99)
        MOCKS["api"]._fg = fg

        ok = plugin._focus_note_object("nonexistent-fp", {"app_name": "demo", "control_name": "Ghost", "content": "Hi"}, fg)
        self.assertFalse(ok)
        self.assertIn((220, 120), MOCKS["tones"].beeps)
        self.assertTrue(any("not found" in m for m in MOCKS["ui"].messages))

        # Verify duplicate announcement suppression
        btn = fg.add_child(FakeNVDAObject(name="Target", role="button", app_name="demo", control_id=7, window_handle=99))
        fp = generate_fingerprint(btn, foreground_title=fg.name)
        plugin.db.save_note(fp, "demo", fg.name, btn.name, "Important reminder")
        plugin._record_announcement(fp)
        MOCKS["ui"].messages.clear()

        called = []
        plugin.event_gainFocus(btn, lambda: called.append(True))
        self.assertEqual(called, [True])
        self.assertEqual(MOCKS["ui"].messages, [])


if __name__ == "__main__":
    unittest.main()
