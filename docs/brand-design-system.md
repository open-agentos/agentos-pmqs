# PMQs (Product Managers Questions)
### Brand & Design System — Draft 1 Visual Identity

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

## 2. Logo — "The Faceted Prism Q"

> **This section is open.** The per-facet bevel below is the priority refinement and is
> **not** present in the reference SVG.

### Concept

A ring built from many cut, faceted surfaces — like a cut gemstone — representing the
many angles a PM has to hold in view at once. At the classic Q tail position (lower
right), the facets stop closing the loop and instead taper outward into a short sequence
of shrinking facets, holding the ring's teal tones for most of their length and
resolving to gold only in the final one or two — clarity arriving late, and only once
earned.

**Embedded symbolism**: the tail is built from exactly eight facets — one for each of
PMQs' eight analytical lenses (competitive positioning, growth/adoption, unit economics,
risk, roadmap tradeoff, quality/reliability, org/execution, narrative/positioning). The
eight perspectives narrow to a single point of resolution. This is intentionally subtle
— it should read as a well-proportioned cut tail regardless of whether anyone clocks the
count.

### Construction notes (current state)

- Ring: ~11 faceted quadrilateral segments around a circle, cut from a narrow family of
  closely-related teal tones (soft contrast between adjacent facets — deliberately not
  high-contrast, to avoid a "busy" or harsh read).
- Tail: 8 tapering facets in the lower-right (classic Q) position, taper accelerates
  toward the tip, starts slightly underneath the ring (overlapping/emerging from it
  rather than merely touching its edge), colour holds teal through most of its length and
  resolves to gold only in the last 1–2 facets.
- A thin outer highlight/shadow rim was tried as a whole-shape bevel — **superseded by
  the note below.**
- A small cream centre point anchors the form.

### Open refinement — priority item for the design agent

The whole-shape outer rim bevel (single highlight arc + single shadow arc traced around
the outside) is the **wrong** approach and should be replaced. What's wanted instead:
**bevel embedded into each individual facet**, both its inner and outer edge, so every
segment reads as its own small cut gem surface catching light — not the silhouette as a
whole. Each facet should look dimensional on its own (e.g. a lighter edge along the side
facing the implied light source, a darker edge along the opposite side, per facet)
rather than relying on one rim treatment for the entire mark. Keep it subtle — visible,
not glossy or heavy-handed; this should still read as flat/clean at a distance and only
reveal the cut-gem depth on closer inspection.

### Other refinements to explore

- Confirm the tail's current length reads as confident and intentional, not clipped, now
  that it's been shortened from earlier drafts.
- Consider whether the ring's internal facet seams (currently soft strokes) are needed at
  all, or whether colour-shift alone between adjacent facets could carry the faceted read
  with even less visual noise.
- Facet irregularity: the ring is currently a uniform-angle cut. A hand-cut, slightly
  irregular facet arrangement may feel less mechanical without adding real complexity.
- Verify legibility and character survive at small sizes (app icon / favicon scale) —
  this is a more detailed mark than a typical scalable logo and needs a tested
  minimum-size fallback (likely a simplified silhouette or solid-fill version below
  ~24px).

### The resolve doesn't survive at UI scale — measured

This is the most important thing on this page and it is not a shading problem, so the
per-facet bevel will not fix it.

The tail's gold tip is **10.7 sq units of a 63504 viewBox — 0.017% of the mark.**
Rasterised against `--bg-main`, gold runs **1:740** against teal. In pixels of gold:

