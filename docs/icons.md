# Icons: Frutiger Aqua glyph recipe

This documents the recipe `src/spiced/ui/widgets/nav_icons.py` implements
for the sidebar's 14 nav glyphs. It didn't exist as a real file before this
pass -- two code comments referenced it as if it did, but there was nothing
behind them. This is the doc future icon work should extend, not the
broader Frutiger Aero direction (see `ui/theme.py`'s module docstring and
`design_handoff_spiced_frutiger_aqua/README.md` for that).

## Frutiger Aqua vs. Frutiger Aero

Frutiger Aero is the umbrella early-2000s aesthetic (sunset gradients,
glass panels, bubbly rounded type -- what `ui/theme.py` implements at the
shell level). Frutiger Aqua is more specific: it's Mac OS X's water-droplet
metaphor specifically (Apple's Aqua UI, first shipped 2000-2001) -- a
saturated glass "gumdrop" with a strong specular highlight near the top,
simulating an overhead light source shining through liquid, not just
generic shininess. That distinction is what this recipe is built around:
every icon glyph is a small glass object with a light source, not a flat
shape with a gradient slapped on.

## The Glossy Orb Recipe token

The design handoff's core reusable token, already implemented as QSS for
button/nav chrome in `ui/theme.py` (`NAV_IDLE_BG`/`NAV_ACTIVE_BG`/etc.):

```
radial-gradient(circle at 32% 28%, <light>, <mid> 55%, <dark> 100%)
```

The highlight center sits at 32%/28% into the shape -- upper-left, not
centered -- because that's where an overhead-and-slightly-left light source
would put it. This pass applies the same token to icon *glyphs themselves*
(`nav_icons._glass_gradient`), which QSS chrome could never reach.

## The glyph recipe

Every icon is built from two Python-level primitives in `nav_icons.py`:

- **`_paint_body`** -- the full treatment, for an icon's main silhouette:
  1. A soft drop shadow: the same path filled with `QColor(20, 20, 30, 70)`,
     offset by `(0, 1.3)` logical units in the icon's 24x24 coordinate
     space (`_SHADOW_OFFSET`). No blur pass -- at 44px display size a crisp
     low-alpha offset silhouette already reads as "soft shadow," and a real
     multi-pass blur would cost more than it buys here (see `ui/theme.py`'s
     own precedent of applying `QGraphicsDropShadowEffect` only where a
     real blur is cheap to get, e.g. whole panels, not small painted
     glyphs).
  2. The Glossy Orb Recipe fill (`_glass_gradient`): a `QRadialGradient`
     centered at 32%/28% of the shape's bounding box, stops at
     `base.lighter(185)` → `base` (55%) → `base.darker(165)`.
  3. A 1.1px bevel rim stroke in `base.darker(170)`, for edge definition
     against whatever sits behind the icon.
  4. A glass highlight cap: a vertical `QLinearGradient` (white, alpha 190
     → 0) clipped to the shape, covering the top ~42% of its bounding box
     -- the "light through glass" cue that's the whole point of Aqua.
- **`_paint_accent`** -- for secondary filled details that should look
  *recessed into* the body rather than floating above it (a door, a liquid
  level, a handle disc, a ferrule band): no shadow, no highlight cap, just
  a subtler top-to-bottom gradient (`base.darker(115)` → `base.darker(150)`)
  and a thin rim.

Thin non-filled details (handles, gear teeth, sound-wave arcs) stay plain
strokes via `_accent_pen`, one shade darker than the body
(`base.darker(135)`) so they read as engraved rather than pasted on top.

## Color derivation -- procedural, not a second palette

Every gradient/highlight/shadow stop above is derived from the *single*
base `QColor` each glyph function already receives (`c`, resolved from
`NavOrbButton.set_glyph_colors(idle_hex, active_hex)`, itself driven by
`ui.theme.resolve_palette` -- idle/active/colorblind-safe tinting). Nothing
in `nav_icons.py` hardcodes a second color ramp. This is a deliberate
constraint: accessibility palette swaps (colorblind-safe in particular)
have to keep working automatically, and that's only guaranteed if every
visual layer traces back to the one hex the theme system hands the glyph.

The one exception is the Testing beaker's liquid fill and the Art brush's
bristle tip, which use a fixed warm amber accent (`#FFC876` → `#C97E1A`,
`#FFB347` → `#C97E1A`) instead of deriving from the base color -- these are
meant to read as a distinct physical material (liquid, paint) rather than
part of the glass vessel/handle itself, matching the design handoff's own
example ("a beaker with a glass-highlight gradient and an *amber liquid*
gradient"). Both fall back to a flat `_paint_accent` under high-contrast,
same as every other secondary detail.

## High-contrast fallback

`ui/theme.py` is explicit that high-contrast mode drops the glass/gradient
aesthetic everywhere in the app -- opaque flat panels, no translucency,
because legibility wins over atmosphere in that mode. Icon glyphs follow
the same rule: `_paint_body`/`_paint_accent` both take a `high_contrast`
flag and, when set, skip the shadow/gradient/highlight layers entirely and
just fill the shape flat (`base` for body shapes, `base.darker(130)` for
accents). This is driven by `NavOrbButton.set_glyph_colors(..., high_contrast=...)`,
set from `MainWindow._apply_nav_glyph_colors` alongside the existing
idle/active hex resolution -- one extra bool threaded through, no new
per-mode color table.

## Scope

This recipe covers the 14 real sidebar nav items only
(`nav_icons._GLYPHS`). The design handoff's separate 6-icon "Icon Pack"
reference screen (status dots, action chips) was never built as a real
Spiced page and stays out of scope -- there's no dedicated icon-asset
surface for it to live on; today those states render as colored-text
`QLabel` badges (`StatusDot`/`ChecklistStatus`/`StatusPill` in
`ui/theme.py`), not icon glyphs.

## Adding a 15th icon

1. Identify the shape(s) that read as the icon's main "physical object" --
   that's your `_paint_body` call(s).
2. Anything that should look inset/recessed (not the primary silhouette)
   goes through `_paint_accent`.
3. Thin structural details (handles, arcs, teeth) stay `_accent_pen`
   strokes.
4. Add the function to `_GLYPHS` with the `(p: QPainter, c: QColor, hc: bool) -> None`
   signature -- every glyph must accept and honor the high-contrast flag.
5. Render `nav_icons._GLYPHS` at a few sizes/colors before merging (see the
   contact-sheet approach used to review this pass) -- there's no live-GUI
   check in this dev environment, so an offscreen render is the only way to
   actually see it before it ships.
