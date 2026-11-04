# English / Ukrainian Auto Layout

A quiet Ubuntu **X11 background utility** with a tray icon. Keep using your
normal English (US) and Ukrainian keyboard layouts. There is no special input
source to select and no preedit underline.

Type normally. After Space is released, a recognised wrong-layout word such as
`ghbdsn` is replaced with `привіт`. The reverse direction works too: `руддщ`
becomes `hello`. By default the keyboard switches to the corrected language
for the next word. Words that already exist in the current language, ambiguous
words, unknown names and words shorter than four characters are left alone.

Select text in an editable application and press **Ctrl+Alt+Space** to convert
its keyboard positions between English and Ukrainian. The shortcut can be changed
in Settings; the direction follows the majority of English or Ukrainian letters.

## Install / upgrade

Target: Ubuntu 22.04 or newer, **Ubuntu on Xorg / X11**. Both standard US and
Ukrainian layouts must already be present in Ubuntu Keyboard settings. A native
Wayland session and raw Linux virtual consoles are not supported by this backend.

```bash
./scripts/build-deb.sh
sudo apt install ./dist/en-ua-switcher_0.2.3_all.deb
```

The app starts quietly at your next sign-in. To start it immediately, run
`en-ua-switcher --run`, or open **English / Ukrainian Auto Layout** from the app
menu. The app menu opens Settings; closing Settings leaves the tray utility
running. Opening it repeatedly uses the same process.

Upgrading from 0.1.x removes the old IBus component. At startup the utility
removes only its obsolete `English / Ukrainian (Automatic)` input source;
existing English, Ukrainian and other sources are preserved. It no longer
changes GNOME's per-window preferences or GTK input module.

## Tray and settings

Click the keyboard tray icon to enable/disable correction, open Settings or
Quit. There are no routine notifications or forced language-selection dialogs.
The Ubuntu AppIndicator tray extension must be enabled to display the icon.
If it is disabled, the application-menu entry still opens Settings.

Settings include:

* Start quietly when signing in.
* Enable or pause automatic correction.
* Switch keyboard layout after a correction, or keep the current layout.
* Minimum word length (4–12 characters).
* Per-application exclusions using case-insensitive X11 WM_CLASS fragments.
* Optional terminal correction, disabled by default.
* Shortcut for manually converting selected text (default Ctrl+Alt+Space).

Settings are saved in `~/.config/en-ua-switcher/settings.json`. Typed words,
clipboard data and document contents are never saved or sent over the network.

## Conservative behaviour and limits

Normal keystrokes go straight to the application. The utility observes only
recent keyboard events and does not intercept normal typing. On a correction,
it checks the focused window and held keys, removes only the freshly typed
word plus its Space using Backspace, then replays the corrected word and Space
through XTEST. It uses the installed keyboard layouts, without changing the
clipboard or installing a hardware keylogger/root service.

Version 0.2.1 fixes a first-character race such as `ghbdsn` → `gривіт`:
replay waits for a stable keyboard group and paces the synthetic events so
asynchronous input-method clients can consume them in order. Observation runs
on a separate thread; new typing during the settling interval cancels the
pending text replacement before any Backspace is sent. The settling delay is
bounded, and this remains a best-effort desktop operation rather than an
application-provided atomic edit. Quit the old tray instance and start the app
again after upgrading so the running process loads the fix.

Version 0.2.2 refreshes the keyboard map when the desktop changes layouts and
resumes correction when a password field loses focus. These fixes address a
tray process that appears to be running but stops correcting words. Use
`en-ua-switcher --status` to inspect the running monitor, event and correction
counts, password protection and the last skipped replacement. Status never
includes typed text. `en-ua-switcher --quit` stops the tray process before a
restart.

Version 0.2.3 switches GNOME input sources through the configured desktop
shortcut. GNOME reverses direct XKB group changes, which previously left words
unchanged even while the monitor was running. The utility waits for GNOME to
release its temporary keyboard grab before replaying text, and preserves
per-window input-source settings. Other X11 desktops keep the direct XKB path.
GNOME's normal input-source popup may briefly appear during a correction.

