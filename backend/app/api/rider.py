from uuid import UUID

from fastapi import APIRouter

from app.api.deps import SessionDep
from app.auth.deps import RiderUser
from app.domain.schemas import RiderLocationUpdate
from app.marketplace import access, dispatch
from app.marketplace.schemas import (
    AssignmentActionOut,
    AvailabilityIn,
    DeliveryActionIn,
    EarningsOut,
    MarketOrderOut,
    OfferActionOut,
    OfferOut,
    RiderProfileOut,
)

router = APIRouter(prefix="/api/v1/rider", tags=["rider"])


@router.get("/me", response_model=RiderProfileOut)
async def me(user: RiderUser, session: SessionDep) -> RiderProfileOut:
    rider = await access.rider_for(session, user)
    return await dispatch.rider_profile(session, rider)


@router.post("/availability", response_model=RiderProfileOut)
async def availability(
    payload: AvailabilityIn, user: RiderUser, session: SessionDep
) -> RiderProfileOut:
    rider = await access.rider_for(session, user)
    return await dispatch.set_availability(session, rider, payload.online)


@router.post("/location", response_model=RiderProfileOut)
async def location(
    payload: RiderLocationUpdate, user: RiderUser, session: SessionDep
) -> RiderProfileOut:
    rider = await access.rider_for(session, user)
    return await dispatch.update_location(
        session,
        rider,
        payload.lat,
        payload.lng,
        source=payload.source,
        accuracy_m=payload.accuracy_m,
    )


@router.get("/offers", response_model=list[OfferOut])
async def offers(user: RiderUser, session: SessionDep) -> list[OfferOut]:
    rider = await access.rider_for(session, user)
    return await dispatch.offers_for_rider(session, rider)


@router.post("/offers/{assignment_id}/accept", response_model=AssignmentActionOut)
async def accept_offer(
    assignment_id: UUID, user: RiderUser, session: SessionDep
) -> AssignmentActionOut:
    rider = await access.rider_for(session, user)
    return await dispatch.accept_offer(session, rider, assignment_id)


@router.post("/offers/{assignment_id}/reject", response_model=OfferActionOut)
async def reject_offer(
    assignment_id: UUID,
    user: RiderUser,
    session: SessionDep,
    payload: DeliveryActionIn | None = None,
) -> dict:
    rider = await access.rider_for(session, user)
    return await dispatch.reject_offer(
        session,
        rider,
        assignment_id,
        payload.reason if payload else None,
    )


@router.get("/deliveries/active", response_model=AssignmentActionOut | None)
async def active_delivery(
    user: RiderUser, session: SessionDep
) -> AssignmentActionOut | None:
    rider = await access.rider_for(session, user)
    return await dispatch.active_delivery(session, rider)


@router.get("/deliveries/history", response_model=list[MarketOrderOut])
async def delivery_history(
    user: RiderUser, session: SessionDep
) -> list[MarketOrderOut]:
    rider = await access.rider_for(session, user)
    return await dispatch.delivery_history(session, rider)


@router.get("/earnings", response_model=EarningsOut)
async def earnings(user: RiderUser, session: SessionDep) -> EarningsOut:
    rider = await access.rider_for(session, user)
    return await dispatch.earnings(session, rider)


@router.post(
    "/assignments/{assignment_id}/arrived-restaurant",
    response_model=AssignmentActionOut,
)
async def arrived_restaurant(
    assignment_id: UUID, user: RiderUser, session: SessionDep
) -> AssignmentActionOut:
    rider = await access.rider_for(session, user)
    return await dispatch.arrived_at_restaurant(session, rider, assignment_id)


@router.post("/assignments/{assignment_id}/pickup", response_model=AssignmentActionOut)
async def pickup(
    assignment_id: UUID, user: RiderUser, session: SessionDep
) -> AssignmentActionOut:
    rider = await access.rider_for(session, user)
    return await dispatch.pickup(session, rider, assignment_id)


@router.post(
    "/assignments/{assignment_id}/arrived-customer",
    response_model=AssignmentActionOut,
)
async def arrived_customer(
    assignment_id: UUID, user: RiderUser, session: SessionDep
) -> AssignmentActionOut:
    rider = await access.rider_for(session, user)
    return await dispatch.arrived_at_customer(session, rider, assignment_id)


@router.post("/assignments/{assignment_id}/complete", response_model=AssignmentActionOut)
async def complete(
    assignment_id: UUID,
    user: RiderUser,
    session: SessionDep,
    payload: DeliveryActionIn | None = None,
) -> AssignmentActionOut:
    rider = await access.rider_for(session, user)
    return await dispatch.complete(session, rider, assignment_id, payload)
