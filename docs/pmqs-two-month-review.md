# PMQs at Scale: A Two-Month Review

*Written from the perspective of a VP of Product whose organization — a large consumer tech company (think Spotify/Google) or a PM-strong B2B company (think Stripe/Cursor) — has had every PM on PMQs for two months.*

---

## Assumptions

PMQs is configured and working as designed through Phase 4: each PM has their products connected to the AgentOS repo substrate, watchlists/keywords/media sources feeding news ingestion, a fresh time-boxed batch of lens-generated questions in the inbox each morning, the war room and on-demand position documents available, and all five outcome types (Issue, Policy, Document, Meeting, Question) recording to the ledger. I assume single-PM private deployments — no team features, no manager visibility — which matches the product's stated scope. I evaluate against two org archetypes because they stress the product differently: a consumer org where decision evidence lives mostly in analytics, experiments, and research; and an engineering-led B2B org where a large share of it genuinely lives in repos.

One further assumption I'll test rather than grant: PMQs' founding premise that decision-making weight on PMs is increasing and PMs are becoming more powerful in the org.

---

## Are my PMs making better decisions?

**Yes, in a specific and observable way: decisions have become explicit events.** The single biggest behavioral change after two months is not speed or volume — it's that things which used to drift ambiently ("we should probably look at churn in that cohort someday") now arrive as named questions with an evidence pointer, get a session, and leave a typed outcome. Before PMQs, most of my PMs' decisions were never *made* so much as *accreted*. The inbox converts ambient signal into decision moments, and the outcomes ledger makes the decision itself an artifact. That alone is a real contribution to PM practice, and it's one no tool in the current landscape attempts.

**The floor rises more than the ceiling.** Position documents are the mechanism. The California-Voter-Guide format — plain summary, consequence framing, neutral background, argument-for and argument-against each with rebuttal — is quietly radical, because the document most PMs produce before a decision is a PRD-shaped justification of the choice they've already made. Forcing a structured *against* raises the preparation quality of my median PM substantially. My best PMs already interrogate themselves this way; for them PMQs saves time rather than changing behavior. That's fine — VPs are hired to raise medians.

**But I cannot yet tell whether the decisions are *good*.** The ledger counts outcomes produced, which is the right metric versus inbox-zero — the design is explicit and correct that success is outcomes, not clearing. Two months in, though, I can see activity, not accuracy. Nothing in PMQs asks, six weeks later, "you decided X expecting Y — did Y happen?" This is the product's most important missing piece, and it's the one most aligned with its own spirit: the gym doesn't just make you lift, it tracks whether you got stronger.

---

## Where behavior actually lands after two months

**The inbox habit stands or falls on precision, and precision depends on where the evidence lives.** The daily time-boxed batch is the right design — the insight that PMs silently ignore rather than dismiss, so a bounded regeneration beats an accumulating queue, is exactly right and I've watched it play out. At the Cursor/Stripe archetype, structural repo triggers (stale issues, label conflicts, cost/error deltas) are rich and cheap, hit rates are high, and the morning inbox check is a genuine habit by week three. At the Spotify/Google archetype, the picture is weaker: repos and Actions telemetry are a thin slice of what drives consumer PM decisions. Experiments, funnels, research, and support signal live in Amplitude, internal experiment platforms, and research repositories. There, the interpretive news lens carries too much of the load, precision drops, and by week six a meaningful fraction of PMs treat the inbox as one more unread digest. The design documents anticipate this exact failure mode (the drift-toward-LLM-triggers watch item); the product doesn't yet instrument it. You can't currently see per-lens hit rates, so you can't see the decay until the habit is dead.

**The war room is episodic, and that's correct — the risk is substitution, not frequency.** Realistic cadence is one or two sessions per PM per week, clustered around planning reviews, exec asks, and incidents. That's healthy: war rooms are for decisions, and PMs don't make big decisions daily. The real threat is the other tab. Every PM already has ChatGPT or Claude open, with memory, with connectors, with zero switching cost. PMQs' war room wins only when its context advantage — receipts into real issues/PRs/runs, the scoped lens pass, standing Policies, the history of prior outcomes — is *felt within the first minute* of a session. When it is, the session is categorically better than a general assistant. When the substrate is thin (consumer archetype again), the general assistant wins on convenience and the war room goes quiet. On-demand-only position documents are the right economics; nobody resents the cost of a report they asked for.

**Outcomes is the best design decision in the product.** Measuring what PMs *produce* — Issues, Policies, Documents, Meetings — is what I actually review them on. Two risks appear at scale. First, outcome theater: the moment managers can see ledgers, PMs will manufacture outcomes; the current PM-private scoping protects against this, and I'd defend it. Second, the missing follow-through loop above — an outcome log without a "did it hold?" check is a diary, not a record of judgment.

**Policies are the sleeper primitive.** Durable, private, free-form standing rules fed to agents as context is exactly where the PM role is heading — the shift from operating AI systems to governing them. Two months in, my strongest PMs have accumulated a dozen Policies each, and those Policies are doing real work shaping agent behavior and war-room reasoning. This is the feature that will look obvious in three years.

---

## Is the founding thesis true?

