# Adopting the "Parchment" visual identity — build spec

**Repo:** `open-agentos/agentos-pmqs`
**Scope:** **visual identity only** — palette, typography, logo, ornament. **No IA change, no new views, no new data.**
**Status:** ⚠️ **Blocked on Matt's answers in §1 — do not start building until those are filled in.**
**Suggested model:** Claude Sonnet, one issue per run.
**Related:** `docs/figma-design-adoption.md` (the *structural* study, already shipped), `docs/brand-design-system.md` (the identity this spec replaces), `pmqs/pmqs/web/TEMPLATE-CONTRACT.md`.

---

## 0. Read this first — what this actually is

A second Figma Make exploration (React/Vite/Tailwind) was produced. Like the first one, **it is not being ported.** It is a source of one decision: a new look.

The important thing to understand before you touch anything:

- The **structural** ideas from the *first* study (two-pane Inbox, conversational thread rail, for/against grid, rank badges, shared source card) **already shipped** — PRs #112–#116, merged 17 Jul. `docs/figma-design-adoption.md` records that work. This spec does **not** revisit any of it.
- What is new in this upload is a **brand identity**: a light, warm *parchment* system — burnt-amber accent on cream, Fraunces serif headings, decorative flourishes. It is the inverse of what ships today: the dark "Draft 1" identity (`--bg-main:#12181c`, teal/gold/sage, DM Sans), documented in `docs/brand-design-system.md` and guarded in CI.
- The first study's spec said, in as many words: *"Cream + violet + Fraunces — deferred brand decision. Do not touch tokens."* **This spec is Matt taking up that deferred decision.** (The accent has evolved from violet to burnt amber since; everything else is the same pivot.)

So the mental model is: **re-skin every existing surface, change nothing about what those surfaces are or do.** The React file is a colour/type reference, not a component library. You will not write any React. You will change the design tokens in one template's `:root`, the brand doc that documents them, the font import, and the logo — and every `var(--…)` reference in the product re-tints automatically.

