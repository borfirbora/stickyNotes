import hashlib
import time
from collections import deque

import api
import controlTypes
import winUser


class FocusMode:
    """Result modes returned by ObjectLocator.focus_object."""
    SYSTEM = "system"
    BROWSE_MODE = "browse_mode"
    NAVIGATOR = "navigator"
    ALREADY_FOCUSED = "already_focused"
    FAILED = "failed"


def _get_state(name):
    """Return an NVDA controlTypes state constant across NVDA 2022.1–2026.1+."""
    state_enum = getattr(controlTypes, "State", None)
    if state_enum is not None and hasattr(state_enum, name):
        return getattr(state_enum, name)
    return getattr(controlTypes, f"STATE_{name}", None)


def generate_fingerprint(obj, foreground_title=None):
    """Generate the SHA-256 fingerprint identifying an NVDAObject.

    Accepts an optional foreground_title to avoid repeated api.getForegroundObject()
    calls during accessibility tree traversal.
    """
    app_module = getattr(obj, "appModule", None)
    app_name = app_module.appName if app_module else "unknown"
    role = str(getattr(obj, "role", ""))
    name = getattr(obj, "name", None) or ""
    win_class = getattr(obj, "windowClassName", None) or ""
    ctrl_id_val = getattr(obj, "windowControlID", 0)
    ctrl_id = str(ctrl_id_val) if ctrl_id_val else ""

    ia2_attrs = getattr(obj, "IA2Attributes", None)
    if isinstance(ia2_attrs, dict):
        dom_id = ia2_attrs.get("id", "")
        tag = ia2_attrs.get("tag", "")
        xml_roles = ia2_attrs.get("xml-roles", "")
        web_sig = f"id:{dom_id}" if dom_id else f"tag:{tag}|xml:{xml_roles}|name:{name}"
        if foreground_title is None:
            fg = api.getForegroundObject()
            win_title = fg.name if fg and fg.name else ""
        else:
            win_title = foreground_title
        raw_sig = f"{app_name}|{win_title}|{role}|{web_sig}"
    else:
        raw_sig = f"{app_name}|{win_class}|{ctrl_id}|{role}|{name}"

    return hashlib.sha256(raw_sig.encode("utf-8", errors="ignore")).hexdigest()


def _get_states_safe(obj):
    try:
        states = getattr(obj, "states", None)
        return states if states is not None else set()
    except Exception:
        return set()


def _is_defunct(obj):
    defunct_state = _get_state("DEFUNCT")
    if defunct_state is None:
        return False
    return defunct_state in _get_states_safe(obj)


def _is_focusable(obj):
    focusable_state = _get_state("FOCUSABLE")
    if focusable_state is None:
        return False
    return focusable_state in _get_states_safe(obj)


def _node_identity_key(obj):
    """Build a best-effort cycle-guard key without collapsing distinct siblings."""
    ia2_id = getattr(obj, "IA2UniqueID", None)
    runtime_id = getattr(obj, "runtimeID", None)
    hwnd = getattr(obj, "windowHandle", None)
    if runtime_id is not None:
        try:
            return ("uia", hwnd, tuple(runtime_id))
        except TypeError:
            return ("uia", hwnd, runtime_id)
    if ia2_id is not None:
        return ("ia2", hwnd, ia2_id)
    return ("py", id(obj))


def _iter_children_safe(obj, max_siblings=500):
    """Lazily iterate children via firstChild/next with cycle and COM error protection."""
    try:
        child = obj.firstChild
    except Exception:
        return

    seen_siblings = set()
    count = 0
    while child is not None and count < max_siblings:
        key = _node_identity_key(child)
        if key in seen_siblings:
            break
        seen_siblings.add(key)
        yield child
        count += 1
        try:
            next_child = child.next
        except Exception:
            break
        if next_child is child:
            break
        child = next_child