**Directionally yes, with a twist that matters for the roadmap.** The evidence from the field supports increasing decision weight: as engineering throughput explodes with AI, product judgment — not code — becomes the bottleneck (the framing Anthropic's own product leadership has used publicly); PMs report making more decisions per unit of time as execution work compresses; PM hiring has recovered strongly but concentrated at senior and leadership levels, with orgs betting on fewer, more experienced PMs covering more surface area; and industry surveys put strategy and business acumen at the top of the skills PMs say matter next.

The twist: the weight is increasing *per PM*, but the power is concentrating in *fewer* PMs, and the role's boundaries are blurring — LinkedIn replacing its APM program with a generalist "Product Builder" program is the emblematic example. So PMQs' target persona is right: the concentrated-judgment PM accountable for an enormous surface area, increasingly including fleets of agents. But PMQs' evidence assumption — that this PM's decisions are grounded in repos plus news — matches only a subset of that accountability surface today. The trend that most favors PMQs is that as agents do more of the building, the repo genuinely becomes the org's nervous system, and PMQs is early to that world. At AgentOS-native shops that world is *now*; at Spotify it's two to three years out. The strategic conclusion: PMQs' wedge is AI-native, agent-run engineering orgs, and its expansion path for everyone else runs through opening the evidence layer.

---

## Competitive insights

The 2026 landscape is organized in lanes, none of which occupy PMQs' position. Feedback synthesis (Productboard with its Spark agent, Zeda.io, Enterpret, Dovetail) aggregates and themes customer signal. Analytics intelligence (Pendo's Novus, Amplitude/Mixpanel AI) surfaces product-usage patterns. AI-moderated discovery (Perspective AI, CleverX) scales the customer conversation itself. Drafting tools (ChatPRD) accelerate documents. Meeting capture (Granola) recovers decisions from calls. Execution platforms (Linear, Jira Product Discovery with Rovo) manage delivery. And general assistants (ChatGPT, Claude, Claude Code) are the actual default tool of 96% of working PMs.

Three observations follow:

**Nobody owns the decision layer.** Every lane above is either upstream evidence-gathering or downstream execution. PMQs' interrogative posture — the system asks the PM questions, rather than waiting to be prompted — is genuinely differentiated; everything else in the market is reactive. The closest conceptual neighbors are Pendo Novus ("continuous product intelligence") and Productboard Spark, both proactive-ish, but both anchored to their own data silos, neither decision-native, neither structurally adversarial, and neither with a typed outcomes record. The for/against/rebuttal position document and the outcomes ledger have no competitor equivalent.

**The real competitive threat is the general assistant, not the PM tool.** Memory, connectors, and scheduled tasks in ChatGPT/Claude can approximate a morning question digest today, and that convergence will continue. PMQs' defensibility is the closed loop the assistants don't have — question → session → typed outcome → Policy → better questions — plus the AgentOS substrate underneath. The loop compounds: every outcome and Policy makes the next batch of questions smarter. Protect and deepen the loop; don't compete on chat.

**Category confusion is a positioning risk.** Without deliberate framing, PMQs gets shelved next to ChatPRD as "another AI PM assistant." The positioning that matches both the product's spirit and the market gap is *decision system of record*: your PRD tool drafts, your analytics tool reports — PMQs makes sure the decision got made, on evidence, against the strongest counterargument, and then checks whether it held.

---

## Prioritized feature list

**P0 — trust and the loop** (these determine whether the habit survives month three)

1. **Outcome follow-through** — expected-result field and revisit-by date on every outcome; auto-generates a scheduled inbox question ("you decided X expecting Y — did Y happen?"). Turns the ledger into a record of judgment quality.
2. **Third evidence class** — read-only connectors (MCP-based) for analytics, experiments, and feedback signal, feeding the existing lens machinery alongside repos and news.
3. **Inbox relevance capture** — instrument act/save/open/ignore per question and per lens. Manual weights stay; the signal must exist before anything can learn from it.
4. **Per-lens precision telemetry** — make the interpretive-trigger-drift watch item visible instead of latent.

**P1 — habit and reach**

5. **Morning digest delivery** (email/Slack) deep-linking into the inbox — reach the PM before the other tab opens.
6. **Decision memo export** — one PM-controlled shareable artifact per decision (position-doc summary plus outcome); the pressure-release for stakeholder visibility without building a reporting surface.
7. **PMQs as an MCP server** — expose questions, outcomes, and Policies to the PM's general assistant; converts the substitution threat into distribution.
8. **Suggested lens weights from behavior** — suggest, never auto-apply; a safe pull-forward of the deferred inference phase.
9. **Quick-triage inbox** (mobile/lite) for corridor-and-commute usage.

**P2 — already logged or later**

10. **Agent Debate mode** — as logged; the synthesis-layer candidate once the loop is instrumented.
11. **Opt-in shared Policy spaces** — the first careful step beyond the single-PM loop.
12. **State-of-the-Product view** grown organically from the ledger — as already scoped; revisit once follow-through data gives it something honest to report.

---

## Verdict

PMQs is pointed at the right hill. The scarcest resource in a 2026 product org is not information, drafting capacity, or even engineering throughput — it is judgment under load, and PMQs is the only product I've seen that treats the *decision* as the unit of work. After two months, it demonstrably makes decisions explicit, better-evidenced, and adversarially tested where the substrate is rich, and its Policies primitive anticipates the governing-not-operating shape of the role better than anything on the market. Whether it catalyzes better PM behavior *at scale* comes down to two moves: close the outcome loop, so the tool measures whether judgment held rather than whether activity occurred; and open the evidence layer, so the lenses see what consumer and B2B PMs are actually accountable for. Both moves deepen the original intent — rigorous, not adversarial; a thinktank, not a fight; the gym that also tracks whether you got stronger — rather than diluting it into another dashboard.
