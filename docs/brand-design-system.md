# PMQs (Product Managers Questions)
### Brand & Design System — Parchment Visual Identity (light default; dark theme available)

*Source of truth for brand voice, the logo concept and its reference implementation,
colour/type tokens, and the backlog of open refinements.*

**Status:** Draft 1 — directionally confirmed, not finished.
**Still open:** §2 (the logo) — specifically the per-facet bevel.
**Settled:** §1, §3, §4, §5, §6.

> **Implementers:** before changing `pmqs/pmqs/web/templates/app.html`, read
> `pmqs/pmqs/web/TEMPLATE-CONTRACT.md`. That file is production code — `render.py`
> splices data into it with regex anchored on its markup. Colours, fonts and spacing
> are free to change; class names and structure are not, and the tests will not tell
> you if you break them.

---

## 1. Brand Voice & Philosophy

PMQs is a single-PM decision instrument built on a GitHub-primitives substrate. It is
**not** a public-facing debate stage, and it is **not** combative.

The right frame: **the gym, the viva with your professor, the private counseling
session, the thinktank.** Rigorous, demanding, in service of making the PM sharper and
their direction clearer — never a fight, never adversarial theater.

The people it's for are multi-faceted, lateral thinkers — PMs who hold many perspectives
at once and coordinate across wildly different disciplines. The visual identity should
carry that complexity, not flatten it away.

The core idea, stated plainly: **clarity comes from having fully thought something
through — not from stripping complexity away.** (Closer to a hardcore-Zen framing of
clarity through complete understanding than to minimalism-as-clarity.) Every part of
this system should be judged against that idea: does it show genuine depth resolving
into a clear point, or does it just look simple?

**Do not**: use literal parliamentary/debate props (gavels, shields, scrolls), make the
mark feel adversarial or combative, or over-flatten the logo into a bare geometric glyph
— an earlier minimalist pass (a plain ring sliced by an arrow) was rejected specifically
for reading as too simple and, incidentally, as an unrelated symbol.

---

## 2. Logo — "The Quill/A"

### Concept

The mark is an amber tile carrying a light **quill/A**: the letter A drawn as a
nib, an apex point above it like the tip of a pen. It reads as *authoring* — a PM
writing the decision down — which is what the product is for. It replaces the
Draft‑1 "Faceted Prism Q". This is a faithful first pass adapted from the
parchment mock and is explicitly **to be revisited**; the rules below are the
ones worth holding while it is.

### Construction

- **Box.** `viewBox="0 0 28 28"`, square. A rounded tile, `rect rx="8"`, filled
  with `--accent-gold`. Both variants share the viewBox so they are drop‑in
  swappable.
- **Glyph.** The A is two stroked paths (the apex `M6 22 L14 6 l8 16` and the
  crossbar `M9 17 h10`) in `--on-accent`, plus, in the detailed variant, a small
  apex point (`circle id="apex"`). Round caps and joins.
- **Two variants, chosen by size — not at the call site.** `web/logo.py`
  switches below `MIN_DETAIL_PX` (64px): the detailed mark keeps the apex point
  and 2.2 strokes; the simplified glyph drops the point and thickens strokes to
  2.8 so the A holds its shape in a 16–32px tab. The rail draws at 30px, so it
  gets the simplified glyph deliberately. The favicon is always the simplified
  glyph.

### Colours

Literal hex, not `var()`, because the mark is also served standalone as a
favicon, where custom properties have no document to resolve against. Two values
are tokens and must track section 3 — `tests/test_logo.py` pins both:

- tile = `--accent-gold` `#95500f`
- glyph = `--on-accent` `#fdf6e9`

### Logo usage rules

- Keep the tile square; never stretch it.
- Don't drop the glyph below legible contrast against the tile.
- One mark per lockup — don't pair it with a second icon.
- The amber tile carries its own field, so it sits correctly on the light
  parchment canvas **and** on the dark theme without recolouring.

---

## 3. Colour Tokens

**Light parchment is the default identity.** Dark is a secondary theme — the same
type system and the same token *names*, re‑skinned to dark values under
`html[data-theme="dark"]` in the template, toggled from the rail and remembered
in `localStorage`. This section documents the **default (light)** palette, which
is what the drift guard pins; the dark skin is intentionally not gated.

Ratios below are stated **per surface**. The single hardest lesson from the last
two identities: a token picked by role/name and measured against one background
fails once the component it lands on sits on a *different* surface. On a warm
palette that bites harder — muted tans read fine to the eye and still miss AA. So
every foreground is measured against each surface it actually renders on, and
`tests/test_contrast.py` enforces it.

