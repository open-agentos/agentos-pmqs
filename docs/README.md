# PMQs docs

| Document | Status |
|---|---|
| [`product-design.md`](product-design.md) | **Living** — the product/UX design record |
| [`brand-design-system.md`](brand-design-system.md) | **Living** — brand voice, logo, colour/type tokens |
| [`architecture.md`](architecture.md) | **Living** |
| [`how-to-use-pmqs.md`](how-to-use-pmqs.md) | Stub |
| `build-spec-phase-0-1.md` | **Historical** |
| `build-spec-phase-2.md` | **Historical** |
| `build-spec-phase-3.md` | **Historical** |
| `build-spec-phase-4.md` | **Historical** |
| `build-spec-polish.md` | **Historical** |

**Historical** documents are a record of what was true when a phase was built. They are
not maintained and will drift from the code — that's expected. Don't "correct" them; if
something in one is wrong *today*, the fix belongs in a living document.

---

## Where did `pmqs-mockup.html` go?

→ **`pmqs/pmqs/web/templates/app.html`**

It was never really a mockup by the end. `pmqs/pmqs/web/render.py` splices real data into
it at request time, so the app cannot serve a single page without it — it was production
code living in a documentation folder, which invited exactly the wrong instinct about
whether it was safe to edit.

Before changing it, read [`../pmqs/pmqs/web/TEMPLATE-CONTRACT.md`](../pmqs/pmqs/web/TEMPLATE-CONTRACT.md).
Its class names, `id`s, `data-*` attributes, comment sentinels and nesting depth are a
load-bearing API, and **no test asserts on any of them** — you can break rendering and
still get a green CI run.
