"""AI Growth Agent — scheduled analysis that produces *recommendations only*.

Operating mode: RECOMMENDATION_ONLY.

This module never spends money, never publishes content, never deletes records
and never changes customer messaging policy. Consequential actions require an
explicit, separately-recorded authorisation from an owner (see
``authorize_recommendation``), and even then the action is performed by a human
or a purpose-built job — not by this agent.

Honesty rules:
  * Every recommendation cites the concrete numbers it is based on.
  * Nothing claims the system "learns" or "improves automatically"; the agent
    compares the current period with the previous one and says so plainly.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger, log_extra
from app.db.enums import (
    ConversationStatus,
    JobStatus,
    LeadClassification,
    MessageStatus,
    PipelineStage,
    RunStatus,
)
from app.db.models import AutomationRun, Conversation, FollowUpJob, Lead, Message
from app.services import analytics

logger = get_logger(__name__)

MODE = "recommendation_only"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Recommendation:
    id: str
    category: str
    severity: str  # info | low | medium | high
    title: str
    evidence: dict
    suggested_action: str
    requires_authorization: bool = False
    authorization_scope: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class GrowthReport:
    run_id: str | None
    generated_at: str
    mode: str
    period_days: int
    metrics: dict
    recommendations: list[Recommendation] = field(default_factory=list)
    summary_text: str = ""
    comparison: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "generated_at": self.generated_at,
            "mode": self.mode,
            "period_days": self.period_days,
            "metrics": self.metrics,
            "recommendations": [r.as_dict() for r in self.recommendations],
            "summary_text": self.summary_text,
            "comparison": self.comparison,
            "disclaimer": (
                "Recommendation-only mode. No campaign spend, publishing, record "
                "deletion or messaging-policy change is performed automatically. "
                "This agent does not 'learn' on its own; it compares stored metrics."
            ),
        }


def _rid() -> str:
    return uuid.uuid4().hex[:12]


# --------------------------------------------------------------------------- #
# Bottleneck detection
# --------------------------------------------------------------------------- #
def _count(db: Session, model, *filters) -> int:
    return int(db.execute(select(func.count()).select_from(model).where(*filters)).scalar_one())


def detect_bottlenecks(db: Session, summary: dict) -> list[Recommendation]:
    """Inspect stored metrics and describe concrete, actionable problems."""
    now = _now()
    recs: list[Recommendation] = []

    leads = summary["leads"]
    bookings = summary["bookings"]
    total = leads["total"]

    # 1. Nothing captured at all.
    if total == 0:
        recs.append(Recommendation(
            id=_rid(), category="acquisition", severity="high",
            title="No leads have been captured yet",
            evidence={"total_leads": 0},
            suggested_action=(
                "Confirm lead capture is wired up: submit a test entry through the "
                "website form and send a test WhatsApp message, then check that both "
                "appear here. Until leads are recorded, no other metric is meaningful."
            ),
        ))
        return recs

    # 2. Cold-dominant pipeline = qualification problem.
    cold = leads["by_classification"].get(LeadClassification.COLD.value, 0)
    cold_share = cold / total
    if cold_share >= 0.6:
        recs.append(Recommendation(
            id=_rid(), category="qualification", severity="medium",
            title="Most leads arrive with too little information to qualify",
            evidence={"cold_leads": cold, "total_leads": total,
                      "cold_share_pct": round(cold_share * 100, 1)},
            suggested_action=(
                "Add the service, preferred time and location fields to the capture "
                "form and to the WhatsApp first reply so leads arrive pre-qualified."
            ),
        ))

    # 3. Leads captured but never worked (still NEW after a day).
    stale_cutoff = now - timedelta(hours=settings.unanswered_inquiry_hours * 3)
    unworked = _count(
        db, Lead, Lead.stage == PipelineStage.NEW, Lead.created_at <= stale_cutoff
    )
    if unworked > 0:
        recs.append(Recommendation(
            id=_rid(), category="follow_up", severity="high",
            title="Leads are sitting in NEW without being contacted",
            evidence={"unworked_new_leads": unworked,
                      "older_than_hours": settings.unanswered_inquiry_hours * 3},
            suggested_action=(
                "Open the follow-up queue and send the drafted replies. Each of these "
                "leads already has a prepared message waiting for approval."
            ),
        ))

    # 4. Drafts piling up = replies not being sent.
    pending_drafts = _count(db, Message, Message.status == MessageStatus.DRAFTED)
    if pending_drafts >= 5:
        recs.append(Recommendation(
            id=_rid(), category="operations", severity="medium",
            title="Prepared replies are piling up unsent",
            evidence={"drafted_messages_waiting": pending_drafts},
            suggested_action=(
                "Review and send the drafted replies. Drafting is automatic; sending "
                "is deliberately a human decision."
            ),
        ))

    # 5. Qualified leads that never convert.
    if leads["qualified"] >= 5 and bookings["confirmed"] + bookings["completed"] == 0:
        recs.append(Recommendation(
            id=_rid(), category="conversion", severity="high",
            title="Qualified leads are not converting into bookings",
            evidence={"qualified_leads": leads["qualified"],
                      "confirmed_bookings": bookings["confirmed"],
                      "completed_bookings": bookings["completed"]},
            suggested_action=(
                "Call the qualified leads directly. Ask what blocked them from "
                "booking and record the answer against the lead."
            ),
        ))

    # 6. Escalated WhatsApp conversations nobody picked up.
    escalated = _count(db, Conversation, Conversation.status == ConversationStatus.ESCALATED)
    if escalated > 0:
        recs.append(Recommendation(
            id=_rid(), category="operations", severity="high",
            title="Hot WhatsApp conversations are waiting for the owner",
            evidence={"escalated_conversations": escalated},
            suggested_action=(
                "Reply to the escalated conversations first — they were flagged HOT "
                "by the qualification engine and are the most likely to book."
            ),
        ))

    # 7. Failed follow-up jobs.
    failed_jobs = _count(db, FollowUpJob, FollowUpJob.status == JobStatus.FAILED)
    if failed_jobs > 0:
        recs.append(Recommendation(
            id=_rid(), category="reliability", severity="medium",
            title="Some follow-up jobs exhausted their retries",
            evidence={"failed_follow_up_jobs": failed_jobs},
            suggested_action=(
                "Inspect these leads manually. Persistent failures usually mean a "
                "missing WhatsApp channel or a consent record that was never set."
            ),
        ))

    # 8. Campaigns that spend but never convert.
    for campaign in summary.get("campaigns", []):
        if campaign["spend"] and campaign["bookings"] == 0 and campaign["leads"] >= 5:
            recs.append(Recommendation(
                id=_rid(), category="marketing", severity="medium",
                title=f"Campaign '{campaign['name']}' spends without bookings",
                evidence={"campaign": campaign["name"], "spend": campaign["spend"],
                          "leads": campaign["leads"], "bookings": 0},
                suggested_action=(
                    "Pause or rework this campaign's creative and landing page, then "
                    "run a small test before restoring the budget."
                ),
                requires_authorization=True,
                authorization_scope="campaign_budget_change",
            ))

    return recs


# --------------------------------------------------------------------------- #
# Period-over-period comparison
# --------------------------------------------------------------------------- #
def _period_comparison(db: Session, days: int) -> dict:
    now = _now()
    current_start = now - timedelta(days=days)
    previous_start = now - timedelta(days=days * 2)

    current = _count(db, Lead, Lead.created_at >= current_start)
    previous = _count(
        db, Lead, Lead.created_at >= previous_start, Lead.created_at < current_start
    )
    if previous == 0:
        change = None
        note = "No leads were captured in the previous period, so no change can be computed."
    else:
        change = round((current - previous) / previous * 100, 1)
        note = "Percentage change in captured leads versus the preceding period."

    return {
        "current_period_leads": current,
        "previous_period_leads": previous,
        "change_pct": change,
        "basis": note,
        "provenance": "measured",
    }


# --------------------------------------------------------------------------- #
# Report assembly
# --------------------------------------------------------------------------- #
def _summary_text(summary: dict, recs: list[Recommendation], comparison: dict) -> str:
    leads = summary["leads"]
    bookings = summary["bookings"]
    lines = [
        f"Leads captured in this window: {leads['in_period']} "
        f"({leads['total']} all-time, {leads['new_today']} today).",
        f"Pipeline: {leads['qualified']} qualified, {leads['lost']} lost.",
        f"Bookings: {bookings['confirmed']} confirmed, {bookings['completed']} completed.",
        f"Lead-to-booking conversion: {summary['conversion']['lead_to_booking_rate_pct']}%.",
        f"WhatsApp inbound messages: {summary['whatsapp']['inbound_messages']} "
        f"({summary['whatsapp']['escalated_to_owner']} escalated to the owner).",
        f"Follow-ups due now: {summary['follow_ups']['due_now']}.",
    ]
    if comparison["change_pct"] is not None:
        lines.append(f"Lead volume vs previous period: {comparison['change_pct']}%.")
    else:
        lines.append(comparison["basis"])
    lines.append(
        f"{len(recs)} recommendation(s) generated. Mode: {MODE} — nothing was executed."
    )
    return " ".join(lines)


def run_analysis(db: Session, *, days: int = 7, persist: bool = True) -> GrowthReport:
    """Analyse stored metrics and return recommendations. Executes nothing."""
    started = _now()
    summary = analytics.build_summary(db, days=days)
    recommendations = detect_bottlenecks(db, summary)
    comparison = _period_comparison(db, days)

    run_id: str | None = None
    if persist:
        run = AutomationRun(
            run_type="growth_analysis",
            status=RunStatus.SUCCESS,
            started_at=started,
            finished_at=_now(),
            metrics={
                "leads_total": summary["leads"]["total"],
                "leads_in_period": summary["leads"]["in_period"],
                "qualified": summary["leads"]["qualified"],
                "confirmed_bookings": summary["bookings"]["confirmed"],
                "completed_bookings": summary["bookings"]["completed"],
                "conversion_pct": summary["conversion"]["lead_to_booking_rate_pct"],
                "follow_ups_due": summary["follow_ups"]["due_now"],
                "comparison": comparison,
            },
            recommendations=[r.as_dict() for r in recommendations],
        )
        run.duration_ms = int((run.finished_at - started).total_seconds() * 1000)
        db.add(run)
        db.flush()
        run_id = str(run.id)

    report = GrowthReport(
        run_id=run_id,
        generated_at=started.isoformat(),
        mode=MODE,
        period_days=days,
        metrics=summary,
        recommendations=recommendations,
        comparison=comparison,
    )
    report.summary_text = _summary_text(summary, recommendations, comparison)
    logger.info(
        "growth.analysis_complete",
        extra=log_extra(run_id=run_id, recommendations=len(recommendations), mode=MODE),
    )
    return report