```css
:root{
  /* Structure — warm parchment: canvas -> card -> active -> raised */
  --bg-main:#f8f0dc;
  --bg-surface:#fefcf4;
  --bg-active:#ede0c4;
  --bg-raised:#e0cfb0;
  --border-default:#d6c09a;   /* soft hairline, decorative (not gated to 3:1) */
  --border-muted:#e8d9bc;

  /* Text — warm ink */
  --text-primary:#231409;     /* 11.7–17.4 across the four surfaces */
  --text-secondary:#6b4728;   /*  5.4– 8.0 */
  --text-muted:#8a6238;       /*  3.5– 5.3 — AA-large on the deep surfaces; faint metadata, used knowingly */

  /* Structural / interactive accent — warm ink family. On light, the
     interactive signal is weight + underline, not a second hue, so -fg
     shares the secondary ink; -dim is the structural border. */
  --accent-teal:#e7d3ac;      /* FILL only — subtle warm tan (system avatar) */
  --accent-teal-fg:#6b4728;   /*  5.4– 8.0 — interactive text */
  --accent-teal-dim:#c2a878;  /*  soft structural border */

  /* Resolution / primary action — burnt amber. Deepened from the mock's
     #b05e10 so it clears AA (4.5) as text on the mid surfaces too. */
  --accent-gold:#95500f;      /*  4.7– 5.4 as text (canvas/card/active/paper) */
  --accent-gold-dim:#a86414;  /*  border derivative */
  --on-accent:#fdf6e9;        /*  near-white text ON an accent fill — 6+ on --accent-gold */

  /* Semantic status — warm-adjusted, each clears 4.5 as text on card/paper */
  --accent-sage:#2e6b3c;      /*  4.2– 6.2 — success only */
  --pulse-cyan:#2a5880;       /*  4.9– 7.3 — telemetry / live status */
  --pulse-coral:#9c3220;      /*  4.8– 7.1 — risk / error */
  --pulse-coral-dim:#c05a42;  /*  border derivative */

  /* Document surface — "the letter" (see below) */
  --paper:#f4e6c8;
  --paper-ink:#2a1a09;        /* 13–16 on --paper */
  --paper-muted:#7a5630;      /*  ~5 on --paper */
}
```

### The fourth surface

The product has four structural levels — canvas, card, active row, and the
chips/controls that sit **on** an active row (`--bg-raised`). Contrast for any
foreground is measured against whichever of these it actually lands on, not
against the canvas alone.

### `--on-accent`, and why it's a token

Primary actions (record & stage, save, send) are amber fills with near‑white
labels. That label colour can't be `--bg-main`: on the light theme the canvas is
cream, so cream‑on‑amber fails. `--on-accent` is the inverse‑text token — near
white on light, dark on the dark skin — so one rule reads correctly in both
themes.

### Two deliberate deviations from the mock

- The mock's signature amber `#b05e10` fails AA (4.5) as **text** on the mid
  surfaces (~3.6:1 on the active row). It's used as text — active nav, the top
  rank badge, the stakes pill — so it's deepened to `#95500f`. Buttons put
  `--on-accent` on it, not cream.
- The mock's muted tan (~`#9e7558`) fails everywhere as text; `--text-muted` is
  darkened to `#8a6238`, AA‑large on the deep surfaces, matching the prior
  identity's "faint metadata, used knowingly" intent.

### Warm paper — the letter

`--paper` is a deeper, warmer parchment than the card, read in the serif doc
face. It is deliberately distinct from `--bg-surface`: the position document is a
crafted reading surface — a letter — not another UI panel. `--paper-ink` /
`--paper-muted` are its text tones.

---

## 4. Typography

The identity is set in three families. Loaded from Google Fonts in the template's
`@import`.

- `--font-display` — **Fraunces** (a soft, high‑contrast serif). Headers are
  **serif** on this identity: the inbox/settings titles, detail titles and
  section headers.
- `--font-body` — **Plus Jakarta Sans**. UI text, labels, controls, metadata.
- `--font-mono` — **Geist Mono**. Numerals, scores, telemetry, the rail metrics.
- `--font-doc` — **Fraunces**. The document ("letter") surface; also the generic
  `h1`–`h3` face.

```css
--font-display:'Fraunces', ui-serif, Georgia, serif;
--font-body:'Plus Jakarta Sans', ui-sans-serif, system-ui, sans-serif;
--font-mono:'Geist Mono', ui-monospace, SFMono-Regular, monospace;
--font-doc:'Fraunces', ui-serif, Georgia, serif;
```

This identity has no unlicensed face: the Draft‑1 header face has been dropped
entirely in favour of Fraunces, so there is nothing to substitute for.

### Header roles map to these components

`--font-display` (Fraunces) is used specifically on `.logo`, `.detail-title`,
`.inbox-header`, `.settings-header` and `.set-section h2`; generic `h1`–`h3` fall
to `--font-doc` (also Fraunces). Tracking figures from Draft 1 were tuned to a
different face and must be re‑checked against Fraunces at each size rather than
inherited.


