"""Visual theme: Frutiger Aqua / Y2K "Aero" gel-and-glass look.

Sunset-gradient shell, translucent glass panels, glossy aqua-accented gel
buttons/pills, and rounded Baloo 2 / Nunito typography -- see
``design_handoff_spiced_frutiger_aqua/README.md`` (the design handoff this
theme implements) for the full visual-direction spec and design tokens this
module's colors are lifted from.

Two honest scope-downs from that spec, both because Qt's QSS dialect doesn't
support the underlying CSS features at all (not a choice, a platform limit):
- No ``backdrop-filter: blur()`` -- "glass" here means translucent gradient
  fills only, not a true blur of whatever sits behind a panel.
- No ``box-shadow``/``text-shadow`` -- real drop-shadow elevation on panels
  is instead applied in code via ``QGraphicsDropShadowEffect`` (see
  ``ui.main_window``), and heading glow is simply dropped.

Calm spacing, rounded panels, and readable typography stay the priority. The
palette is kept in one place so screens stay consistent.

In-App Accessibility Settings (Phase L, section 9 part 2, Core tier): four
runtime-toggleable variants layered onto the base palette/stylesheet below,
via ``build_stylesheet`` --

- **Text size** (small/normal/large): a real base ``font-size`` multiplier
  applied to the generated stylesheet's ``*`` rule -- see ``TEXT_SIZES``.
- **High-contrast palette** (``HIGH_CONTRAST_PALETTE``): near-black text on
  pure white panels and a darker, saturated teal accent -- genuinely
  higher-contrast values against the default palette (e.g. default body text
  ``BROWN`` #1A2340 on a light glass card is roughly 14:1; high-contrast's
  #000000 on #FFFFFF is 21:1, the maximum possible), not a relabeling of the
  same colors. High-contrast also deliberately drops the glass/gradient
  aesthetic in favor of fully opaque panels -- translucency and a
  photographic sunset backdrop would undermine the whole point of this mode,
  so every panel/card background resolves to a flat, opaque value here
  instead of a gradient.
- **Colorblind-safe palette** (``COLORBLIND_SAFE_PALETTE``): keeps the same
  glass/gradient shell as the default look (the aqua accent family is
  already blue-leaning, one of the safer hues under red-green color vision
  deficiency), but swaps the semantic status ramp (success/danger/warning)
  for colors drawn from the Okabe-Ito qualitative palette (Okabe & Ito,
  "Color Universal Design (CUD)", 2008) -- a well-known, widely-cited set
  chosen to stay distinguishable under the common forms of color vision
  deficiency, since red/green/amber status colors are exactly the case that
  palette exists to fix. Cited here rather than hand-rolled: Spiced has no
  existing colorblindness simulation matrix to reuse for this --
  ``core.accessibility`` (the Accessibility Pass feature) reviews the
  *developer's own game*, not Spiced's own UI, and doesn't implement a
  simulation matrix either.
- **Motion reduction**: checked across this module and every screen in
  ``ui/`` -- Spiced's UI has no ``QPropertyAnimation``/``QVariantAnimation``/
  transition anywhere today (the sunset background's "twinkle" dots and the
  glossy gel buttons are static, painted/styled once, not animated), so
  there is genuinely nothing to reduce. Rather than inventing motion just to
  gate it, ``build_stylesheet``'s ``reduce_motion`` parameter is accepted,
  stored, and threaded through the Settings screen honestly labeled as a
  no-op for now (see ``ACCESSIBILITY_MOTION_NOTE`` and ``ui.screens.settings``)
  -- present and wired end-to-end so a future animation automatically has
  something to check, but not faked today.

If both ``high_contrast`` and ``colorblind_safe`` are requested together,
high-contrast wins (documented, not silent) -- it's the stronger
accessibility need of the two and its near-black-on-white values already
read clearly under color vision deficiency too.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Default palette: Frutiger Aqua sunset + aqua-gel ------------------------
#
# Historical key names (CREAM, CREAM_PANEL, SAFFRON, SAFFRON_DEEP, BROWN,
# BROWN_SOFT, BORDER, SIDEBAR, SELECTED) are kept across all three palettes
# below -- some hold plain colors, others hold ready-to-use QSS ``background``
# values (solid color or a full ``qlineargradient(...)`` expression), so a
# single shared stylesheet template can stay mode-agnostic: every mode fills
# in the same placeholders, and only high-contrast's values happen to be flat
# instead of gradients.
CREAM = "#FFF6E8"
CREAM_PANEL = "#FFFDFB"
SAFFRON = "#FF9D54"
SAFFRON_DEEP = "#E2604F"
BROWN = "#1A2340"
BROWN_SOFT = "#3A4258"
BORDER = "rgba(58, 66, 88, 0.18)"
SIDEBAR = "#2B1C46"
SELECTED = "#22B8D6"

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
    # Aqua accent ramp (interactive/active states) -- README "Design Tokens".
    "AQUA_BRIGHT": "#7FE7FF",
    "AQUA_MID": "#22B8D6",
    "AQUA_DEEP": "#0A7EA8",
    # Status/semantic ramp.
    "SUCCESS": "#3FB96F",
    "SUCCESS_DEEP": "#1C7A3F",
    "SUCCESS_TEXT": "#1C8C4A",
    "DANGER": "#E2604F",
    "DANGER_DEEP": "#A83A2E",
    "DANGER_TEXT": "#A83A2E",
    "WARNING": "#FFB347",
    "WARNING_DEEP": "#C97E1A",
    "WARNING_TEXT": "#A85F10",
    "NEUTRAL": "#C3CCDB",
    "NEUTRAL_DEEP": "#8F9AB0",
    "NEUTRAL_TEXT": "#5A6478",
    # Root shell background: the sunset environment gradient.
    "ROOT_BG": (
        "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
        "stop:0 #160f38, stop:0.22 #3a1361, stop:0.46 #7c2f78, "
        "stop:0.7 #e2604f, stop:0.86 #ff9d54, stop:1 #ffdf8f)"
    ),
    # Dark glass chrome: sidebar / top bar / context panel.
    "DARK_PANEL_BG": (
        "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
        "stop:0 rgba(20, 14, 50, 210), stop:1 rgba(60, 20, 70, 175))"
    ),
    "DARK_PANEL_BORDER": "rgba(255, 255, 255, 0.25)",
    "TEXT_ON_DARK": "#FFFFFF",
    "TEXT_ON_DARK_MUTED": "rgba(255, 255, 255, 0.72)",
    "TEXT_ON_DARK_FAINT": "rgba(255, 255, 255, 0.5)",
    # Light glass cards.
    "CARD_BG": (
        "qlineargradient(x1:0, y1:0, x2:0.4, y2:1, "
        "stop:0 rgba(255, 255, 255, 224), stop:1 rgba(255, 255, 255, 148))"
    ),
    "CARD_BORDER": "rgba(255, 255, 255, 0.65)",
    "READINESS_CARD_BG": (
        "qlineargradient(x1:0, y1:0, x2:0.4, y2:1, "
        "stop:0 rgba(189, 243, 255, 232), stop:1 rgba(127, 231, 255, 130))"
    ),
    # Sidebar nav gel pills.
    "NAV_IDLE_BG": (
        "qradialgradient(cx:0.32, cy:0.28, radius:1.1, "
        "stop:0 rgba(255, 255, 255, 90), stop:0.6 rgba(255, 255, 255, 22), "
        "stop:1 rgba(255, 255, 255, 10))"
    ),
    "NAV_HOVER_BG": (
        "qradialgradient(cx:0.32, cy:0.28, radius:1.1, "
        "stop:0 rgba(255, 255, 255, 140), stop:0.6 rgba(255, 255, 255, 55), "
        "stop:1 rgba(255, 255, 255, 25))"
    ),
    "NAV_ACTIVE_BG": (
        "qradialgradient(cx:0.32, cy:0.28, radius:1.1, "
        "stop:0 #bdf3ff, stop:0.55 #22b8d6, stop:1 #0a7ea8)"
    ),
    "NAV_ACTIVE_TEXT": "#0a2a35",
    # Gel buttons / pills.
    "BTN_BG": (
        "qradialgradient(cx:0.32, cy:0.28, radius:1.1, "
        "stop:0 #bdf3ff, stop:0.55 #22b8d6, stop:1 #0a7ea8)"
    ),
    "BTN_HOVER_BG": (
        "qradialgradient(cx:0.32, cy:0.28, radius:1.1, "
        "stop:0 #d6f8ff, stop:0.55 #3fc9e6, stop:1 #0f95c2)"
    ),
    "BTN_TEXT": "#0a2a35",
    "BTN_DISABLED_BG": "rgba(255, 255, 255, 0.3)",
    "GHOST_BORDER": "#22B8D6",
    "GHOST_TEXT_ON_LIGHT": "#0a7ea8",
    "GHOST_TEXT_ON_DARK": "#bdf3ff",
    "GHOST_HOVER_BG": "rgba(127, 231, 255, 0.22)",
    # Inputs.
    "INPUT_BG": "rgba(255, 255, 255, 0.75)",
    "INPUT_BORDER": "rgba(58, 66, 88, 0.25)",
    "INPUT_FOCUS_BORDER": "#22B8D6",
    # Tabs (segmented pill control).
    "TAB_IDLE_BG": "rgba(255, 255, 255, 0.18)",
    "TAB_IDLE_TEXT": "#FFFFFF",
    "TAB_ACTIVE_BG": (
        "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
        "stop:0 #bdf3ff, stop:0.55 #22b8d6, stop:1 #0a7ea8)"
    ),
    "TAB_ACTIVE_TEXT": "#0a2a35",
    # Checkbox gel "track" (see module docstring: no sliding-knob animation).
    "CHECK_IDLE_BG": "rgba(58, 66, 88, 0.18)",
    "CHECK_CHECKED_BG": (
        "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7fe7ff, stop:1 #0a7ea8)"
    ),
    # Pills / badges.
    "PILL_BG": "rgba(127, 231, 255, 0.28)",
    "PILL_TEXT": "#0a4b5c",
    # List selection.
    "LIST_SELECTED_BG": "rgba(127, 231, 255, 0.35)",
    "SCROLL_CONTENT_BG": "transparent",
}

# Near-black on pure white -- 21:1 contrast, the maximum possible, vs. the
# default palette's body text at roughly 14:1 on a light glass card. Fully
# opaque throughout (see module docstring): the sunset/glass aesthetic is
# deliberately dropped here, not just re-tinted, because translucency and a
# photographic backdrop actively work against maximum legibility. The accent
# is a deep, saturated teal (still visually part of the aqua family) rather
# than the default palette's bright cyan, since the bright cyan is close to
# WCAG AA's 3:1 large-text/UI-component floor against white; this one clears
# it with real margin.
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
    "AQUA_BRIGHT": "#0B5566",
    "AQUA_MID": "#0B5566",
    "AQUA_DEEP": "#063942",
    "SUCCESS": "#1C7A3F",
    "SUCCESS_DEEP": "#0F4D28",
    "SUCCESS_TEXT": "#0F4D28",
    "DANGER": "#A8231A",
    "DANGER_DEEP": "#6E160F",
    "DANGER_TEXT": "#6E160F",
    "WARNING": "#8A5A00",
    "WARNING_DEEP": "#5C3C00",
    "WARNING_TEXT": "#5C3C00",
    "NEUTRAL": "#4D4D4D",
    "NEUTRAL_DEEP": "#333333",
    "NEUTRAL_TEXT": "#333333",
    "ROOT_BG": "#FFFFFF",
    "DARK_PANEL_BG": "#FFFFFF",
    "DARK_PANEL_BORDER": "#000000",
    "TEXT_ON_DARK": "#000000",
    "TEXT_ON_DARK_MUTED": "#333333",
    "TEXT_ON_DARK_FAINT": "#333333",
    "CARD_BG": "#FFFFFF",
    "CARD_BORDER": "#000000",
    "READINESS_CARD_BG": "#FFD9A0",
    "NAV_IDLE_BG": "transparent",
    "NAV_HOVER_BG": "#EDEDED",
    "NAV_ACTIVE_BG": "#0B5566",
    "NAV_ACTIVE_TEXT": "#FFFFFF",
    "BTN_BG": "#0B5566",
    "BTN_HOVER_BG": "#063942",
    "BTN_TEXT": "#FFFFFF",
    "BTN_DISABLED_BG": "#CCCCCC",
    "GHOST_BORDER": "#0B5566",
    "GHOST_TEXT_ON_LIGHT": "#0B5566",
    "GHOST_TEXT_ON_DARK": "#0B5566",
    "GHOST_HOVER_BG": "#E6F2F4",
    "INPUT_BG": "#FFFFFF",
    "INPUT_BORDER": "#000000",
    "INPUT_FOCUS_BORDER": "#0B5566",
    "TAB_IDLE_BG": "#EDEDED",
    "TAB_IDLE_TEXT": "#000000",
    "TAB_ACTIVE_BG": "#0B5566",
    "TAB_ACTIVE_TEXT": "#FFFFFF",
    "CHECK_IDLE_BG": "#FFFFFF",
    "CHECK_CHECKED_BG": "#0B5566",
    "PILL_BG": "#EDEDED",
    "PILL_TEXT": "#000000",
    "LIST_SELECTED_BG": "#FFD9A0",
    "SCROLL_CONTENT_BG": "#FFFFFF",
}

# Same glass/gradient shell as the default look (the aqua accent is already
# blue-leaning and reads fine under color vision deficiency) -- only the
# semantic status ramp changes, to the Okabe-Ito qualitative palette
# (Okabe & Ito, 2008), since red/green/amber status colors sitting side by
# side are exactly the case that palette exists to fix.
COLORBLIND_SAFE_PALETTE = {
    "CREAM": CREAM,
    "CREAM_PANEL": CREAM_PANEL,
    "SAFFRON": "#D55E00",
    "SAFFRON_DEEP": "#9C4500",
    "BROWN": "#1B1B1B",
    "BROWN_SOFT": "#4D4D4D",
    "BORDER": "rgba(27, 27, 27, 0.25)",
    "SIDEBAR": SIDEBAR,
    "SELECTED": "#0072B2",
    "AQUA_BRIGHT": "#56B4E9",
    "AQUA_MID": "#0072B2",
    "AQUA_DEEP": "#004C77",
    "SUCCESS": "#0072B2",
    "SUCCESS_DEEP": "#004C77",
    "SUCCESS_TEXT": "#004C77",
    "DANGER": "#D55E00",
    "DANGER_DEEP": "#9C4500",
    "DANGER_TEXT": "#9C4500",
    "WARNING": "#E69F00",
    "WARNING_DEEP": "#A87200",
    "WARNING_TEXT": "#7A5200",
    "NEUTRAL": "#C3CCDB",
    "NEUTRAL_DEEP": "#8F9AB0",
    "NEUTRAL_TEXT": "#4D4D4D",
    "ROOT_BG": DEFAULT_PALETTE["ROOT_BG"],
    "DARK_PANEL_BG": DEFAULT_PALETTE["DARK_PANEL_BG"],
    "DARK_PANEL_BORDER": DEFAULT_PALETTE["DARK_PANEL_BORDER"],
    "TEXT_ON_DARK": "#FFFFFF",
    "TEXT_ON_DARK_MUTED": "rgba(255, 255, 255, 0.75)",
    "TEXT_ON_DARK_FAINT": "rgba(255, 255, 255, 0.55)",
    "CARD_BG": DEFAULT_PALETTE["CARD_BG"],
    "CARD_BORDER": DEFAULT_PALETTE["CARD_BORDER"],
    "READINESS_CARD_BG": DEFAULT_PALETTE["READINESS_CARD_BG"],
    "NAV_IDLE_BG": DEFAULT_PALETTE["NAV_IDLE_BG"],
    "NAV_HOVER_BG": DEFAULT_PALETTE["NAV_HOVER_BG"],
    "NAV_ACTIVE_BG": (
        "qradialgradient(cx:0.32, cy:0.28, radius:1.1, "
        "stop:0 #cde9f7, stop:0.55 #0072B2, stop:1 #004C77)"
    ),
    "NAV_ACTIVE_TEXT": "#FFFFFF",
    "BTN_BG": (
        "qradialgradient(cx:0.32, cy:0.28, radius:1.1, "
        "stop:0 #cde9f7, stop:0.55 #0072B2, stop:1 #004C77)"
    ),
    "BTN_HOVER_BG": (
        "qradialgradient(cx:0.32, cy:0.28, radius:1.1, "
        "stop:0 #e3f2fb, stop:0.55 #1c86c4, stop:1 #005f92)"
    ),
    "BTN_TEXT": "#FFFFFF",
    "BTN_DISABLED_BG": "rgba(255, 255, 255, 0.3)",
    "GHOST_BORDER": "#0072B2",
    "GHOST_TEXT_ON_LIGHT": "#004C77",
    "GHOST_TEXT_ON_DARK": "#cde9f7",
    "GHOST_HOVER_BG": "rgba(0, 114, 178, 0.18)",
    "INPUT_BG": "rgba(255, 255, 255, 0.85)",
    "INPUT_BORDER": "rgba(27, 27, 27, 0.3)",
    "INPUT_FOCUS_BORDER": "#0072B2",
    "TAB_IDLE_BG": "rgba(255, 255, 255, 0.2)",
    "TAB_IDLE_TEXT": "#FFFFFF",
    "TAB_ACTIVE_BG": "#0072B2",
    "TAB_ACTIVE_TEXT": "#FFFFFF",
    "CHECK_IDLE_BG": "rgba(27, 27, 27, 0.2)",
    "CHECK_CHECKED_BG": "#0072B2",
    "PILL_BG": "rgba(0, 114, 178, 0.22)",
    "PILL_TEXT": "#004C77",
    "LIST_SELECTED_BG": "rgba(0, 114, 178, 0.3)",
    "SCROLL_CONTENT_BG": "transparent",
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

# Registered via QFontDatabase.addApplicationFont in app.main -- see
# ui/assets/fonts/. Falls back to the platform default sans if a font file
# is ever missing, so this theme still renders (just not bubbly) rather than
# erroring.
FONT_DISPLAY = '"Baloo 2"'
FONT_BODY = '"Nunito"'


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
    font-family: {FONT_BODY}, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: {font_size}px;
    color: {p["BROWN"]};
}}

QMainWindow, QWidget#Root {{
    background: {p["ROOT_BG"]};
}}

/* Dark glass chrome: sidebar / top bar / context panel. */
QFrame#Sidebar, QFrame#ContextPanel, QFrame#TopBar {{
    background: {p["DARK_PANEL_BG"]};
    border: 1px solid {p["DARK_PANEL_BORDER"]};
    border-radius: 20px;
}}
QFrame#Sidebar QLabel, QFrame#ContextPanel QLabel, QFrame#TopBar QLabel {{
    color: {p["TEXT_ON_DARK"]};
}}
QFrame#Sidebar QLabel#Muted, QFrame#ContextPanel QLabel#Muted, QFrame#TopBar QLabel#Muted {{
    color: {p["TEXT_ON_DARK_MUTED"]};
}}
QFrame#Sidebar QLabel#SectionTitle, QFrame#ContextPanel QLabel#SectionTitle,
QFrame#TopBar QLabel#SectionTitle {{
    color: {p["TEXT_ON_DARK_FAINT"]};
}}
QFrame#Sidebar QLabel#Tagline, QFrame#ContextPanel QLabel#Tagline {{
    color: {p["TEXT_ON_DARK_MUTED"]};
}}

/* Main workspace: still a glass panel, but content-column-flavored (lighter,
   larger radius) rather than dark chrome -- cards float on top of it. */
QFrame#Panel {{
    background: {p["CARD_BG"]};
    border: 1px solid {p["CARD_BORDER"]};
    border-radius: 22px;
}}

QDialog#Panel {{
    background: {p["CREAM_PANEL"]};
    border: 1px solid {p["CARD_BORDER"]};
    border-radius: 20px;
}}

/* Glass cards */
QFrame#Card {{
    background: {p["CARD_BG"]};
    border: 1px solid {p["CARD_BORDER"]};
    border-radius: 18px;
}}
QFrame#ReadinessCard {{
    background: {p["READINESS_CARD_BG"]};
    border: 1px solid {p["AQUA_MID"]};
    border-radius: 18px;
}}
QLabel#CardTitle {{
    font-family: {FONT_DISPLAY}, {FONT_BODY};
    font-size: {font_size + 3}px;
    font-weight: 700;
    color: {p["AQUA_DEEP"]};
}}
QLabel#ReadinessLabel {{
    font-family: {FONT_DISPLAY}, {FONT_BODY};
    font-size: {font_size + 6}px;
    font-weight: 700;
    color: {p["BROWN"]};
}}
/* Build-readiness state coloring (ui.widgets.readiness_badge sets the
   "state" dynamic property) -- a color-coded gel pill instead of plain
   text. */
QLabel#ReadinessLabel[state="good"] {{ color: {p["SUCCESS_TEXT"]}; }}
QLabel#ReadinessLabel[state="warn"] {{ color: {p["WARNING_TEXT"]}; }}
QLabel#ReadinessLabel[state="bad"] {{ color: {p["DANGER_TEXT"]}; }}
QLabel#ReadinessLabel[state="neutral"] {{ color: {p["NEUTRAL_TEXT"]}; }}

QLabel#Brand {{
    font-family: {FONT_DISPLAY}, {FONT_BODY};
    font-size: {font_size + 10}px;
    font-weight: 800;
    color: {p["TEXT_ON_DARK"]};
    padding: 6px 4px;
}}

QLabel#Tagline {{
    font-size: {max(font_size - 2, 10)}px;
    padding: 0 4px 8px 4px;
}}

QLabel#ScreenTitle {{
    font-family: {FONT_DISPLAY}, {FONT_BODY};
    font-size: {font_size + 8}px;
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

/* Sidebar navigation: bubbly gel pills (an "orb" recipe stretched to a
   pill footprint, since these carry text labels rather than being bare
   circular glyphs). */
QPushButton#NavButton {{
    text-align: left;
    padding: 11px 14px;
    border: none;
    border-radius: 14px;
    background: {p["NAV_IDLE_BG"]};
    font-size: {font_size}px;
    font-weight: 600;
    color: {p["TEXT_ON_DARK"]};
}}
QPushButton#NavButton:hover {{
    background: {p["NAV_HOVER_BG"]};
}}
QPushButton#NavButton:checked {{
    background: {p["NAV_ACTIVE_BG"]};
    color: {p["NAV_ACTIVE_TEXT"]};
    font-weight: 700;
}}

/* Primary gel buttons */
QPushButton {{
    background: {p["BTN_BG"]};
    color: {p["BTN_TEXT"]};
    border: none;
    border-radius: 14px;
    padding: 9px 18px;
    font-weight: 700;
}}
QPushButton:hover {{ background: {p["BTN_HOVER_BG"]}; }}
QPushButton:disabled {{ background: {p["BTN_DISABLED_BG"]}; color: {p["NEUTRAL_TEXT"]}; }}

QPushButton#Ghost {{
    background: transparent;
    color: {p["GHOST_TEXT_ON_LIGHT"]};
    border: 2px solid {p["GHOST_BORDER"]};
}}
QPushButton#Ghost:hover {{ background: {p["GHOST_HOVER_BG"]}; }}
QFrame#Sidebar QPushButton#Ghost, QFrame#ContextPanel QPushButton#Ghost,
QFrame#TopBar QPushButton#Ghost {{
    color: {p["GHOST_TEXT_ON_DARK"]};
}}

/* Notification bell orb (ui.notification_center.NotificationBell) */
QPushButton#BellButton {{
    background: {p["NAV_IDLE_BG"]};
    color: {p["TEXT_ON_DARK"]};
    border: none;
    border-radius: 18px;
    padding: 6px 10px;
    font-weight: 600;
}}
QPushButton#BellButton:hover {{ background: {p["NAV_HOVER_BG"]}; }}
QLabel#UnreadDot {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {p["SAFFRON"]}, stop:1 {p["SAFFRON_DEEP"]});
    border: 2px solid rgba(20, 14, 50, 0.65);
    border-radius: 6px;
}}

/* Inputs: glass pills */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {{
    background: {p["INPUT_BG"]};
    border: 1px solid {p["INPUT_BORDER"]};
    border-radius: 12px;
    padding: 8px 12px;
    selection-background-color: {p["AQUA_MID"]};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
    border: 2px solid {p["INPUT_FOCUS_BORDER"]};
}}

/* Segmented pill tabs (e.g. Testing screen's Functional/Performance/
   Accessibility/Build & Release/Economy tabs) -- generic QTabWidget/QTabBar
   selectors, so every screen using a stock QTabWidget gets this for free. */
QTabWidget::pane {{
    border: 1px solid {p["CARD_BORDER"]};
    border-radius: 16px;
    top: 6px;
}}
QTabBar::tab {{
    background: {p["TAB_IDLE_BG"]};
    color: {p["TAB_IDLE_TEXT"]};
    border: none;
    border-radius: 999px;
    padding: 8px 16px;
    margin: 2px 4px 2px 0;
    font-weight: 600;
}}
QTabBar::tab:selected {{
    background: {p["TAB_ACTIVE_BG"]};
    color: {p["TAB_ACTIVE_TEXT"]};
    font-weight: 700;
}}

/* Checkbox gel "track" -- see module docstring re: no sliding-knob
   animation. Covers every QCheckBox in the app (Solo/Team Mode, telemetry,
   Discord, Rapid Prototyping, and all four accessibility toggles) with no
   changes needed at any of those call sites. */
QCheckBox {{
    spacing: 10px;
    font-weight: 600;
}}
QCheckBox::indicator {{
    width: 40px;
    height: 22px;
    border-radius: 11px;
    background: {p["CHECK_IDLE_BG"]};
    border: 1px solid {p["CARD_BORDER"]};
}}
QCheckBox::indicator:checked {{
    background: {p["CHECK_CHECKED_BG"]};
    border: 1px solid {p["AQUA_DEEP"]};
}}

/* Usage / plan pill */
QLabel#UsagePill {{
    background: {p["PILL_BG"]};
    color: {p["PILL_TEXT"]};
    border-radius: 14px;
    padding: 8px 12px;
    font-size: {max(font_size - 2, 10)}px;
    font-weight: 700;
}}

QListWidget {{
    background: transparent;
    border: none;
}}
QListWidget::item {{
    padding: 8px;
    border-radius: 10px;
}}
QListWidget::item:selected {{
    background: {p["LIST_SELECTED_BG"]};
    color: {p["BROWN"]};
}}

/* Live Task Progress Transparency (Phase L): the appending plain-language
   step trail -- see ui.widgets.progress_trail.ProgressTrail. */
QListWidget#ProgressTrailList {{
    background: {p["CARD_BG"]};
    border: 1px solid {p["CARD_BORDER"]};
    border-radius: 12px;
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
   scroll content renders correctly regardless of the OS theme. Left
   transparent (rather than a flat fill) so the glass Panel it sits inside
   keeps bleeding the sunset backdrop through behind every card. */
QWidget#ScrollContent {{ background: {p["SCROLL_CONTENT_BG"]}; }}
"""


# Evaluated once at import time -- exactly the stylesheet this module has
# always exported, for callers that don't need a non-default variant.
STYLESHEET = build_stylesheet()
