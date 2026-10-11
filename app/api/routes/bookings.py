"""Booking endpoints. Confirmation always requires human verification."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_writer
from app.core.logging import get_logger
from app.core.security import Principal
from app.db.models import Booking
from app.schemas.booking import BookingCreate, BookingRead, BookingUpdate
from app.services import bookings as bookings_service
from app.services.bookings import BookingNotFoundError, UnverifiedConfirmationError

router = APIRouter(prefix="/bookings", tags=["bookings"])
logger = get_logger(__name__)


@router.post("", response_model=BookingRead, status_code=status.HTTP_201_CREATED)
def create_booking(
    payload: BookingCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_writer),
) -> BookingRead:
    """Record a booking *request*. It is never a confirmation."""
    try:
        booking = bookings_service.create_booking(db, payload, actor=principal.subject)
    except BookingNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    db.commit()
    db.refresh(booking)
    return booking


@router.patch("/{booking_id}", response_model=BookingRead)
def update_booking(
    booking_id: uuid.UUID,
    payload: BookingUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_writer),
) -> BookingRead:
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    try:
        bookings_service.update_booking(db, booking, payload, actor=principal.subject)
    except UnverifiedConfirmationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    db.commit()
    db.refresh(booking)
    return booking


@router.get("/{booking_id}", response_model=BookingRead)
def get_booking(
    booking_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_writer),
) -> BookingRead:
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    return booking