## 5. Iconography

No literal debate props. Any icon system should be derived from the logo's own vocabulary
— cut facets, angled strokes, a single resolving point — so icons read as siblings of the
mark, not a separate illustration layer. Build only as-needed per UI surface; don't
pre-populate a large decorative set.

*(Note: facet-derived glyphs were considered as a carrier for outcome-type identity and
deliberately **not** adopted — see §3. The type is already carried by its text label; a
glyph would be a second redundancy on the same fact. Explore only with evidence that
word-scanning is too slow.)*

---

## 6. Component Patterns

⚠️ These specify **properties, not selectors.** Class names in `app.html` are
load-bearing — `render.py` anchors on them and no test catches breakage. See
`pmqs/pmqs/web/TEMPLATE-CONTRACT.md`. Do not rename an existing class to match a name
below; apply the properties to the component that plays the role.

### What Draft 1 named vs. what exists

| Draft 1 | Real component | Status |
|---|---|---|
| `.tab-item.active` | `.a-tab.active` (artifact pane tabs) | ✅ applied |
| `.pulse-metric-row` | `.metric-row` (left rail) | ✅ applied |
| `.pulse-metric-value` | `.metric-row span:last-child` | ✅ applied |
| `.war-room-container` | — **nothing** | ⚠️ see below |

```css
/* the artifact pane's tab strip */
.a-tab              { border-bottom: 2px solid transparent; }  /* reserves the space */
.a-tab.active       { color: var(--accent-gold); border-bottom-color: var(--accent-gold);
                      font-weight: 600; background: var(--bg-surface); }

/* the left rail's ambient telemetry */
.metric-row                 { font-family: var(--font-mono); font-size: 0.8rem;
                              color: var(--text-secondary); }
.metric-row span:last-child { color: var(--text-primary); font-weight: bold; }
```

### `.war-room-container` describes a component that doesn't exist

Draft 1 specifies it as a card: `background-color: var(--bg-surface)`, `border-radius: 8px`,
`padding: 24px`, `box-shadow: 0 4px 24px rgba(0,0,0,0.5)`.

**The war room is not a card.** It's a full-bleed two-pane layout — `.ws-wrap` is
`display:flex; height:100%`, splitting into a conversation pane and an artifact pane that
fill the viewport. There is no padded, rounded, shadowed container anywhere in it, and
adding one would box the whole workspace: less room for the thing the workspace is for,
and a drop shadow on a full-height pane that has nothing to cast onto.

Nothing else fits either. The card-like surfaces in the war room are `.evidence-item` and
`.proposed-item` — list items, where 24px padding and a heavy shadow would be wrong — and
`.doc`, which is the **paper** surface and takes `--paper`, not `--bg-surface`.

So this rule is unapplied, deliberately. It's the same defect as §4's header hierarchy one
section over: **Draft 1's component patterns were written against an imagined inventory
rather than the built product.** If a war-room card is genuinely wanted, that's a design
change with a real cost, not a token migration.

### Left-rail metrics are static

An animated pulse was judged distracting; the left-column metrics concept stays. Verified:
there is no `@keyframes` and no `animation:` property anywhere in the template. The
sparkline is a static path.

### Known: the active tab now carries four emphasis signals

Applying §6 faithfully gives `.a-tab.active` gold text **and** bold weight **and** a gold
underline **and** a lighter background. That's heavier than it needs to be — the
background is the most likely one to drop, since the underline is what §6 actually asks
for. Left as specified rather than quietly overruled; a call for the design agent.

## 7. Handoff Notes for Design Agent

Priority order for polishing:

1. **Per-facet embedded bevel** (§2) — the single highest-priority refinement. Each facet
   in both the ring and tail should carry its own subtle inner/outer edge treatment so it
   reads as an individual cut gem surface, not a flat colour patch under one whole-shape
   rim.
2. Validate tail proportions at full size and re-check confidence vs. clipped feeling.
3. Explore removing internal ring seams in favour of colour-shift-only faceting.
4. Introduce slight facet irregularity for a hand-cut (not lathed) feel.
5. ~~Design and test a simplified fallback glyph~~ — done; `assets/logo-fallback.svg`,
   minimum established empirically at 64px. But see "The resolve doesn't survive": the
   glyph is a workaround for a taper problem, and re-cutting the taper is the better fix.
6. Once the mark is finalised, extend the embedded-bevel treatment (if it works) to
   relevant UI surfaces (cards, active states) for visual consistency between brand mark
   and product chrome — exploratory, not a requirement.

§1, §3, §4, §5 and §6 are settled and should not be redesigned. §2 is open — the
per-facet bevel is the whole of the remaining brief.

---
*PMQs Brand & Design System — Draft 1 Visual Identity*
