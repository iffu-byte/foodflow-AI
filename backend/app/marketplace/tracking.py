from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import service as domain_service
from app.domain.models import (
    EtaPrediction,
    OrderStatus,
    Restaurant,
    Review,
    Rider,
    TrackingPoint,
    User,
)
from app.marketplace import access
from app.marketplace.schemas import (
    RoutePointOut,
    TrackingOut,
    TrackingPointOut,
    TrackingRiderOut,
    TrackingRouteOut,
)
from app.routing.base import LatLng
from app.routing.service import get_router

LIVE_GPS_WINDOW = timedelta(minutes=2)


def _is_live_gps(rider: Rider) -> bool:
    if rider.location_source != "gps" or rider.last_seen_at is None:
        return False
    seen = rider.last_seen_at
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=UTC)
    return datetime.now(UTC) - seen <= LIVE_GPS_WINDOW


async def tracking(session: AsyncSession, user: User, order_id: UUID) -> TrackingOut:
    order = await domain_service.get_order(session, order_id)
    await access.assert_can_view_order(session, user, order)
    restaurant = await session.get(Restaurant, order.restaurant_id)
    rider = await session.get(Rider, order.rider_id) if order.rider_id else None
    prediction = (
        await session.execute(
            select(EtaPrediction)
            .where(EtaPrediction.order_id == order.id)
            .order_by(EtaPrediction.created_at.desc())
        )
    ).scalars().first()
    points = list(
        (
            await session.execute(
                select(TrackingPoint)
                .where(TrackingPoint.order_id == order.id)
                .order_by(TrackingPoint.created_at.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    points.reverse()
    live_gps = rider is not None and _is_live_gps(rider)
    return TrackingOut(
        order_id=order.id,
        order_number=order.order_number,
        status=order.status,
        restaurant_name=restaurant.name if restaurant else "Restaurant",
        restaurant_address=restaurant.address if restaurant else None,
        restaurant_lat=restaurant.lat if restaurant else order.drop_lat,
        restaurant_lng=restaurant.lng if restaurant else order.drop_lng,
        drop_lat=order.drop_lat,
        drop_lng=order.drop_lng,
        delivery_address=order.delivery_address,
        rider=(
            TrackingRiderOut(
                id=rider.id,
                name=rider.name,
                lat=rider.lat,
                lng=rider.lng,
                vehicle=rider.vehicle,
                phone=None,
                location_source=rider.location_source,
                location_accuracy_m=rider.location_accuracy_m,
                last_seen_at=rider.last_seen_at,
            )
            if rider is not None
            else None
        ),
        points=[
            TrackingPointOut(lat=point.lat, lng=point.lng, created_at=point.created_at)
            for point in points
        ],
        eta_minutes=prediction.predicted_minutes if prediction else None,
        low_minutes=prediction.lower_bound_minutes if prediction else None,
        high_minutes=prediction.upper_bound_minutes if prediction else None,
        promised_eta_at=order.promised_eta_at,
        simulated=not live_gps,
    )


async def route_for_order(
    session: AsyncSession, user: User, order_id: UUID
) -> TrackingRouteOut:
    """Return the current delivery leg as map-ready route geometry.

    Routes are calculated on the server so routing credentials and provider
    fallback remain outside the browser.  The router cache rounds positions to
    roughly 100 metres, avoiding a provider request for every GPS event.
    """
    order = await domain_service.get_order(session, order_id)
    await access.assert_can_view_order(session, user, order)
    restaurant = await session.get(Restaurant, order.restaurant_id)
    restaurant_point = LatLng(
        restaurant.lat if restaurant is not None else order.drop_lat,
        restaurant.lng if restaurant is not None else order.drop_lng,
    )
    rider = await session.get(Rider, order.rider_id) if order.rider_id else None

    if rider is not None and order.status in (
        OrderStatus.READY,
        OrderStatus.ACCEPTED,
        OrderStatus.PREPARING,
    ):
        phase = "to_pickup"
        origin = LatLng(rider.lat, rider.lng)
        destination = restaurant_point
    elif rider is not None and order.status in (
        OrderStatus.PICKED_UP,
        OrderStatus.DELIVERED,
    ):
        phase = "to_drop"
        origin = LatLng(rider.lat, rider.lng)
        destination = LatLng(order.drop_lat, order.drop_lng)
    else:
        phase = "restaurant_to_customer"
        origin = restaurant_point
        destination = LatLng(order.drop_lat, order.drop_lng)

    result = await get_router().route(origin, destination)
    return TrackingRouteOut(
        order_id=order.id,
        phase=phase,
        origin=RoutePointOut(lat=origin.lat, lng=origin.lng),
        destination=RoutePointOut(lat=destination.lat, lng=destination.lng),
        points=[RoutePointOut(lat=lat, lng=lng) for lat, lng in result.polyline],
        distance_m=result.distance_m,
        duration_s=result.duration_s,
        routing_provider=result.provider,
        is_estimated=result.provider == "haversine",
    )


async def review_for_order(
    session: AsyncSession, order_id: UUID
) -> Review | None:
    return await session.scalar(select(Review).where(Review.order_id == order_id))