| render size | gold px² | |
|---|---|---|
| 16px (favicon) | 0.16 | invisible |
| 24px (Draft 1's stated minimum) | 0.35 | invisible |
| **30px (the left rail — the mark's main placement)** | **0.55** | **invisible** |
| 48px | 1.40 | invisible |
| 64px | 2.48 | a smudge |
| 128px | ~11 | first legible |

The facets are fine — all three ring tones are still distinguishable at 12px. Facet
detail was never what breaks. **What breaks is the resolve**, and the resolve is the
entire idea: *clarity arriving late, and only once earned*; eight lenses narrowing to one
point.

At every size PMQs actually renders this mark, it shows a teal ring with a teal tail and
no resolution at all.

**The cause is the taper, and it's structural.** §2 asks for gold in "the final one or
two facets" *and* for the taper to accelerate toward the tip. Those two together
guarantee that the facets carrying the meaning are the smallest ones on the mark. The
eight tail facets by area:

| facet | 1 | 2 | 3 | 4 | 5 | 6 | 7 (amber) | 8 (gold) |
|---|---|---|---|---|---|---|---|---|
| % of tail | 43.9 | 17.8 | 13.2 | 9.7 | 6.9 | 4.7 | 2.8 | **1.0** |

**This is the design question §2 should answer**, ahead of the bevel: either re-cut the
taper so the resolve has area at ~30px, or accept that the detailed mark is a hero/poster
asset and the product wears the simplified glyph. The fallback currently implements the
second, because it's the one that can be done without redesigning the mark.

If the taper is re-cut so gold survives at ~30px, lower `MIN_DETAIL_PX` in
`web/logo.py` and delete this section. `tests/test_logo.py` will tell you when that
happens — it asserts the detailed mark shows *zero* gold at 16px, and starts failing the
moment that stops being true.

### Known issues in the reference SVG

To be fixed when the mark is integrated as an asset:

- **Dead canvas.** `viewBox` is `0 0 680 520`, but the artwork occupies roughly x≈175–425,
  y≈135–480. Nearly half the canvas is empty — harmless in a document, actively harmful
  as an asset.
- **Baked-in text.** The `<text>` elements have hardcoded fill and no `font-family`, so
  they render in the SVG UA default rather than the type stack in §4.
- **Hardcoded fills.** Facet colours are literals rather than token references. Note the
  ring's teal ramp is genuinely many closely-related tones, not one token — tokenising
  it fully may not be desirable.
- **Degenerate tail polygon.** The final tail facet specifies a duplicated vertex
  (`411.3,371.3` twice), i.e. a quad that is really a triangle. It renders correctly;
  it's cosmetic, but it reads as a copy-paste error.

### Reference implementation (current best draft, as SVG)

This is the actual working geometry from the latest round — use it as a literal starting
point, not just a description.

```svg
<svg width="100%" viewBox="0 0 680 520" xmlns="http://www.w3.org/2000/svg">
<g stroke="#1a2226" stroke-width="0.5" stroke-opacity="0.25">
<polygon points="335.29,315.09 351.64,325.78 365.78,311.64 355.09,295.29" fill="#1f4d47"/>
<polygon points="351.64,325.78 360.93,331.53 371.53,320.93 365.78,311.64" fill="#24504a"/>
<polygon points="360.93,331.53 369.85,337.63 377.63,329.85 371.53,320.93" fill="#29544d"/>
<polygon points="369.85,337.63 378.42,344.08 384.08,338.42 377.63,329.85" fill="#2e5850"/>
<polygon points="378.42,344.08 386.78,350.74 390.74,346.78 384.08,338.42" fill="#345d53"/>
<polygon points="386.78,350.74 395.01,357.55 397.55,355.01 390.74,346.78" fill="#5f6d50"/>
<polygon points="395.01,357.55 403.08,364.50 404.50,363.08 397.55,355.01" fill="#a5894a"/>
<polygon points="403.08,364.50 411.3,371.3 411.3,371.3 404.50,363.08" fill="#dfb15b"/>
</g>
<g stroke="#1a2226" stroke-width="0.5" stroke-opacity="0.25">
<polygon points="425,260 408.25,322.5 364.95,297.5 375,260" fill="#1f4d47"/>
<polygon points="362.5,368.25 300,385 300,335 337.5,324.95" fill="#29564f"/>
<polygon points="300,385 237.5,368.25 262.5,324.95 300,335" fill="#355f57"/>
<polygon points="237.5,368.25 191.75,322.5 235.05,297.5 262.5,324.95" fill="#1f4d47"/>
<polygon points="191.75,322.5 175,260 225,260 235.05,297.5" fill="#29564f"/>
<polygon points="175,260 191.75,197.5 235.05,222.5 225,260" fill="#355f57"/>
<polygon points="191.75,197.5 237.5,151.75 262.5,195.05 235.05,222.5" fill="#1f4d47"/>
<polygon points="237.5,151.75 300,135 300,185 262.5,195.05" fill="#29564f"/>
<polygon points="300,135 362.5,151.75 337.5,195.05 300,185" fill="#355f57"/>
<polygon points="362.5,151.75 408.25,197.5 364.95,222.5 337.5,195.05" fill="#1f4d47"/>
<polygon points="408.25,197.5 425,260 375,260 364.95,222.5" fill="#29564f"/>
</g>
<circle cx="300" cy="260" r="6" fill="#f4efe6"/>
<text x="300" y="450" text-anchor="middle" font-size="42" font-weight="500" fill="#f4efe6" letter-spacing="-1">PMQs</text>
<text x="300" y="480" text-anchor="middle" font-size="14" fill="#9aa5a9" letter-spacing="1">PRODUCT MANAGERS QUESTIONS</text>
</svg>
```

*(Note: the outer rim bevel arcs from the previous round are intentionally omitted here —
see the refinement note above for the preferred replacement approach.)*

### Logo usage rules

- **Minimum size for the detailed mark: 64px.** Below that, `web/logo.py` returns the
  simplified glyph automatically (`assets/logo-fallback.svg`) — call sites don't choose.
  Draft 1 estimated 24px. Measured, that was wrong in both directions; see
  "The resolve doesn't survive" below.
- Clearspace: minimum 0.5× the mark's height on all sides.
- Don't: recolour onto a light/cream field, add drop shadows or glow beyond the embedded
  per-facet bevel, or pair the mark with any secondary icon in the same lockup.

---

## 3. Colour Tokens

```css
:root {
  /* Structure */
  --bg-main: #12181c;
  --bg-surface: #1a2226;
  --bg-active: #212b30;
  --border-default: #2e383d;
  --border-muted: #232b2f;

  /* Text */
  --text-primary: #f4efe6;
  --text-secondary: #9aa5a9;
  --text-muted: #5f6a6d;

  /* Structural accent (also the logo's ring family) — FILL ONLY, see below */
  --accent-teal: #1f4d47;

  /* Semantic */
  --accent-gold: #dfb15b;    /* resolution / primary action / logo tail resolve */
  --accent-sage: #8fae86;    /* success state only */
  --pulse-cyan: #38bdf8;     /* telemetry / info */
  --pulse-coral: #f87171;    /* risk / error */

  /* Document surface — the §3 exception. See "Warm paper" below. */
  --paper: #efe9dd;
  --paper-ink: #2a2620;
  --paper-muted: #6b6153;
}
```

| Token | Value | Use |
|---|---|---|
| `--bg-main` | `#12181c` | App background |
| `--bg-surface` | `#1a2226` | Panels, cards |
| `--text-primary` | `#f4efe6` | Body/heading text |
| `--accent-gold` | `#dfb15b` | Primary actions, active states, the logo's resolved point |
| `--accent-sage` | `#8fae86` | Success/confirmation states only |
| `--pulse-cyan` | `#38bdf8` | Telemetry, live status |
| `--pulse-coral` | `#f87171` | Errors, risk flags |
| `--paper` | `#efe9dd` | **Document surfaces only** — see below |

### Warm paper — the one background exception

Ivory-cream is a text/mark colour on all app chrome. **The single exception is the
document surface** (position documents, artifact panels), where warm paper is a
deliberate figure/ground inversion signalling *"this is a document, not UI."*

That inversion is the product's signature device: the dark-ink/warm-paper contrast is
what makes the war-room read as a document rather than a dashboard. Do not use cream as
a background on any other surface.

The document surface also carries its own typeface — see §4.

### Contrast constraints (measured, not estimated)

Ratios against `--bg-main` (`#12181c`):

| Token | Ratio | Verdict |
|---|---|---|
| `--text-primary` | 15.63:1 | ✅ AA |
| `--accent-gold` | 9.02:1 | ✅ AA |
| `--pulse-cyan` | 8.36:1 | ✅ AA |
| `--accent-sage` | 7.30:1 | ✅ AA |
| `--text-secondary` | 7.10:1 | ✅ AA |
| `--pulse-coral` | 6.47:1 | ✅ AA |
| `--text-muted` | 3.21:1 | ⚠️ AA-large only — acceptable for faint metadata, but use knowingly |
| `--accent-teal` | **1.88:1** | ❌ **fill only — never text or borders** |

**`--accent-teal` is not a foreground colour.** It is the logo's ring fill family. At
1.88:1 on `--bg-main` it is effectively invisible as text. Any foreground use needs a
lightened derivative that has been measured.

### Settled: hue does not carry type identity

The Outcomes ledger previously colour-coded by type (Issue / Policy / Document /
Meeting / Question) in teal / brass / violet / sky / grey. **That is retired.** Type
identity is carried by the word, and hue is reserved for state.

Four reasons, in order of weight:

**1. Hue was redundant.** The tag already renders the type as text
(`<span class="ledger-tag issue">Issue</span>`), as does the summary strip. The colour
was decoration on top of a label that already carried the fact unambiguously.

**2. Hue inflation.** In this system saturated hue means *"attend to this"* — gold is
resolution, coral is risk, cyan is live. That role language works because it is scarce.
Type is not a state needing attention; it's a neutral fact about a row, like a date.
Spending attention-grabbing colour on it teaches users that colour here is decorative,
and once they've learned that, the gold CTA stops meaning anything. Identity hues don't
merely fail to help — they devalue the semantic ones.

**3. The old set was not distinguishable anyway.** Machado et al. (2009) simulation,
ΔE2000 between the retired tag colours:

| Pair | Normal | Deuteranomaly | Protanomaly |
|---|---|---|---|
| violet vs sky | 18.3 | **4.4** | **6.5** |
| teal vs violet | 28.0 | **5.1** | **9.7** |
| teal vs sky | 15.3 | **8.6** | **10.0** |

ΔE2000 ≈ 2.3 is a just-noticeable difference between *adjacent* patches; 10px separated
tags need far more. Under deuteranomaly (~6% of men) teal, violet and sky collapse into
one another — five categories become two groups. Even on normal vision, sky vs grey is
ΔE 11.5. It was weak for everyone and broken for roughly 1 in 12 men.

Extending the palette instead would have required five hues mutually separable under
both deuteranomaly and protanomaly, at 10px, on a near-black background, in a muted
register, *after* gold/cyan/coral/sage are reserved. That gamut is empty. Any set that
satisfied the constraint would be saturated enough to wreck §1's voice.

**4. Brand fit.** A five-hue ledger reads as a task board. Outcomes is a register of work
product — closer to a bound logbook. The PM should feel they produced things, not that
they have tickets. Colour arrives when something is genuinely resolved, which is the same
idea as §2's tail: clarity arriving late, and only once earned.

> *A note on colour psychology, since it tends to get invoked here:* most of it —
> "violet feels creative," "blue builds trust" — is weakly replicated and culturally
> contingent, and no decision in this system rests on it. What is well-supported is
> **salience** (saturation and contrast draw the eye, largely independent of hue) and
> **semantic consistency** (a colour meaning one thing is processed faster than one
> meaning three). Both point the same way.

**What this means in practice:**

- All `.ledger-tag.*` variants share one neutral treatment; the word carries the type.
- Summary-strip numbers are `--text-primary`, not per-type hues.
- `--violet` and `--sky` (and their `-dim` variants) are **deleted** from the palette.
- Hue on a ledger row is free to express genuine state: an Issue pending its push to
  GitHub is a pending action → `--accent-gold`; once pushed → `--accent-sage`; risk →
  `--pulse-coral`.

Facet-derived glyphs (§5) may be explored **only** if word-scanning measurably drags in
a long ledger. A glyph beside the word is a second redundancy on the same fact — it must
earn its place with evidence, not inherit it from the colour removed here. Default to
not building it.

**Don't**: use `--accent-sage` or `--accent-teal` as a page background; don't introduce
ivory-cream as a background on any surface other than the document surface; don't
reintroduce identity hues.

---

## 4. Typography

> **Amended from Draft 1.** The original specified **Aeonik** for headers. Aeonik is a
> commercial typeface from CoType and PMQs holds no licence for it, so it cannot ship.
> Substituted with **DM Sans** — the closest free match to Aeonik's construction (a
> geometric skeleton with neo-grotesque detailing), already available on Google Fonts,
> so no self-hosting or static asset serving is required.
>
> Candidates considered and rejected: **Inter** (often cited as the closest match, but
> it's already the body face — using it for headers too would collapse the header/body
> distinction this section draws, and it's a neo-grotesque, not geometric); **Geist**
> (thematically apt for a dark developer-tool palette, but not on Google Fonts and loses
> Aeonik's geometry); **Space Grotesk** (geometric, but idiosyncratic in a way that
> fights §1's "rigorous, not quirky" voice).

| Role | Stack | Weight | Notes |
|---|---|---|---|
| Display / headers | `'DM Sans', system-ui, sans-serif` | 600–700 | Tracking tuned per size — see below |
| Body copy | `'Inter', system-ui, sans-serif` | 400 | |
| Monospace / telemetry | `'IBM Plex Mono', SFMono-Regular, Consolas, monospace` | 400 | Tracking 0.05em |
| **Document surface** | `'Source Serif 4', Georgia, serif` | 500–700 | The paper panel (§3 exception) |

Available as tokens: `--font-display`, `--font-body`, `--font-mono`, `--font-doc`.

**The serif is not optional.** Draft 1 omitted it, but `Source Serif 4` is what sets the
document surface. Since the paper panel stays (§3), the serif is part of the system and
is documented here rather than left as an undeclared dependency.

### Tracking must be tuned, not inherited

Draft 1 specified `-0.03em` / `-0.01em`. Those figures were tuned to Aeonik's
sidebearings and do **not** transfer to DM Sans. Tracking is set per-element by eye at
real sizes.

### Header roles map to these components

Draft 1's table named "App Title (2.0rem)" and "Section Headers (H2, 1.3rem)". Neither
exists in the product as such — the app has no `h1`/`h2` chrome, and the Inbox's section
header was deliberately removed during design. The display face applies to:

| Element | Size | Role |
|---|---|---|
| `.logo` | 20px | App title (until the §2 lockup replaces it) |
| `.inbox-header` | 26px | Inbox view title |
| `.outcomes-header` | 26px | Outcomes view title |

⚠️ `h1`/`h2`/`h3` **stay on the serif.** The only heading element in the template is the
`<h3>` inside the `.doc` paper panel. Applying the display face to `h1,h2,h3` would flip
the document heading to sans and break the very surface §3's exception exists to protect.

Sizes above are the layout's real values. Draft 1's 2.0rem/1.3rem figures describe a
hierarchy the product doesn't have; if a larger display scale is wanted, that's a design
change, not a typography migration.

---

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
