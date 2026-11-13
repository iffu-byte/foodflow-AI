from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.models import Order, OrderEvent, OrderStatus, Rider
from app.realtime import service as realtime_service

ACTIVE_STATUSES = (
    OrderStatus.PLACED,
    OrderStatus.ACCEPTED,
    OrderStatus.PREPARING,
    OrderStatus.READY,
    OrderStatus.PICKED_UP,
)

AT_RISK_BUFFER_MIN = {
    OrderStatus.PLACED: 8.0,
    OrderStatus.ACCEPTED: 8.0,
    OrderStatus.PREPARING: 6.0,
    OrderStatus.READY: 5.0,
    OrderStatus.PICKED_UP: 4.0,
}

STALL_LIMIT_MIN = {
    OrderStatus.PLACED: 6.0,
    OrderStatus.ACCEPTED: 10.0,
    OrderStatus.PREPARING: 20.0,
    OrderStatus.READY: 10.0,
    OrderStatus.PICKED_UP: 30.0,
}


@dataclass
class RiskItem:
    order: Order
    rider: Rider | None
    severity: str
    flags: list[str]
    minutes_remaining: float | None
    minutes_since_last_event: float
    risk_score: int
    reasons: list[str]


@dataclass
class MonitorSummary:
    active_orders: int
    at_risk: int
    late: int
    stalled: int
    avg_minutes_remaining: float | None


@dataclass
class ScanResult:
    scanned: int
    events_appended: int
    orders: list[RiskItem]


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def _active_orders(session: AsyncSession, limit: int | None = 200) -> list[Order]:
    stmt = (
        select(Order)
        .where(Order.status.in_(ACTIVE_STATUSES))
        .options(selectinload(Order.items))
        .order_by(Order.placed_at)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list((await session.execute(stmt)).scalars().all())


def _assess_order(
    order: Order,
    rider: Rider | None,
    last_event_at: datetime,
    now: datetime,
) -> RiskItem | None:
    minutes_since = max(0.0, (now - last_event_at).total_seconds() / 60.0)
    flags: list[str] = []
    reasons: list[str] = []
    minutes_remaining: float | None = None

    if order.promised_eta_at is not None:
        promised = _aware(order.promised_eta_at)
        minutes_remaining = (promised - now).total_seconds() / 60.0
        buffer = AT_RISK_BUFFER_MIN.get(order.status, 5.0)
        if minutes_remaining < 0:
            flags.append("late")
            reasons.append(f"{abs(minutes_remaining):.0f} min past the promised ETA")
        elif minutes_remaining <= buffer:
            flags.append("at_risk")
            reasons.append(
                f"{minutes_remaining:.0f} min left, inside the {buffer:.0f} min buffer"
            )

    stall_limit = STALL_LIMIT_MIN.get(order.status, 20.0)
    if minutes_since > stall_limit:
        flags.append("stalled")
        reasons.append(f"no progress for {minutes_since:.0f} min (limit {stall_limit:.0f})")

    if not flags:
        return None

    score = 0
    if "late" in flags:
        score += 60 + min(25, int(abs(minutes_remaining or 0.0) * 2))
    if "at_risk" in flags:
        score += 35
    if "stalled" in flags:
        score += 25 + min(15, int(max(0.0, minutes_since - stall_limit)))
    score = min(100, score)
    severity = "critical" if "late" in flags or score >= 70 else "warning"

    return RiskItem(
        order=order,
        rider=rider,
        severity=severity,
        flags=flags,
        minutes_remaining=(
            round(minutes_remaining, 1) if minutes_remaining is not None else None
        ),
        minutes_since_last_event=round(minutes_since, 1),
        risk_score=score,
        reasons=reasons,
    )


async def _assess_orders(
    session: AsyncSession,
    orders: list[Order],
    now: datetime | None = None,
) -> list[RiskItem]:
    if not orders:
        return []
    now = now or datetime.now(UTC)

    order_ids = [order.id for order in orders]
    rows = (
        await session.execute(
            select(OrderEvent.order_id, func.max(OrderEvent.created_at))
            .where(OrderEvent.order_id.in_(order_ids))
            .group_by(OrderEvent.order_id)
        )
    ).all()
    last_events = {row[0]: _aware(row[1]) for row in rows}

    rider_ids = {order.rider_id for order in orders if order.rider_id is not None}
    riders = (
        {
            rider.id: rider
            for rider in (
                await session.execute(select(Rider).where(Rider.id.in_(rider_ids)))
            )
            .scalars()
            .all()
        }
        if rider_ids
        else {}
    )

    items: list[RiskItem] = []
    for order in orders:
        last_event_at = last_events.get(order.id, _aware(order.placed_at))
        item = _assess_order(order, riders.get(order.rider_id), last_event_at, now)
        if item is not None:
            items.append(item)
    return items


async def list_at_risk(session: AsyncSession, limit: int = 50) -> list[RiskItem]:
    orders = await _active_orders(session, limit)
    items = await _assess_orders(session, orders)
    return sorted(items, key=lambda item: (-item.risk_score, item.order.placed_at))


async def scan(session: AsyncSession, limit: int = 200) -> ScanResult:
    orders = await _active_orders(session, limit)
    items = await _assess_orders(session, orders)
    by_order = {item.order.id: item for item in items}

    events: list[tuple[Order, OrderEvent]] = []
    for order in orders:
        item = by_order.get(order.id)
        current_flags = list(item.flags) if item is not None else []
        previous_flags = set(order.delay_flags or [])
        new_flags = [flag for flag in current_flags if flag not in previous_flags]
        order.delay_flags = current_flags

        if item is None or not new_flags:
            continue

        event = OrderEvent(
            order_id=order.id,
            type="delay_flagged",
            payload={
                "severity": item.severity,
                "flags": current_flags,
                "new_flags": new_flags,
                "risk_score": item.risk_score,
                "minutes_remaining": item.minutes_remaining,
                "minutes_since_last_event": item.minutes_since_last_event,
                "reasons": item.reasons,
            },
        )
        session.add(event)
        events.append((order, event))

    await session.commit()

    for order, event in events:
        await realtime_service.publish_order_event(order, event)

    return ScanResult(scanned=len(orders), events_appended=len(events), orders=items)


async def summary(session: AsyncSession) -> MonitorSummary:
    orders = await _active_orders(session, None)
    items = await _assess_orders(session, orders)
    remaining = [
        item.minutes_remaining for item in items if item.minutes_remaining is not None
    ]
    return MonitorSummary(
        active_orders=len(orders),
        at_risk=len(items),
        late=sum(1 for item in items if "late" in item.flags),
        stalled=sum(1 for item in items if "stalled" in item.flags),
        avg_minutes_remaining=(
            round(sum(remaining) / len(remaining), 1) if remaining else None
        ),
    )
