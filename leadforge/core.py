"""LEADFORGE core engine: a lightweight CRM pipeline with email sequences.

Pure standard-library. The engine persists to a single JSON file so the same
state can be driven from the CLI or over MCP. All business logic (stage
transitions, sequence scheduling, due-step computation, pipeline metrics) lives
here so it is testable without any I/O harness.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

TOOL_NAME = "leadforge"
TOOL_VERSION = "1.0.0"

# Ordered sales pipeline. Movement is validated against this ordering.
STAGES: List[str] = ["new", "contacted", "qualified", "proposal", "won", "lost"]
OPEN_STAGES = {"new", "contacted", "qualified", "proposal"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class LeadForgeError(Exception):
    """Domain error surfaced to the CLI as a non-zero exit."""


@dataclass
class Lead:
    id: str
    name: str
    email: str
    company: str = ""
    value: float = 0.0
    stage: str = "new"
    sequence: Optional[str] = None
    seq_step: int = 0
    next_due: Optional[str] = None
    created: str = field(default_factory=lambda: _iso(_now()))
    history: List[Dict[str, Any]] = field(default_factory=list)


# Built-in cold-outreach cadence. Offsets are days from enrollment.
DEFAULT_SEQUENCES: Dict[str, List[Dict[str, Any]]] = {
    "cold-outreach": [
        {"day": 0, "subject": "Quick question, {name}", "body": "Intro + value prop"},
        {"day": 3, "subject": "Following up", "body": "Case study nudge"},
        {"day": 7, "subject": "Worth a chat?", "body": "Offer 15-min call"},
        {"day": 14, "subject": "Closing the loop", "body": "Breakup email"},
    ],
}


class Engine:
    def __init__(self, path: Optional[str] = None):
        self.path = path or os.environ.get("LEADFORGE_DB", "leadforge_db.json")
        self.leads: Dict[str, Lead] = {}
        self.sequences: Dict[str, List[Dict[str, Any]]] = dict(DEFAULT_SEQUENCES)
        self._load()

    # ----- persistence -------------------------------------------------
    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise LeadForgeError(
                f"database file is not valid JSON ({self.path}): {exc}"
            ) from exc
        except OSError as exc:
            raise LeadForgeError(
                f"cannot read database file ({self.path}): {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise LeadForgeError(
                f"database file has unexpected format "
                f"(expected a JSON object): {self.path}"
            )
        leads_raw = data.get("leads", {})
        if not isinstance(leads_raw, dict):
            raise LeadForgeError("database 'leads' field must be a JSON object")
        loaded: Dict[str, Lead] = {}
        for lid, rec in leads_raw.items():
            if not isinstance(rec, dict):
                raise LeadForgeError(
                    f"lead record {lid!r} is not a JSON object"
                )
            # Drop unknown keys — keeps loading forward-compatible.
            known = set(Lead.__dataclass_fields__)
            rec_clean = {k: v for k, v in rec.items() if k in known}
            try:
                loaded[lid] = Lead(**rec_clean)
            except TypeError as exc:
                raise LeadForgeError(
                    f"lead record {lid!r} is missing required fields: {exc}"
                ) from exc
        self.leads = loaded
        sequences_raw = data.get("sequences", {})
        if not isinstance(sequences_raw, dict):
            raise LeadForgeError("database 'sequences' field must be a JSON object")
        self.sequences.update(sequences_raw)

    def save(self) -> None:
        data = {
            "leads": {lid: asdict(l) for lid, l in self.leads.items()},
            "sequences": self.sequences,
        }
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp, self.path)
        except OSError as exc:
            raise LeadForgeError(f"cannot save database ({self.path}): {exc}") from exc

    # ----- lead lifecycle ---------------------------------------------
    def add_lead(self, name: str, email: str, company: str = "",
                 value: float = 0.0) -> Lead:
        name = (name or "").strip()
        if not name:
            raise LeadForgeError("lead name is required")
        if not EMAIL_RE.match(email or ""):
            raise LeadForgeError(f"invalid email: {email!r}")
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise LeadForgeError(f"value must be a number, got: {value!r}")
        if value < 0:
            raise LeadForgeError(f"value must be non-negative, got: {value}")
        for l in self.leads.values():
            if l.email.lower() == email.lower():
                raise LeadForgeError(f"duplicate email: {email}")
        lid = uuid.uuid4().hex[:8]
        lead = Lead(id=lid, name=name, email=email, company=company,
                    value=float(value))
        lead.history.append({"at": _iso(_now()), "event": "created"})
        self.leads[lid] = lead
        return lead

    def get(self, lid: str) -> Lead:
        lead = self.leads.get(lid)
        if not lead:
            raise LeadForgeError(f"no such lead: {lid}")
        return lead

    def move(self, lid: str, stage: str) -> Lead:
        if stage not in STAGES:
            raise LeadForgeError(f"unknown stage: {stage} (valid: {', '.join(STAGES)})")
        lead = self.get(lid)
        old = lead.stage
        if old == stage:
            raise LeadForgeError(f"lead already in stage {stage}")
        # Cannot move out of a closed stage without an explicit reopen to 'new'.
        if old in ("won", "lost") and stage != "new":
            raise LeadForgeError(f"lead is closed ({old}); reopen to 'new' first")
        lead.stage = stage
        if stage in ("won", "lost"):
            lead.sequence = None
            lead.next_due = None
        lead.history.append({"at": _iso(_now()), "event": "stage",
                             "from": old, "to": stage})
        return lead

    # ----- sequences ---------------------------------------------------
    def enroll(self, lid: str, seq_name: str,
               start: Optional[datetime] = None) -> Lead:
        if seq_name not in self.sequences:
            raise LeadForgeError(f"unknown sequence: {seq_name}")
        lead = self.get(lid)
        if lead.stage in ("won", "lost"):
            raise LeadForgeError("cannot enroll a closed lead")
        steps = self.sequences[seq_name]
        if not steps:
            raise LeadForgeError(f"sequence {seq_name} has no steps")
        start = start or _now()
        lead.sequence = seq_name
        lead.seq_step = 0
        lead.next_due = _iso(start + timedelta(days=steps[0]["day"]))
        lead.history.append({"at": _iso(_now()), "event": "enrolled",
                             "sequence": seq_name})
        return lead

    def due_steps(self, at: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Return every sequence step currently due (next_due <= at)."""
        at = at or _now()
        out: List[Dict[str, Any]] = []
        for lead in self.leads.values():
            if not lead.sequence or not lead.next_due:
                continue
            if lead.sequence not in self.sequences:
                # Sequence was removed after enrollment — skip gracefully.
                continue
            steps = self.sequences[lead.sequence]
            if not steps or lead.seq_step >= len(steps):
                continue
            if _parse(lead.next_due) <= at:
                step = steps[lead.seq_step]
                out.append({
                    "lead_id": lead.id, "name": lead.name, "email": lead.email,
                    "sequence": lead.sequence, "step": lead.seq_step,
                    "due": lead.next_due,
                    "subject": step["subject"].format(name=lead.name,
                                                       company=lead.company or ""),
                    "body": step["body"],
                })
        return sorted(out, key=lambda r: r["due"])

    def send_due(self, at: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Mark all due steps as sent and advance/complete each sequence."""
        at = at or _now()
        sent: List[Dict[str, Any]] = []
        for row in self.due_steps(at):
            lead = self.leads[row["lead_id"]]
            steps = self.sequences[lead.sequence]
            lead.history.append({"at": _iso(at), "event": "email_sent",
                                 "sequence": lead.sequence, "step": lead.seq_step,
                                 "subject": row["subject"]})
            nxt = lead.seq_step + 1
            if nxt >= len(steps):
                lead.history.append({"at": _iso(at), "event": "sequence_done",
                                     "sequence": lead.sequence})
                lead.sequence = None
                lead.next_due = None
            else:
                base = _parse(lead.next_due) - timedelta(days=steps[lead.seq_step]["day"])
                lead.seq_step = nxt
                lead.next_due = _iso(base + timedelta(days=steps[nxt]["day"]))
            sent.append(row)
        return sent

    # ----- reporting ---------------------------------------------------
    def pipeline(self) -> Dict[str, Any]:
        by_stage: Dict[str, Dict[str, Any]] = {
            s: {"count": 0, "value": 0.0} for s in STAGES
        }
        for l in self.leads.values():
            by_stage[l.stage]["count"] += 1
            by_stage[l.stage]["value"] += l.value
        open_value = sum(by_stage[s]["value"] for s in OPEN_STAGES)
        won = by_stage["won"]["count"]
        closed = won + by_stage["lost"]["count"]
        return {
            "total_leads": len(self.leads),
            "open_value": round(open_value, 2),
            "won_value": round(by_stage["won"]["value"], 2),
            "win_rate": round(won / closed, 3) if closed else 0.0,
            "by_stage": by_stage,
        }

    def list_leads(self, stage: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = [asdict(l) for l in self.leads.values()]
        if stage:
            if stage not in STAGES:
                raise LeadForgeError(f"unknown stage: {stage}")
            rows = [r for r in rows if r["stage"] == stage]
        return sorted(rows, key=lambda r: (STAGES.index(r["stage"]), -r["value"]))
