from app.domain.exceptions import IllegalTransition
from app.domain.models import Order, OrderEvent, OrderStatus

LEGAL_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PLACED: {OrderStatus.ACCEPTED, OrderStatus.CANCELLED},
    OrderStatus.ACCEPTED: {OrderStatus.PREPARING, OrderStatus.CANCELLED},
    OrderStatus.PREPARING: {OrderStatus.READY, OrderStatus.CANCELLED},
    OrderStatus.READY: {OrderStatus.PICKED_UP, OrderStatus.CANCELLED},
    OrderStatus.PICKED_UP: {OrderStatus.DELIVERED, OrderStatus.FAILED},
    OrderStatus.DELIVERED: set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.FAILED: set(),
}


def transition(
    order: Order,
    new_status: OrderStatus,
    actor: str,
    reason: str | None = None,
) -> OrderEvent:
    """Apply a validated status change and return the matching order event.

    This is the single choke point for order status mutations. Callers own the
    transaction and must persist the returned event.
    """
    allowed = LEGAL_TRANSITIONS[order.status]
    if new_status not in allowed:
        raise IllegalTransition(order.status.value, new_status.value)

    previous = order.status
    order.status = new_status
    return OrderEvent(
        order_id=order.id,
        type="status_changed",
        payload={
            "from": previous.value,
            "to": new_status.value,
            "actor": actor,
            "reason": reason,
        },
    )
