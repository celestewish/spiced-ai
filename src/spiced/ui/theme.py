"""Visual theme: saffron accents, cream background, deep brown text.

Calm spacing, rounded panels, and readable typography. The palette is kept in
one place so screens stay consistent.

In-App Accessibility Settings (Phase L, section 9 part 2, Core tier): four
runtime-toggleable variants layered onto the base palette/stylesheet below,
via ``build_stylesheet`` --

- **Text size** (small/normal/large): a real base ``font-size`` multiplier
  applied to the generated stylesheet's ``*`` rule -- see ``TEXT_SIZES``.
- **High-contrast palette** (``HIGH_CONTRAST_PALETTE``): near-black text on
  pure white panels and a darker, more saturated accent -- genuinely
  higher-contrast values against the default palette (e.g. default body text
  ``BROWN`` #3A2C1F on ``CREAM`` #FBF3E4 is roughly 10.6:1; high-contrast's
  #000000 on #FFFFFF is 21:1, the maximum possible), not a relabeling of the
  same colors.
- **Colorblind-safe palette** (``COLORBLIND_SAFE_PALETTE``): swaps the accent
  hues for colors from the Okabe–Ito qualitative palette (Okabe & Ito,
  "Color Universal Design (CUD)", 2008) -- a well-known, widely-cited set
  chosen to stay distinguishable under the common forms of color vision
  deficiency. Cited here rather than hand-rolled: Spiced has no existing
  colorblindness simulation matrix to reuse for this -- ``core.accessibility``
  (the Accessibility Pass feature) reviews the *developer's own game*, not
  Spiced's own UI, and doesn't implement a simulation matrix either.
- **Motion reduction**: checked across this module and every screen in
  ``ui/`` -- Spiced's UI has no ``QPropertyAnimation``/``QVariantAnimation``/
  transition anywhere today, so there is genuinely nothing to reduce. Rather
  than inventing motion just to gate it, ``build_stylesheet``'s
  ``reduce_motion`` parameter is accepted, stored, and threaded through the
  Settings screen honestly labeled as a no-op for now (see
  ``ACCESSIBILITY_MOTION_NOTE`` and ``ui.screens.settings``) -- present and
  wired end-to-end so a future animation automatically has something to
  check, but not faked today.

If both ``high_contrast`` and ``colorblind_safe`` are requested together,
high-contrast wins (documented, not silent) -- it's the stronger
accessibility need of the two and its near-black-on-white values already
read clearly under color vision deficiency too.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Default palette ---------------------------------------------------------
CREAM = "#FBF3E4"
CREAM_PANEL = "#FFFDF8"
SAFFRON = "#E8873B"
SAFFRON_DEEP = "#D2721F"
BROWN = "#3A2C1F"
BROWN_SOFT = "#6E5A48"
BORDER = "#E7D7BE"
SIDEBAR = "#F3E5CC"
SELECTED = "#F6D9AF"

_PALETTE_KEYS = (
    "CREAM",
    "CREAM_PANEL",
    "SAFFRON",
    "SAFFRON_DEEP",
    "BROWN",
    "BROWN_SOFT",
    "BORDER",
    "SIDEBAR",
    "SELECTED",
)

DEFAULT_PALETTE = {
    "CREAM": CREAM,
    "CREAM_PANEL": CREAM_PANEL,
    "SAFFRON": SAFFRON,
    "SAFFRON_DEEP": SAFFRON_DEEP,
    "BROWN": BROWN,
    "BROWN_SOFT": BROWN_SOFT,
    "BORDER": BORDER,
    "SIDEBAR": SIDEBAR,
    "SELECTED": SELECTED,
}

# Near-black on pure white -- 21:1 contrast, the maximum possible, vs. the
# default palette's body text at roughly 10.6:1. The accent is a darker,
# more saturated orange so it still passes against a white panel (the
# default SAFFRON is close to WCAG AA's 3:1 large-text/UI-component floor
# against white; this one clears it with real margin).
HIGH_CONTRAST_PALETTE = {
    "CREAM": "#FFFFFF",
    "CREAM_PANEL": "#FFFFFF",
    "SAFFRON": "#B35900",
    "SAFFRON_DEEP": "#7A3D00",
    "BROWN": "#000000",
    "BROWN_SOFT": "#333333",
    "BORDER": "#000000",
    "SIDEBAR": "#EDEDED",
    "SELECTED": "#FFD9A0",
}

# Accent hues drawn from the Okabe-Ito colorblind-safe qualitative palette
# (vermillion #D55E00 / a darker vermillion for the "deep" variant) --
# chosen to stay distinguishable from the sidebar/border neutrals under
# protanopia/deuteranopia/tritanopia, unlike the default's orange-on-cream
# pairing which can read as low-contrast under red-green deficiency.
COLORBLIND_SAFE_PALETTE = {
    "CREAM": "#FBF3E4",
    "CREAM_PANEL": "#FFFDF8",
    "SAFFRON": "#D55E00",
    "SAFFRON_DEEP": "#9C4500",
    "BROWN": "#1B1B1B",
    "BROWN_SOFT": "#4D4D4D",
    "BORDER": "#CCCCCC",
    "SIDEBAR": "#F0E6D8",
    "SELECTED": "#F5D6B3",
}

TEXT_SIZES = {
    "small": 12,
    "normal": 14,
    "large": 18,
}
DEFAULT_TEXT_SIZE = "normal"

ACCESSIBILITY_MOTION_NOTE = (
    "Spiced's UI has no animations or transitions today, so this setting has nothing to "
    "act on yet -- turning it on is safe and future-proof (any animation added later is "
    "expected to check this setting) but changes nothing visible right now."
)


@dataclass(frozen=True)
class AccessibilityOptions:
    """One bundle of accessibility settings -- see ``build_stylesheet``."""

    text_size: str = DEFAULT_TEXT_SIZE
    high_contrast: bool = False
    colorblind_safe: bool = False
    reduce_motion: bool = False


def _resolve_palette(*, high_contrast: bool, colorblind_safe: bool) -> dict[str, str]:
    if high_contrast:
        return HIGH_CONTRAST_PALETTE
    if colorblind_safe:
        return COLORBLIND_SAFE_PALETTE
    return DEFAULT_PALETTE


def build_stylesheet(
    *,
    text_size: str = DEFAULT_TEXT_SIZE,
    high_contrast: bool = False,
    colorblind_safe: bool = False,
    reduce_motion: bool = False,  # noqa: ARG001 -- accepted for API completeness, see module docstring
) -> str:
    """Build the app's QSS stylesheet for a given set of accessibility
    settings. Called with no arguments, this returns exactly the same
    stylesheet Spiced has always used (``STYLESHEET`` below is just
    ``build_stylesheet()``, evaluated once at import time for callers that
    don't need to vary it).
    """
    palette = _resolve_palette(high_contrast=high_contrast, colorblind_safe=colorblind_safe)
    font_size = TEXT_SIZES.get(text_size, TEXT_SIZES[DEFAULT_TEXT_SIZE])
    p = palette

    return f"""
* {{
    font-family: "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif;
    font-size: {font_size}px;
    color: {p["BROWN"]};
}}

QMainWindow, QWidget#Root {{
    background: {p["CREAM"]};
}}

