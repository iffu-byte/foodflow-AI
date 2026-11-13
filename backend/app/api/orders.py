from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import SessionDep
from app.auth.deps import require_roles
from app.domain import service
from app.domain.exceptions import NotFoundError
from app.domain.models import OrderStatus, Restaurant, Role
from app.domain.schemas import (
    ActionRequest,
    OrderCreate,
    OrderEventOut,
    OrderOut,
    RiderStatusUpdate,
)
from app.eta.schemas import EtaOut
from app.eta.service import estimate_for_order

_admin_only = [Depends(require_roles(Role.ADMIN))]

# These legacy endpoints power the operations console. Marketplace actors use
# the authenticated role-specific APIs under /api/v1 instead.
router = APIRouter(prefix="/orders", tags=["orders"], dependencies=_admin_only)
restaurant_router = APIRouter(
    prefix="/restaurant/orders", tags=["restaurant"], dependencies=_admin_only
)


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def create_order(payload: OrderCreate, session: SessionDep) -> OrderOut:
    order = await service.create_order(session, payload)
    return OrderOut.model_validate(order)


@router.get("", response_model=list[OrderOut])
async def list_orders(
    session: SessionDep,
    status: OrderStatus | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[OrderOut]:
    orders = await service.list_orders(session, status=status, limit=limit)
    return [OrderOut.model_validate(order) for order in orders]


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: UUID, session: SessionDep) -> OrderOut:
    order = await service.get_order(session, order_id)
    return OrderOut.model_validate(order)


@router.get("/{order_id}/events", response_model=list[OrderEventOut])
async def list_order_events(order_id: UUID, session: SessionDep) -> list[OrderEventOut]:
    events = await service.list_order_events(session, order_id)
    return [OrderEventOut.model_validate(event) for event in events]


@router.get("/{order_id}/eta", response_model=EtaOut)
async def get_order_eta(order_id: UUID, session: SessionDep) -> EtaOut:
    order = await service.get_order(session, order_id)
    restaurant = await session.get(Restaurant, order.restaurant_id)
    if restaurant is None:
        raise NotFoundError("restaurant not found")

    prediction = await estimate_for_order(session, order, restaurant)
    meets_deadline = (
        order.promised_eta_at <= order.deadline_at
        if order.promised_eta_at is not None and order.deadline_at is not None
        else None
    )
    return EtaOut(
        **prediction.event_payload(),
        promised_eta_at=order.promised_eta_at,
        deadline_at=order.deadline_at,
        meets_deadline=meets_deadline,
    )


@router.post("/{order_id}/cancel", response_model=OrderOut)
async def cancel_order(
    order_id: UUID,
    session: SessionDep,
    body: ActionRequest | None = None,
) -> OrderOut:
    order = await service.advance_order(
        session,
        order_id,
        OrderStatus.CANCELLED,
        actor="customer",
        reason=body.reason if body else None,
    )
    return OrderOut.model_validate(order)


@router.post("/{order_id}/status", response_model=OrderOut)
async def update_order_status(
    order_id: UUID,
    payload: RiderStatusUpdate,
    session: SessionDep,
) -> OrderOut:
    order = await service.advance_order(
        session,
        order_id,
        OrderStatus(payload.status),
        actor=f"rider:{payload.rider_id}",
        reason=payload.reason,
        rider_id=payload.rider_id,
    )
    return OrderOut.model_validate(order)


@restaurant_router.post("/{order_id}/accept", response_model=OrderOut)
async def accept_order(
    order_id: UUID,
    session: SessionDep,
    body: ActionRequest | None = None,
) -> OrderOut:
    order = await service.advance_order(
        session,
        order_id,
        OrderStatus.ACCEPTED,
        actor="restaurant",
        reason=body.reason if body else None,
    )
    return OrderOut.model_validate(order)


@restaurant_router.post("/{order_id}/preparing", response_model=OrderOut)
async def start_preparing(
    order_id: UUID,
    session: SessionDep,
    body: ActionRequest | None = None,
) -> OrderOut:
    order = await service.advance_order(
        session,
        order_id,
        OrderStatus.PREPARING,
        actor="restaurant",
        reason=body.reason if body else None,
    )
    return OrderOut.model_validate(order)


@restaurant_router.post("/{order_id}/ready", response_model=OrderOut)
async def mark_ready(
    order_id: UUID,
    session: SessionDep,
    body: ActionRequest | None = None,
) -> OrderOut:
    order = await service.advance_order(
        session,
        order_id,
        OrderStatus.READY,
        actor="restaurant",
        reason=body.reason if body else None,
    )
    return OrderOut.model_validate(order)