def _belongs_to_window(obj, root_fg, max_parent_hops=40):
    """Verify whether obj belongs to the same top-level window as root_fg."""
    if root_fg is None:
        return True
    if obj == root_fg:
        return True

    obj_hwnd = getattr(obj, "windowHandle", None)
    fg_hwnd = getattr(root_fg, "windowHandle", None)
    if obj_hwnd and fg_hwnd:
        if obj_hwnd == fg_hwnd:
            return True
        get_ancestor = getattr(winUser, "getAncestor", None)
        ga_root = getattr(winUser, "GA_ROOT", None)
        if callable(get_ancestor) and ga_root is not None:
            try:
                obj_root = get_ancestor(obj_hwnd, ga_root)
                fg_root = get_ancestor(fg_hwnd, ga_root)
                if obj_root and fg_root:
                    return obj_root == fg_root
            except Exception:
                pass

    cur = obj
    for _ in range(max_parent_hops):
        try:
            parent = cur.parent
        except Exception:
            break
        if parent is None or parent is cur:
            break
        if parent == root_fg:
            return True
        cur = parent
    return False


class ObjectLocator:
    """Locates and focuses NVDAObjects associated with saved sticky notes."""

    def __init__(self, max_nodes=2500, max_depth=30, time_budget=1.5):
        self.max_nodes = max_nodes
        self.max_depth = max_depth
        self.time_budget = time_budget
        self._cache = {}

    def cache_object(self, fingerprint, obj):
        if fingerprint and obj is not None:
            self._cache[fingerprint] = obj

    def invalidate(self, fingerprint):
        self._cache.pop(fingerprint, None)

    def clear_cache(self):
        self._cache.clear()

    def _is_cached_object_valid(self, obj, expected_fp, root_fg, fg_title, expected_app=None):
        if obj is None:
            return False
        try:
            hwnd = getattr(obj, "windowHandle", None)
            if hwnd and hasattr(winUser, "isWindow") and not winUser.isWindow(hwnd):
                return False
            if _is_defunct(obj):
                return False
            if expected_app:
                app_module = getattr(obj, "appModule", None)
                if not app_module or app_module.appName != expected_app:
                    return False
            if root_fg is not None and not _belongs_to_window(obj, root_fg):
                return False
            return generate_fingerprint(obj, foreground_title=fg_title) == expected_fp
        except Exception:
            return False

    def _get_ti_root(self, tree_interceptor):
        if tree_interceptor is None:
            return None
        try:
            root = getattr(tree_interceptor, "rootNVDAObject", None)
            if root is not None and not _is_defunct(root):
                return root
        except Exception:
            pass
        return None

    def _bfs_find_one(self, root, target_fp, fg_title, skip_root, deadline, visited, budget):
        queue = deque([(root, 0)])
        while queue and budget[0] < self.max_nodes and time.monotonic() < deadline:
            node, depth = queue.popleft()
            if node is None:
                continue
            if skip_root is not None and node == skip_root:
                continue
            key = _node_identity_key(node)
            if key in visited:
                continue
            visited.add(key)

            if _is_defunct(node):
                continue

            budget[0] += 1
            try:
                if generate_fingerprint(node, foreground_title=fg_title) == target_fp:
                    return node
            except Exception:
                pass

            if depth < self.max_depth:
                for child in _iter_children_safe(node):
                    queue.append((child, depth + 1))
        return None

    def find_object(self, target_fp, root_fg, tree_interceptor=None, expected_app=None):
        """Locate the live NVDAObject matching target_fp in the active foreground window."""
        if not target_fp or root_fg is None:
            return None

        fg_title = getattr(root_fg, "name", None) or ""

        # Phase 0: O(1) live cache check
        cached = self._cache.get(target_fp)
        if cached is not None:
            if self._is_cached_object_valid(cached, target_fp, root_fg, fg_title, expected_app):
                return cached
            self._cache.pop(target_fp, None)

        deadline = time.monotonic() + self.time_budget
        visited = set()
        budget = [0]

        # Phase 1: Active TreeInterceptor document root first (fast path for web/documents)
        ti_root = self._get_ti_root(tree_interceptor)
        if ti_root is not None and _belongs_to_window(ti_root, root_fg):
            found = self._bfs_find_one(ti_root, target_fp, fg_title, None, deadline, visited, budget)
            if found is not None:
                self.cache_object(target_fp, found)
                return found

        # Phase 2: Active foreground window tree (skipping already-walked ti_root)
        found = self._bfs_find_one(root_fg, target_fp, fg_title, ti_root, deadline, visited, budget)
        if found is not None:
            self.cache_object(target_fp, found)
            return found

        return None

    def _dfs_collect_all(self, root, target_fps, fg_title, skip_root, deadline, visited, budget, results):
        stack = [(root, 0)]
        while stack and budget[0] < self.max_nodes and time.monotonic() < deadline:
            node, depth = stack.pop()
            if node is None:
                continue
            if skip_root is not None and node == skip_root:
                continue
            key = _node_identity_key(node)
            if key in visited:
                continue
            visited.add(key)

            if _is_defunct(node):
                continue

            budget[0] += 1
            try:
                fp = generate_fingerprint(node, foreground_title=fg_title)
                if fp in target_fps:
                    results.append((fp, node))
                    self.cache_object(fp, node)
            except Exception:
                pass

            if depth < self.max_depth:
                children = list(_iter_children_safe(node))
                for child in reversed(children):
                    stack.append((child, depth + 1))

    def find_all_noted_objects(self, target_fps, root_fg, tree_interceptor=None):
        """Return ordered (fingerprint, NVDAObject) pairs for all noted controls in root_fg."""
        if not target_fps or root_fg is None:
            return []

        fg_title = getattr(root_fg, "name", None) or ""
        deadline = time.monotonic() + self.time_budget
        visited = set()
        budget = [0]
        results = []

        ti_root = self._get_ti_root(tree_interceptor)
        if ti_root is not None and _belongs_to_window(ti_root, root_fg):
            self._dfs_collect_all(ti_root, target_fps, fg_title, None, deadline, visited, budget, results)

        self._dfs_collect_all(root_fg, target_fps, fg_title, ti_root, deadline, visited, budget, results)
        return results

    def focus_object(self, target_obj):
        """Smartly focus target_obj using Browse Mode, system focus, or Navigator Object.

        Returns one of the FocusMode constants.
        """
        if target_obj is None or _is_defunct(target_obj):
            return FocusMode.FAILED

        # Best-effort scroll into view before focusing
        try:
            scroll = getattr(target_obj, "scrollIntoView", None)
            if callable(scroll):
                scroll()
        except Exception:
            pass

        # 1. Active Browse Mode (TreeInterceptor with passThrough == False)
        ti = getattr(target_obj, "treeInterceptor", None)
        if ti is not None and not getattr(ti, "passThrough", False):
            try:
                cur_sel = getattr(ti, "selection", None)
                if cur_sel is not None and getattr(cur_sel, "NVDAObjectAtStart", None) == target_obj:
                    api.setNavigatorObject(target_obj)
                    return FocusMode.ALREADY_FOCUSED
            except Exception:
                pass

            try:
                info = ti.makeTextInfo(target_obj)
                info.collapse()
                ti.selection = info
                api.setNavigatorObject(target_obj)
                if _is_focusable(target_obj):
                    try:
                        target_obj.setFocus()
                    except Exception:
                        pass
                return FocusMode.BROWSE_MODE
            except Exception:
                # Fall through to standard system focus / navigator object
                pass

        # Check if system focus is already on target_obj
        try:
            if api.getFocusObject() == target_obj:
                api.setNavigatorObject(target_obj)
                return FocusMode.ALREADY_FOCUSED
        except Exception:
            pass

        # 2. Focusable control -> System keyboard focus
        if _is_focusable(target_obj):
            try:
                target_obj.setFocus()
                api.setNavigatorObject(target_obj)
                return FocusMode.SYSTEM
            except Exception:
                pass

        # 3. Fallback -> Move NVDA Navigator Object
        try:
            api.setNavigatorObject(target_obj)
            return FocusMode.NAVIGATOR
        except Exception:
            return FocusMode.FAILED
