# Design system

The look is **"ink and signal"**: a cool-paper canvas, deep-ink bands where the page needs weight,
and one bright lime "signal" that only ever appears on ink. Actions on light surfaces are
ultramarine. Everything is driven by tokens, so a restyle is a change to two files, not sixty.

* Tokens: [`frontend/src/styles/tokens.css`](../frontend/src/styles/tokens.css)
* Global building blocks: [`frontend/src/styles/base.css`](../frontend/src/styles/base.css)
* To go back to the previous design: `git switch --detach ui-baseline-2` (tag; see the README).

## Principles

1. **Use the screen.** Pages run up to `--page-w` (1240px), not a 700px column. Where a page has
   little to say, it gets something useful to say (the course map beside a course) rather than
   white space.
2. **Weight comes from contrast, not boxes.** A dark band, a white sheet, a tinted canvas. Cards are
   used where a thing genuinely is a unit (a course, a lesson sheet, a table); lists are one panel
   with hairlines, not a pile of boxes.
3. **Show progress as a shape.** Ring/bar/large numerals, never only "4 of 9" in grey text.
4. **One loud thing per screen.** Lime on ink (the hero call to action) or ultramarine on light.

## Surfaces

| Class | What it is |
|---|---|
| (default) | the canvas (`--canvas`); white (`--bg`) is something lifted off it |
| `.ink` | a **dark region**. Re-points the semantic tokens (`--text`, `--border`, `--bg`, `--accent` → lime, `--on-accent`…), so anything inside adapts without knowing |
| `.band` | the hero treatment: ink, two soft light sources and a faint dot grid. Use with `.ink` |
| `.light` | the way **back** to light inside a dark region. Every popover/menu panel carries it, so a menu is always a light surface floating above whatever it opened from |
| `.page` | centres content at `--page-w` with `--page-pad` gutters |

The header is `.ink`; heroes are `ink band`.

## Colour

Never write a colour in a component stylesheet; use the semantic tokens. For text on an accent
fill use `var(--on-accent, #fff)`, not `#fff`: on ink the accent is lime and white text on it is
unreadable (this was a real bug in the notification badge).

`--control-border` is the edge of an input (3.5:1 on white). `--border-strong` is for quiet dividers
and is **too faint to be the only thing marking a field**.

Contrast (computed, WCAG 2.x): body text 12.5:1; muted text 6.4:1 on white / 5.6:1 on canvas; links
and primary buttons 7.1:1; lime on ink 15:1; dark-region muted text 8.6:1 (5.1:1 on the glass
panels). Status colours on their tints all pass 4.5:1.

## Type

* Display: **Bricolage Grotesque** (headings, numerals, buttons' emphasis) via `--font-display`;
  `h1`–`h4` use it automatically.
* Body: **Instrument Sans**. Code and the Studio markdown editor: **JetBrains Mono**.
* All three are **self-hosted** (`@fontsource-variable/*`, imported in `src/index.css`), so the app
  makes no request to a font service and works offline/behind a proxy. Only the subsets a page
  needs are downloaded.
* Scale: `--fs-11 … --fs-60`. Big numerals use the `.num` class (tabular, tight).

## Depth, shape, space

* Three real elevations: `--shadow-1` (resting), `--shadow-2` (raised: sheets, hovered tiles),
  `--shadow-pop` (menus, dialogs). Radii: `--radius` 8 (controls), `--radius-lg` 14 (panels),
  `--radius-xl` 22 (heroes, dialogs).
* Spacing tokens exist **only** for 1, 2, 3, 4, 5, 6, 8, 10, 12, 16, 20 (`--sp-N`, ×4px). `--sp-7`,
  `--sp-9`, `--sp-14` do not exist and silently collapse to nothing.
* Motion is short and purposeful, and is switched off entirely under `prefers-reduced-motion`.

## Page patterns

* **Hero band** (home, course, progress, login): ink band, display title, one call to action, a
  glass panel of the few numbers that matter.
* **Sheet** (lesson): a white, softly lifted page on the canvas, centred when there is no "In this
  lesson" rail.
* **Console** (admin, Studio): white sticky rail + `AdminPage` frame (eyebrow, display title, hint,
  actions) + white table panels. Every console screen gets this from `AdminPage`.

## Gotchas

* CSS Modules rewrite class names. A global helper class inside a module selector needs
  `:global`, e.g. `.stats :global(.num)`; plain `.stats .num` silently matches nothing.
* A new `Popover` panel is light automatically; don't style it dark.
* Screenshots in the desktop app's browser pane can lag one repaint; a mouse move before a capture
  forces it. Use a tall viewport to see a whole page without scrolling.