**This is a large, consequential change.** It overwrites an identity that was deliberately built, argued through (#21–#29, #26, #46, #50), and is pinned by two drift-guard test suites. Treat it with the same care those suites imply.

---

## 1. ⚠️ Open questions — Matt, please answer inline before this is handed off

The mechanical re-tint is small and safe. The *decisions* below are neither, and they gate the build. Please answer each; the executing agent should refuse to start until they're filled in.

### Q1 — Confirm the full pivot (vs. borrowing touches)

This spec assumes you want to **replace** the dark Draft-1 identity with the parchment one wholesale. The alternative is to keep dark and only borrow a few flourishes (the ✦ ornament, serif headings, softer cards). Full pivot is a much bigger change and un-does deliberate earlier work.

> **Full pivot / borrow touches only / something else:** ___________

### Q2 — Dark → light: replace, or keep dark as a toggle?

The parchment palette is a **light** theme; today's is dark. This isn't a re-tint, it's a polarity inversion — every one of the 26 tokens flips. Your framing ("unique in the face of dark-space SaaS") reads as *replace*, but replacing outright removes the dark option entirely, which some users prefer and which is the current default.

> **Replace outright / ship both with a toggle (default = ?):** ___________

### Q3 — The logo

The parchment mock ships a **different mark** — a small amber "quill/A" triangle. The product's mark is the **Faceted Prism Q**, with real history: the sub-pixel gold-taper problem, `MIN_DETAIL_PX` fallback, and `tests/test_logo.py` pinning 8 tail / 11 ring facets and "zero gold at 16px". Two clean paths:

- **(a) Keep the Q, recolour it** into the parchment hues (amber where gold was, ink where teal was). Cheapest; preserves the logo work and most of `test_logo.py`; keeps the "8 lenses → one point of resolution" meaning that matches the product thesis. **Recommended.**
- **(b) Replace it** with the quill/A mark. Discards the Q, the §2 saga, and requires rewriting `test_logo.py` and brand-doc §2 wholesale. The quill/A is charming but generic and carries none of the 8-lens meaning.

> **(a) recolour the Q / (b) replace with quill-A / discuss:** ___________

### Q4 — What is the document surface in a light world?

Today the position-document surface (`--paper:#efe9dd`) is *the one warm-paper exception* to a dark UI (brand doc §3) — it earns its warmth by contrasting against dark chrome. In an all-parchment UI there is no dark chrome, so that rationale evaporates. The doc surface should probably become the near-white card (`--parch-1:#fefcf4`) sitting on the canvas (`--parch-0:#f8f0dc`), but this is a call: keeping a slightly *deeper* paper for the reading surface may still be worth it for focus.

> **Near-white card / a distinct deeper paper / no distinction:** ___________

### Q5 — The sparkline (smaller, but worth a word)

The mock puts an animated-looking sparkline in the left rail. On record you wanted **left-rail metrics static/non-animated** ("an earlier animated pulse was distracting") and PULSE metric **data** is parked ("we'll address that later"). So: keep the sparkline only as a **static, decorative** ornament with no live data wiring, or drop it?

> **Static ornament only / drop it / wire it up now (overrides the parked decision):** ___________

---

## 2. What does NOT change — port the look, keep the IA

The mock's information architecture is a **subset** of the product and, in two places, *invents* things the product doesn't have. None of this changes. This is the same trap the first study's spec caught; the table is reproduced and extended.

| The mock shows | The reality — keep it |
|---|---|
| A static repo block in the rail | The **product switcher** shipped in #51–#57. Keep it; just re-tint it. |
| `Workspaces` with **Discussion / Options / Related** tabs | The five artifact tabs are **Position document / Evidence / Impacts / Proposed questions / Draft**. Keep them. |
| A lettered **"Option A/B/C"** model with risk/effort | PMQs has **no options model** — the position doc is for/against on one question. Do not invent one. |
| A free-text **"Record a decision"** box | The **five outcome types** (Issue / Policy / Document / Meeting / Question) and the `.outcome-bar` are the product thesis. Keep the bar. |
| No **session indicator** | Keep `.session-stats` (`_STATS_RE` anchors on it). |
| No **quick-add** | Keep it. |
| **critical / high / medium / low** severity | Keep the multi-dimensional `score_dims` model and the Urgent / Asked-by-you / System-raised / Saved axis. |
| No news / lens concepts | Out of scope here entirely. |
| Inline `style={{…}}` off a JS `T` object | The product renders a **server-spliced HTML template using `var(--…)`**. Do not introduce inline styles or React. |
| Fonts hotlinked from `static.figma.com/…` | **Never** ship those URLs. Fraunces, Plus Jakarta Sans and Geist Mono are all on Google Fonts — swap them into the existing `@import`. |
| `Sidebar` calls `setState` during render (a real bug in the mock) | Do not copy it. It's dead/buggy code. |

If a change you're about to make alters *what a surface is or does* rather than *how it looks*, stop — it's out of scope.

---

## 3. Where the work actually lands

The template is cleanly tokenised: **26 tokens in `:root`**, and the body uses `var(--…)` throughout (a grep for stray hex outside `:root` finds only issue refs like `#115`). That's the good news — re-tinting is mostly swapping the token block. The cost is concentrated in four coupled places that must move **in lockstep**, or CI goes red:

1. **`pmqs/pmqs/web/templates/app.html` `:root`** — the 26 colour tokens + 4 font tokens + the `@import` line (template lines ~6–60).
2. **`docs/brand-design-system.md`** — §2 (logo), §3 (colour), §4 (typography), §5 (iconography), §7 (handoff). `tests/test_brand_doc.py` asserts *every* `:root` colour token appears in §3 **with a matching hex** and every font token in §4, and that no `Aeonik` stack remains. Change a token without changing §3 → red.
3. **`tests/test_brand_doc.py` and a new contrast guard** — see §4 below.
4. **The logo socket** — `pmqs/pmqs/web/assets/logo-mark.svg` + `logo-fallback.svg`, `pmqs/pmqs/web/logo.py`, and `tests/test_logo.py`, scaled to the Q3 answer.

The token mapping (light-world target, for reference — final values are the design agent's to tune to pass §4's contrast gate):

| Role today (dark) | → parchment target |
|---|---|
| `--bg-main #12181c` | canvas `#f8f0dc` |
| `--bg-surface / -active / -raised` | `#fefcf4` / `#ede0c4` / `#e0cfb0` |
| `--border-default / -muted` | `#d6c09a` / `#e8d9bc` |
| `--text-primary / -secondary / -muted` | ink `#231409` / `#6b4728` / `#9e7558` *(see §4 — muted-as-text is the risk)* |
| `--accent-teal` family (structural) | ink-brown family |
| `--accent-gold` (resolution / primary action) | burnt amber `#b05e10` / soft `#c87528` |
| `--accent-sage` (success) | `#2e6b3c` |
| `--pulse-cyan / -coral` (telemetry / risk) | `#2a5880` / `#9c3220` |
| `--paper / -ink / -muted` | per **Q4** |
| `--font-display` DM Sans (sans) | **Fraunces (serif)** — headers become serif; §4 header-role mapping flips |
| `--font-body` Inter | Plus Jakarta Sans |
| `--font-mono` IBM Plex Mono | Geist Mono |
| `--font-doc` Source Serif 4 | per **Q4** (likely Fraunces) |

---

## 4. The contrast gate — this is the real risk, read it twice

Every contrast ratio documented in brand-doc §3 today is measured **against the dark `--bg-main`**. The moment the canvas goes light, **all of those numbers are void.** More importantly: the last adoption found a *systemic* bug — 4 of 5 issues hit it — where tokens were chosen by role/name **without checking which surface the component actually sits on**. On a light palette this bites harder, because muted warm tones read fine to the eye and still fail AA:

- `--text-muted #9e7558` and the mock's lighter tan `#c4a882` used **as body text** on `#f8f0dc` / `#fefcf4` are the prime suspects — verify, don't assume.
- The mock's **8px priority glyphs** (`⬥ ◆ ◇ ◻`) are decorative but sit next to text; check they aren't the only signal.
- Tinted chips render label text on a `color`+`16` (≈6% alpha) wash — check the *label* colour against the resulting surface, not against white.
- The amber `--accent-*` as **active-nav text** and as button labels on light backgrounds.

**Gate (blocking, every relevant token):**

1. Re-derive AA for **each foreground token against each surface it is actually used on** — not against a single background. The for/against grid lives on the doc surface; avatars on their own tint; nav text on the rail. Measure the real pair.
2. Rewrite §3 to document ratios **per surface**, with the pairing named. (This is also the standing recommendation left open from the first adoption — "restate the documented ratios per-surface so the next spec author doesn't repeat the Draft-1 mistake." Do it now.)
3. Add `tests/test_contrast.py` (or extend `test_brand_doc.py`) that asserts every foreground/surface pair the product actually renders clears **AA (4.5:1 body, 3:1 large/UI)**, computed from the shipped `:root` — so a future retune that breaks a pair fails CI.

A pretty palette that fails AA is not shippable. Budget real time here.

---

## 5. Waves

### Wave 0 — Decision gate
Matt answers §1. Nothing below starts until Q1–Q4 are answered (Q5 is non-blocking).

### Wave 1 — Palette + typography + brand-doc §3/§4 + fonts (one issue, atomic)
Because the `:root` block, brand-doc §3/§4, the drift guard and the new contrast guard are coupled, they move together in one commit-series.

- Swap the 26 colour tokens and 4 font tokens in `app.html` `:root` to the parchment set (final hexes tuned to pass §4).
- Replace the Google-Fonts `@import` with Fraunces + Plus Jakarta Sans + Geist Mono (correct weights/opsz). Flip the header face to the serif; re-map §4's header roles accordingly.
- Rewrite brand-doc §3 (per-surface ratios, §4 fonts). Delete the dark-only rationale for `--paper`; document the Q4 decision.
- `test_brand_doc.py` green; new contrast guard green.
- **Verify in a browser** — load `/`, a real workspace, `/outcomes`, `/settings`; confirm real data renders (a page showing fixture text is a broken splice, not a pass).

**Done when:** the app renders in parchment end-to-end, every documented ratio is per-surface and clears AA, no fixture leak, both guards green.

### Wave 2 — Logo (per Q3)
- **(a) recolour:** edit the two SVGs' hue family to amber/ink; keep 8 tail / 11 ring facets, the square viewBox, and the variant-swap; update the `test_logo.py` colour-parity assertions and the "zero gold at 16px" assertion to the new resolve colour; regenerate the favicon.
- **(b) replace:** new mark + fallback sharing a viewBox; rewrite `test_logo.py` and brand-doc §2 to describe the new mark's invariants; wire `logo.py` (`MIN_DETAIL_PX`, favicon, lockup).
- **Verify** the rail lockup and favicon at real size.

### Wave 3 — Character flourishes (CSS on existing markup only, no new token beyond Wave 1)
The genuinely-new-and-worth-keeping touches, each applied to existing markup, each a small issue:
- The ✦ section ornament on existing section headers.
- Serif treatment already handled in Wave 1 — just confirm heading hierarchy reads well.
- Warmer card shadows / borders on existing `.card`, source card, artifact panes.
- The rail **sparkline only if Q5 says so, and only as static decoration** — no live PULSE data wiring (that's parked).

Each Wave-3 item must introduce **zero new colour tokens** — if it seems to need one, it belongs back in Wave 1's palette, not bolted on.

---

## 6. Repo conventions & verification (non-negotiable)

- **Every PR: `base=main` with a non-empty `closingIssuesReferences`.** This repo's intake loops on PRs that have no linked issue — one stacked PR once spawned stub issues #33–#43, and a PR with no issue behind it spawned #49. Verify the GraphQL `closingIssuesReferences` field is non-empty before trusting it. **Never** open a stacked PR (`base != main`) — GitHub only registers `Closes #N` against the default branch.
- File the implementation issues **unlabeled/inert** (Matt triages; `status:*` labels dispatch the agents).
- **Read `TEMPLATE-CONTRACT.md` in full before editing `app.html`.** `render.py` splices real data with regex matched against the markup, and **no test asserts on the splice** — a broken splice serves fixture data with CI green. This wave is CSS/token-heavy and *shouldn't* move anchors, but if you touch structure at all, change both sides in one commit, prefer sentinels to `</div>` counting, and update the contract.
- `python -m pytest` is **necessary but not sufficient.** For anything touching `app.html`, also load the four surfaces in a browser and confirm real data appears.
- Smallest change that satisfies the issue; no unrelated refactors.

---

## 7. One housekeeping note for Matt (not part of the build)

You pasted a live GitHub PAT into the chat to give me repo access. It's now in the conversation transcript and shell history. Please **revoke it** once this is handed off (or now, and mint a fresh short-lived one for the executing agent). Ideally, hand secrets to agents out-of-band rather than in chat. Not a criticism — just close the loop on it.
