import itertools

import pytest

from app.domain.exceptions import IllegalTransition
from app.domain.models import Order, OrderEvent, OrderStatus, new_uuid
from app.domain.state_machine import LEGAL_TRANSITIONS, transition


def make_order(status: OrderStatus) -> Order:
    return Order(
        id=new_uuid(),
        customer_id=new_uuid(),
        restaurant_id=new_uuid(),
        status=status,
        drop_lat=17.44,
        drop_lng=78.35,
    )


@pytest.mark.parametrize(
    ("current", "target"), list(itertools.product(OrderStatus, OrderStatus))
)
def test_transition_matrix_matches_legal_map(current: OrderStatus, target: OrderStatus) -> None:
    order = make_order(current)

    if target in LEGAL_TRANSITIONS[current]:
        event = transition(order, target, actor="test")

        assert order.status is target
        assert isinstance(event, OrderEvent)
        assert event.type == "status_changed"
        assert event.payload["from"] == current.value
        assert event.payload["to"] == target.value
        assert event.payload["actor"] == "test"
    else:
        with pytest.raises(IllegalTransition):
            transition(order, target, actor="test")
        assert order.status is current
