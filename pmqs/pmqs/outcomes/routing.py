"""routing.py — where an outcome can be sent, per type (Wave 3: route to daily tools).

The ledger used to be a near dead end: an Issue linked to GitHub, a Document/Meeting had
an .md export, and everything else routed nowhere. This module is the single seam that
answers "where can this go?" for every outcome, and it is deliberately honest about which
destinations work today vs. which are stubs awaiting a per-customer connection.

Two classes of destination:
  - LIVE  (available=True): needs no credentials, works right now.
      copy      — the outcome as Markdown, onto the clipboard (any type)
      download  — the same Markdown as a .md file (any type)
      open      — the Markdown inline in a new tab (any type)
      github    — the tracker URL, for a pushed Issue
      gcal      — a Google Calendar event-template deep link for a Meeting (no auth: the
                  PM lands in Calendar with the title/agenda prefilled and picks a time)
  - STUB  (available=False): needs an OAuth app / webhook / API token per customer, which
      is real integration work. Rendered as a visible-but-disabled affordance with a hint,
      so the PM sees the intent ("this can go to Slack") before the wiring lands. Flip
      `available` and populate `url`/an action here when the integration is built — the UI
      and tests read this function, so nothing else has to change.

Pure function, no DB or I/O — takes the outcome fields, returns descriptors.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode


@dataclass(frozen=True)
class Destination:
    key: str            # 'copy'|'download'|'open'|'github'|'gcal'|'slack'|'notion'|'jira'
    label: str          # what the button says
    kind: str           # 'copy' | 'download' | 'link' | 'stub'  (how the client acts)
    url: str | None = None
    available: bool = True
    hint: str | None = None  # tooltip — why a stub is disabled / what it needs


# Stubs, declared once so their copy stays consistent wherever they appear.
def _stub(key: str, label: str, tool: str) -> Destination:
    return Destination(
        key=key, label=label, kind="stub", available=False,
        hint=f"{tool} routing isn't connected yet — coming soon",
    )


def gcal_template_link(title: str, details: str = "") -> str:
    """A Google Calendar event-creation deep link. No auth: opens Calendar's new-event
    form with the fields prefilled. The PM sets the time there (PMQS meetings don't carry
    a firm time). This is a genuine working link, not a stub."""
    q = urlencode({
        "action": "TEMPLATE",
        "text": (title or "Meeting").strip(),
        "details": (details or "").strip(),
    })
    return f"https://calendar.google.com/calendar/render?{q}"


def _export_url(outcome_id: str, *, download: bool = False) -> str:
    base = f"/outcomes/{outcome_id}/export.md"
    return base + ("?download=1" if download else "")


def destinations_for(outcome: Any, payload: dict[str, Any]) -> list[Destination]:
    """The ordered list of destinations for one outcome (most useful first).

    `outcome` needs .id, .type, and (for issue) .github_ref. `payload` is the decoded
    outcome payload (title/body/agenda/text/calendar_link as applicable).
    """
    otype = outcome.type
    oid = outcome.id
    title = (payload.get("title") or "").strip()

    copy = Destination("copy", "Copy as Markdown", "copy", url=_export_url(oid))
    download = Destination("download", "Download .md", "download", url=_export_url(oid, download=True))
    open_tab = Destination("open", "Open in tab", "link", url=_export_url(oid))

    if otype == "issue":
        ref = getattr(outcome, "github_ref", None)
        github = Destination(
            "github", "View on GitHub", "link", url=ref,
            available=bool(ref),
            hint=None if ref else "Raise the issue to GitHub first",
        )
        return [github, copy, _stub("jira", "Send to Jira", "Jira")]

    if otype == "meeting":
        agenda = (payload.get("agenda") or "").strip()
        gcal = Destination(
            "gcal", "Add to Google Calendar", "link",
            url=gcal_template_link(title, agenda),
        )
        dests = [gcal]
        pasted = (payload.get("calendar_link") or "").strip()
        if pasted:
            dests.append(Destination("event", "Open event", "link", url=pasted))
        dests += [copy, download, _stub("slack", "Share to Slack", "Slack")]
        return dests

    if otype == "document":
        return [copy, download, open_tab,
                _stub("notion", "Send to Notion", "Notion"),
                _stub("slack", "Share to Slack", "Slack")]

    if otype == "policy":
        # Policy is private (never GitHub); copy/download are local to the PM, fine.
        return [copy, download, _stub("notion", "Send to Notion", "Notion")]

    if otype == "question":
        return [copy, download, _stub("slack", "Share to Slack", "Slack")]

    return [copy]