Automatic correction is intentionally limited to pure alphabetic words with
optional internal apostrophes and a released Space. Punctuation, Enter, Tab,
paths, numbers and code identifiers do not trigger a correction. Editing,
shortcuts, pasting, mouse clicks, changed focus, long tokens and idle gaps
invalidate the current tracked token. A later ordinary word can be corrected.
Fast typing with overlapping keys may skip a correction to avoid interfering.

This is a dictionary-based helper, not a language model. An unknown intended
word can still map to a known word in the other language and be corrected
incorrectly. Applications that autoformat text or treat Backspace/Space as
commands may be unsuitable: add them to exclusions. Existing or pasted text is changed only when you explicitly select it and invoke the manual shortcut. Replacements are best effort, not an
atomic document edit; an application or focus change during replay can still
interrupt them. Ordinary editor Undo can revert the replay, potentially over
several undo steps; there is no global undo shortcut.

Terminals and known password managers are excluded by default. AT-SPI focus
role metadata is used to skip password fields when applications expose them;
not every application does. Enabling terminal correction also affects shell
commands and unmarked password prompts, so leave it off when that would be
unwanted. The global observer cannot promise password-field detection in all
applications. It never reads field values or surrounding document text.

Manual conversion reads the X11 primary selection and types the result over the
selection; it does not use or change the clipboard. It requires an editable,
active selection in the focused application. It skips text that cannot be typed
with the installed layout, including line breaks, and skips selections with no
clear majority language. The shortcut is observed rather than intercepted, so
avoid combinations already used by the desktop or application. Application
exclusions, terminal and password protection, and the enable switch apply to
manual conversion as well.

The supported desktop path is X11 with RECORD and XTEST. Native Wayland apps,
raw virtual consoles, and applications with raw/exclusive input are unsupported.
On Wayland the app displays the limitation in the tray/settings and does not
run a partial background monitor. It does not modify system security settings.

On GNOME, keep a usable `switch-input-source` shortcut configured in Keyboard
settings (the default is Super+Space). If no shortcut is available, the utility
skips correction and reports the reason in `--status`.

## Diagnostics / development

Use Ubuntu's `/usr/bin/python3` so the GTK and AppIndicator GI bindings are
available.

```bash
/usr/bin/python3 -m en_ua --doctor
/usr/bin/python3 -m en_ua --status
/usr/bin/python3 -m en_ua --run
/usr/bin/python3 -m en_ua --setup
/usr/bin/python3 -m en_ua --convert 'руддщ' --to en
```

Install development dependencies with:

```bash
sudo apt install python3-gi python3-xlib gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 gir1.2-atspi-2.0 libx11-6 libxkbcommon0 python3-enchant hunspell-en-us hunspell-uk
```

Tests:

```bash
/usr/bin/python3 -m unittest discover -v
# Real X11 observer, layout switch and replay in an isolated test application:
EN_UA_X11_TEST=1 xvfb-run -a /usr/bin/python3 -m unittest tests.test_x11 -v
```

The X11 test creates its own window on a virtual display. It never types into
user applications or changes the user's real keyboard configuration. GUI/tray
smoke tests should similarly use a separate Xvfb display and D-Bus session with
an isolated XDG_CONFIG_HOME and in-memory GSettings backend.

Code: `background_core.py` contains conservative word tracking; `x11.py`
implements X11 observation and replacement; `tray.py` provides the singleton
tray application and Settings; `config.py` persists preferences; `core.py`
contains layout mapping and dictionaries. `scripts/build-deb.sh` creates the
Debian installer, including its XDG sign-in autostart entry.

## Remove

Quit from the tray menu, then:

```bash
sudo apt remove en-ua-switcher
```

To remove preferences too, delete `~/.config/en-ua-switcher`.

MIT license.
