from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.domain.exceptions import BadRequestError

TAX_RATE = Decimal("0.05")
FREE_DELIVERY_THRESHOLD = Decimal("499.00")

COUPONS: dict[str, dict] = {
    "WELCOME50": {
        "description": "Flat 50 off on orders above 299",
        "min_subtotal": Decimal("299.00"),
        "discount": Decimal("50.00"),
        "free_delivery": False,
    },
    "FEAST10": {
        "description": "10% off up to 100",
        "min_subtotal": Decimal("199.00"),
        "percent": Decimal("0.10"),
        "max_discount": Decimal("100.00"),
        "free_delivery": False,
    },
    "FREEDEL": {
        "description": "Free delivery on orders above 149",
        "min_subtotal": Decimal("149.00"),
        "discount": Decimal("0.00"),
        "free_delivery": True,
    },
}


@dataclass(frozen=True)
class Quote:
    subtotal: Decimal
    delivery_fee: Decimal
    discount: Decimal
    tax: Decimal
    total: Decimal
    coupon_code: str | None


def money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def coupon_discount(code: str | None, subtotal: Decimal) -> tuple[Decimal, bool, str | None]:
    if not code:
        return Decimal("0.00"), False, None
    normalized = code.strip().upper()
    coupon = COUPONS.get(normalized)
    if coupon is None:
        raise BadRequestError("invalid coupon code")
    if subtotal < coupon["min_subtotal"]:
        raise BadRequestError(
            f"coupon {normalized} needs a minimum order of {coupon['min_subtotal']}"
        )
    if "percent" in coupon:
        discount = min(coupon["max_discount"], subtotal * coupon["percent"])
    else:
        discount = coupon["discount"]
    return money(discount), bool(coupon.get("free_delivery")), normalized


def quote(
    subtotal: Decimal,
    restaurant_delivery_fee: Decimal,
    coupon_code: str | None = None,
) -> Quote:
    subtotal = money(subtotal)
    delivery_fee = money(restaurant_delivery_fee)
    if subtotal >= FREE_DELIVERY_THRESHOLD:
        delivery_fee = Decimal("0.00")
    discount, free_delivery, normalized = coupon_discount(coupon_code, subtotal)
    if free_delivery:
        delivery_fee = Decimal("0.00")
    taxable = max(Decimal("0.00"), subtotal - discount)
    tax = money(taxable * TAX_RATE)
    total = money(taxable + delivery_fee + tax)
    return Quote(
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        discount=discount,
        tax=tax,
        total=total,
        coupon_code=normalized,
    )
