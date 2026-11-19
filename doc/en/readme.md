# Virtual Sticky Notes

* **Author:** Bora Fırlangeç
* **Version:** 1.0.0
* **NVDA Compatibility:** 2023.1 and later

Virtual Sticky Notes is an NVDA add-on that allows blind and visually impaired users to attach personal **Markdown**-formatted sticky notes to specific UI controls (buttons, text fields, links, etc.) across desktop applications and web pages.

## Key Features

* **Smart Control Fingerprinting:** Notes remain attached to their target controls even after restarting applications or refreshing web pages.
* **Instant Audio & Speech Feedback:** When focusing on a control that has an attached note, NVDA plays a brief notification tone and speaks the first line of the note as a summary.
* **Markdown Support:** Write structured notes using headings (`#`), lists (`-`), links (`[text](url)`), and tables.
* **Browse Mode Rendering:** View notes rendered as HTML directly inside NVDA's virtual buffer without opening an external browser. Navigate through headings (`H`), lists (`L`), and links (`K`) using standard browse mode quick navigation keys.
* **Application Note List:** View all saved notes for the currently active application in a single list and press **Enter** on any item to edit it immediately.
* **Persistent Storage:** Notes are stored in your NVDA user configuration directory (`sticky_notes.json`), ensuring your data remains safe across add-on updates.

## Keyboard Shortcuts

All gestures can be customized under **NVDA Menu > Preferences > Input Gestures > Virtual Sticky Notes**:

| Shortcut | Action |
| :--- | :--- |
| `NVDA + Shift + N` | Add a new sticky note or edit the existing note for the focused control. |
| `NVDA + Alt + N` | Open a list of all saved notes for the active application (press `Enter` on a note to edit it). |
| `NVDA + Ctrl + N` | Render and view the focused control's sticky note in NVDA's browse mode window. |

## Usage Tips

1. Move focus to any unlabeled button or complex web form control and press `NVDA + Shift + N`.
2. Type your reminder using Markdown syntax in the multiline text box and activate the **Save** button.
3. Whenever you focus on that control again, NVDA will notify you automatically.
4. To inspect a long note or follow links inside it, press `NVDA + Ctrl + N` to open the browse mode view, and press `Escape` to return to your previous position.