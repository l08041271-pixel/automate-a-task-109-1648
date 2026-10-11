"""Aggregate metrics for the CEO dashboard.

Every number carries an explicit provenance so the dashboard never presents a
guess as a measurement:

  * ``measured``  — counted directly from stored records.
  * ``recorded``  — summed from records the business entered (e.g. prices).
  * ``not_recorded`` — the underlying data simply is not in the system yet.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.enums import (
    BookingStatus,
    ConversationStatus,
    JobStatus,
    LeadSource,
    MessageDirection,
    PipelineStage,
    RunStatus,
)
from app.db.models import (
    AutomationRun,
    Booking,
    Campaign,
    Conversation,
    FollowUpJob,
    Lead,
    Message,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _count(db: Session, model, *filters) -> int:
    return int(db.execute(select(func.count()).select_from(model).where(*filters)).scalar_one())


def _group_counts(db: Session, column, model, *filters) -> dict[str, int]:
    rows = db.execute(
        select(column, func.count()).select_from(model).where(*filters).group_by(column)
    ).all()
    return {(k.value if hasattr(k, "value") else str(k)): int(v) for k, v in rows}


def build_summary(db: Session, *, days: int = 30) -> dict:
    now = _now()
    since = now - timedelta(days=days)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # --- Leads ------------------------------------------------------------
    total_leads = _count(db, Lead)
    leads_in_period = _count(db, Lead, Lead.created_at >= since)
    new_today = _count(db, Lead, Lead.created_at >= day_start)
    by_stage = _group_counts(db, Lead.stage, Lead)
    by_classification = _group_counts(db, Lead.classification, Lead)
    by_source = _group_counts(db, Lead.source, Lead)

    qualified = (
        by_stage.get(PipelineStage.QUALIFIED.value, 0)
        + by_stage.get(PipelineStage.BOOKED.value, 0)
        + by_stage.get(PipelineStage.COMPLETED.value, 0)
    )
    lost_leads = by_stage.get(PipelineStage.LOST.value, 0)

    # --- WhatsApp ---------------------------------------------------------
    whatsapp_leads = _count(db, Lead, Lead.source == LeadSource.WHATSAPP_INBOUND)
    inbound_messages = _count(db, Message, Message.direction == MessageDirection.INBOUND)
    open_conversations = _count(db, Conversation, Conversation.status == ConversationStatus.OPEN)
    escalated = _count(db, Conversation, Conversation.status == ConversationStatus.ESCALATED)

    # --- Bookings ---------------------------------------------------------
    by_booking_status = _group_counts(db, Booking.status, Booking)
    confirmed = by_booking_status.get(BookingStatus.CONFIRMED.value, 0)
    completed = by_booking_status.get(BookingStatus.COMPLETED.value, 0)
    booked_total = confirmed + completed
    conversion_rate = round(booked_total / total_leads * 100, 1) if total_leads else 0.0

    # --- Follow-ups -------------------------------------------------------
    followups_due = _count(
        db, FollowUpJob, FollowUpJob.status == JobStatus.SCHEDULED, FollowUpJob.due_at <= now
    )
    followups_scheduled = _count(db, FollowUpJob, FollowUpJob.status == JobStatus.SCHEDULED)
    followups_failed = _count(db, FollowUpJob, FollowUpJob.status == JobStatus.FAILED)

    # --- Money (only what was actually recorded) --------------------------
    revenue = db.execute(
        select(func.coalesce(func.sum(Booking.price_amount), 0)).where(
            Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.COMPLETED])
        )
    ).scalar_one()
    priced_bookings = _count(
        db,
        Booking,
        Booking.price_amount.is_not(None),
        Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.COMPLETED]),
    )
    expenses = db.execute(
        select(func.coalesce(func.sum(Campaign.spend_amount), 0))
    ).scalar_one()

    # --- System health ----------------------------------------------------
    last_run = db.execute(
        select(AutomationRun).order_by(AutomationRun.started_at.desc()).limit(1)
    ).scalars().first()
    db_ok = True
    try:
        db.execute(select(1))
    except Exception:  # pragma: no cover - only reachable with a broken DB
        db_ok = False

    return {
        "generated_at": now.isoformat(),
        "period_days": days,
        "leads": {
            "total": total_leads,
            "in_period": leads_in_period,
            "new_today": new_today,
            "qualified": qualified,
            "lost": lost_leads,
            "by_stage": by_stage,
            "by_classification": by_classification,
            "by_source": by_source,
            "provenance": "measured",
        },
        "whatsapp": {
            "inbound_messages": inbound_messages,
            "leads_from_whatsapp": whatsapp_leads,
            "open_conversations": open_conversations,
            "escalated_to_owner": escalated,
            "provenance": "measured",
        },
        "bookings": {
            "requested": by_booking_status.get(BookingStatus.REQUESTED.value, 0),
            "confirmed": confirmed,
            "completed": completed,
            "cancelled": by_booking_status.get(BookingStatus.CANCELLED.value, 0),
            "no_show": by_booking_status.get(BookingStatus.NO_SHOW.value, 0),
            "by_status": by_booking_status,
            "provenance": "measured",
        },
        "conversion": {
            "lead_to_booking_rate_pct": conversion_rate,
            "basis": "(confirmed + completed bookings) / all leads",
            "provenance": "measured",
            "caveat": (
                "A rate, not a prediction. Recently captured leads may still convert, "
                "so short periods understate performance."
            ),
        },
        "money": {
            "currency": "SAR",
            "revenue_recorded": float(revenue or 0),
            "expenses_recorded": float(expenses or 0),
            "priced_bookings": priced_bookings,
            "provenance": "recorded" if (priced_bookings or float(expenses or 0)) else "not_recorded",
            "caveat": (
                "Only amounts actually entered against bookings and campaigns. This is "
                "NOT a full P&L; untracked costs and off-platform spend are excluded."
            ),
        },
        "follow_ups": {
            "due_now": followups_due,
            "scheduled": followups_scheduled,
            "failed": followups_failed,
            "provenance": "measured",
        },
        "campaigns": _campaign_rows(db),
        "system_health": {
            "database": "ok" if db_ok else "unavailable",
            "last_automation_run": (
                {
                    "run_type": last_run.run_type,
                    "status": (
                        last_run.status.value
                        if isinstance(last_run.status, RunStatus)
                        else str(last_run.status)
                    ),
                    "started_at": last_run.started_at.isoformat() if last_run.started_at else None,
                }
                if last_run
                else None
            ),
            "provenance": "measured",
        },
        "measurement_notes": {
            "measured": "Counted directly from stored CRM records.",
            "recorded": "Summed from values the business entered; blanks are excluded.",
            "not_tracked": (
                "Walk-ins, phone calls that never entered the CRM, and off-platform "
                "advertising spend are not included anywhere in this summary."
            ),
        },
    }


def _campaign_rows(db: Session) -> list[dict]:
    campaigns = db.execute(
        select(Campaign).order_by(Campaign.created_at.desc()).limit(20)
    ).scalars().all()
    rows: list[dict] = []
    for campaign in campaigns:
        c_leads = _count(db, Lead, Lead.campaign_id == campaign.id)
        c_bookings = _count(
            db,
            Booking,
            Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.COMPLETED]),
            Booking.lead_id.in_(select(Lead.id).where(Lead.campaign_id == campaign.id)),
        )
        spend = float(campaign.spend_amount) if campaign.spend_amount is not None else None
        rows.append(
            {
                "id": str(campaign.id),
                "name": campaign.name,
                "channel": campaign.channel,
                "status": campaign.status,
                "utm_campaign": campaign.utm_campaign,
                "leads": c_leads,
                "bookings": c_bookings,
                "spend": spend,
                "cost_per_lead": round(spend / c_leads, 2) if spend and c_leads else None,
                "cost_per_booking": round(spend / c_bookings, 2) if spend and c_bookings else None,
                "spend_provenance": "recorded" if spend is not None else "not_recorded",
            }
        )
    return rows