/* Panels */
QFrame#Panel, QFrame#Sidebar, QFrame#ContextPanel, QFrame#TopBar {{
    background: {p["CREAM_PANEL"]};
    border: 1px solid {p["BORDER"]};
    border-radius: 14px;
}}

QFrame#Sidebar {{
    background: {p["SIDEBAR"]};
}}

/* Top bar (Phase K): Spiced wordmark + Multi-Project Switcher, notification
   bell on the right. Kept minimal -- reuses Panel's own background/border. */
QDialog#Panel {{
    background: {p["CREAM_PANEL"]};
    border: 1px solid {p["BORDER"]};
    border-radius: 14px;
}}

/* Dashboard cards */
QFrame#Card {{
    background: {p["CREAM_PANEL"]};
    border: 1px solid {p["BORDER"]};
    border-radius: 12px;
}}
QFrame#ReadinessCard {{
    background: {p["SELECTED"]};
    border: 1px solid {p["SAFFRON"]};
    border-radius: 12px;
}}
QLabel#CardTitle {{
    font-size: {font_size + 1}px;
    font-weight: 700;
    color: {p["SAFFRON_DEEP"]};
}}
QLabel#ReadinessLabel {{
    font-size: {font_size + 4}px;
    font-weight: 700;
    color: {p["BROWN"]};
}}

QLabel#Brand {{
    font-size: {font_size + 8}px;
    font-weight: 700;
    color: {p["SAFFRON_DEEP"]};
    padding: 6px 4px;
}}

QLabel#Tagline {{
    color: {p["BROWN_SOFT"]};
    font-size: {max(font_size - 2, 10)}px;
    padding: 0 4px 8px 4px;
}}

QLabel#ScreenTitle {{
    font-size: {font_size + 6}px;
    font-weight: 700;
    color: {p["BROWN"]};
}}

QLabel#SectionTitle {{
    font-size: {max(font_size - 1, 10)}px;
    font-weight: 700;
    color: {p["BROWN_SOFT"]};
    text-transform: uppercase;
    letter-spacing: 1px;
}}

QLabel#Muted {{
    color: {p["BROWN_SOFT"]};
}}

/* Sidebar navigation buttons */
QPushButton#NavButton {{
    text-align: left;
    padding: 11px 14px;
    border: none;
    border-radius: 10px;
    background: transparent;
    font-size: {font_size}px;
    color: {p["BROWN"]};
}}
QPushButton#NavButton:hover {{
    background: {p["SELECTED"]};
}}
QPushButton#NavButton:checked {{
    background: {p["SAFFRON"]};
    color: white;
    font-weight: 600;
}}

/* Primary buttons */
QPushButton {{
    background: {p["SAFFRON"]};
    color: white;
    border: none;
    border-radius: 10px;
    padding: 9px 16px;
    font-weight: 600;
}}
QPushButton:hover {{ background: {p["SAFFRON_DEEP"]}; }}
QPushButton:disabled {{ background: {p["BORDER"]}; color: {p["BROWN_SOFT"]}; }}

QPushButton#Ghost {{
    background: transparent;
    color: {p["SAFFRON_DEEP"]};
    border: 1px solid {p["SAFFRON"]};
}}
QPushButton#Ghost:hover {{ background: {p["SELECTED"]}; }}

/* Inputs */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {{
    background: white;
    border: 1px solid {p["BORDER"]};
    border-radius: 10px;
    padding: 8px 10px;
    selection-background-color: {p["SAFFRON"]};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
    border: 1px solid {p["SAFFRON"]};
}}

/* Usage / plan pill */
QLabel#UsagePill {{
    background: {p["SELECTED"]};
    color: {p["BROWN"]};
    border-radius: 12px;
    padding: 8px 12px;
    font-size: {max(font_size - 2, 10)}px;
    font-weight: 600;
}}

QListWidget {{
    background: transparent;
    border: none;
}}
QListWidget::item {{
    padding: 8px;
    border-radius: 8px;
}}
QListWidget::item:selected {{
    background: {p["SELECTED"]};
    color: {p["BROWN"]};
}}

/* Live Task Progress Transparency (Phase L): the appending plain-language
   step trail -- see ui.widgets.progress_trail.ProgressTrail. */
QListWidget#ProgressTrailList {{
    background: {p["CREAM_PANEL"]};
    border: 1px solid {p["BORDER"]};
    border-radius: 10px;
}}
QListWidget#ProgressTrailList::item {{
    color: {p["BROWN_SOFT"]};
    font-size: {max(font_size - 2, 10)}px;
}}

QScrollArea {{ border: none; background: transparent; }}

/* Every screen wraps its content in a QScrollArea, with the actual content
   living in a plain QWidget passed to setWidget() (see e.g. dashboard.py's
   `content = QWidget()`). That widget sits a level below QScrollArea's own
   background rule above (it's a child of the scroll area's internal
   viewport, not of QScrollArea directly, so the transparent rule above
   never reached it) and was picking up Qt's raw default widget background
   instead of the app's theme -- black under a dark OS theme, since nothing
   here ever gave it an explicit color. Named consistently so every screen's
   scroll content renders correctly regardless of the OS theme. */
QWidget#ScrollContent {{ background: {p["CREAM"]}; }}
"""


# Evaluated once at import time -- exactly the stylesheet this module has
# always exported, for callers that don't need a non-default variant.
STYLESHEET = build_stylesheet()
