import { useEffect, useState } from "react";

import {
  ApiError,
  applyCoupon,
  clearCoupon,
  getCoupons,
  removeCartItem,
  updateCartItem,
  type Cart,
  type Coupon,
} from "../../lib/api";
import { formatCurrency } from "../../lib/format";
import { navigate } from "../../lib/session";
import {
  Btn,
  Empty,
  Notice,
  ProductArt,
  SimBadge,
} from "../../components/market";

export function CartView({
  cart,
  onCartUpdated,
}: {
  cart: Cart | null;
  onCartUpdated: (cart: Cart) => void;
}) {
  const [coupons, setCoupons] = useState<Coupon[]>([]);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void getCoupons()
      .then(setCoupons)
      .catch(() => undefined);
  }, []);

  if (!cart || cart.items.length === 0) {
    return (
      <Empty
        title="Your cart is taking a breather."
        hint="Browse a kitchen, follow a craving, and build something worth waiting for."
        action={<Btn onClick={() => navigate("/customer")}>Find dinner</Btn>}
      />
    );
  }

  const restaurant = cart.restaurant;
  const belowMinimum =
    restaurant !== null && Number(cart.subtotal) < Number(restaurant.min_order_value);

  const setQty = async (lineId: string, qty: number) => {
    setBusy(lineId);
    setError(null);
    try {
      const next = qty <= 0 ? await removeCartItem(lineId) : await updateCartItem(lineId, qty);
      onCartUpdated(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update the cart.");
    } finally {
      setBusy(null);
    }
  };

  const apply = async (value: string) => {
    setBusy("coupon");
    setError(null);
    try {
      const next = await applyCoupon(value);
      onCartUpdated(next);
      setCode("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That offer could not be applied.");
    } finally {
      setBusy(null);
    }
  };

  const removeOffer = async () => {
    setBusy("coupon");
    try {
      onCartUpdated(await clearCoupon());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not remove the offer.");
    } finally {
      setBusy(null);
    }
  };

  const clearAll = async () => {
    setBusy("clear");
    setError(null);
    try {
      let next = cart;
      for (const line of cart.items) {
        next = await removeCartItem(line.id);
      }
      onCartUpdated(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not clear the cart.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500">
            Almost there
          </p>
          <h1 className="mt-1 font-serif text-[36px] italic leading-none">
            One kitchen. One good decision.
          </h1>
          {restaurant ? (
            <button
              type="button"
              onClick={() => navigate(`/customer/restaurants/${restaurant.id}`)}
              className="mt-2 text-[11px] font-semibold text-stone-500 hover:text-[#d94f2b]"
            >
              {restaurant.name} · add more →
            </button>
          ) : null}
        </div>
        <button
          type="button"
          onClick={() => void clearAll()}
          disabled={busy === "clear"}
          className="text-[11px] font-semibold text-stone-400 hover:text-rose-700"
        >
          {busy === "clear" ? "Clearing…" : "Clear cart"}
        </button>
      </div>

      {error ? <Notice>{error}</Notice> : null}

      <div className="grid gap-5 lg:grid-cols-[1fr_360px] lg:items-start">
        <div className="space-y-4">
          <div className="overflow-hidden rounded-[26px] border border-stone-900/10 bg-[#fffcf6]/70">
            {cart.items.map((line, index) => (
              <div
                key={line.id}
                className={`flex items-center gap-3 p-4 ${
                  index > 0 ? "border-t border-stone-900/8" : ""
                }`}
              >
                <span
                  className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl font-serif text-[18px] italic ${
                    line.veg
                      ? "bg-[#1f5b46]/10 text-[#1f5b46]"
                      : "bg-[#d94f2b]/10 text-[#a83a1e]"
                  }`}
                >
                  {line.veg ? "V" : "N"}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[14px] font-semibold">{line.name}</p>
                  <p className="mt-0.5 text-[11px] text-stone-500">
                    {formatCurrency(line.price)} each
                    {line.original_price ? (
                      <span className="ml-1.5 text-stone-400 line-through">
                        {formatCurrency(line.original_price)}
                      </span>
                    ) : null}
                    {line.rescue_listing_id ? (
                      <span className="ml-1.5 rounded-full bg-[#1f5b46] px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-[0.08em] text-white">
                        Rescue price · locks at checkout
                      </span>
                    ) : null}
                    {line.kcal ? (
                      <span className="ml-1.5 text-[10px] text-[#7d5309]">
                        {line.kcal * line.qty} kcal
                      </span>
                    ) : null}
                    {!line.available ? (
                      <span className="ml-2 font-semibold text-rose-700">
                        Currently unavailable
                      </span>
                    ) : null}
                  </p>
                </div>
                <div className="flex items-center rounded-full border border-stone-900/15 bg-white/70">
                  <button
                    type="button"
                    disabled={busy === line.id}
                    onClick={() => void setQty(line.id, line.qty - 1)}
                    className="px-2.5 py-1.5 text-[14px] text-stone-500 hover:text-stone-900"
                  >
                    −
                  </button>
                  <span className="min-w-5 text-center text-[12px] font-bold">
                    {line.qty}
                  </span>
                  <button
                    type="button"
                    disabled={busy === line.id || line.qty >= 20}
                    onClick={() => void setQty(line.id, line.qty + 1)}
                    className="px-2.5 py-1.5 text-[14px] text-stone-500 hover:text-stone-900 disabled:opacity-30"
                  >
                    +
                  </button>
                </div>
                <p className="w-16 text-right text-[13px] font-semibold">
                  {formatCurrency(line.line_total)}
                </p>
              </div>
            ))}
          </div>

          <section className="rounded-[26px] border border-stone-900/10 bg-[#fffcf6]/70 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-stone-500">
                  Offers worth using
                </p>
                <h2 className="mt-1 font-serif text-[23px] italic">A little off, on us</h2>
              </div>
              <SimBadge />
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-3">
              {coupons.map((coupon) => (
                <button
                  key={coupon.code}
                  type="button"
                  disabled={busy === "coupon"}
                  onClick={() => void apply(coupon.code)}
                  className={`rounded-2xl border p-3 text-left transition hover:-translate-y-0.5 ${
                    cart.coupon_code === coupon.code
                      ? "border-[#1f5b46] bg-[#1f5b46]/8"
                      : "border-stone-900/10 bg-white/40 hover:bg-white"
                  }`}
                >
                  <p className="text-[11px] font-bold tracking-[0.08em]">{coupon.code}</p>
                  <p className="mt-1 text-[10px] leading-snug text-stone-500">
                    {coupon.description}
                  </p>
                </button>
              ))}
            </div>
            <div className="mt-3 flex gap-2">
              <input
                value={code}
                onChange={(event) => setCode(event.target.value.toUpperCase())}
                placeholder="Have another code?"
                className="min-w-0 flex-1 rounded-full border border-stone-900/15 bg-white/60 px-3.5 py-2 text-[12px] outline-none focus:border-[#1f5b46]/50"
              />
              <Btn
                size="sm"
                variant="dark"
                disabled={!code.trim() || busy === "coupon"}
                onClick={() => void apply(code.trim())}
              >
                Apply
              </Btn>
            </div>
            {cart.coupon_code ? (
              <div className="mt-3 flex items-center justify-between rounded-xl bg-[#1f5b46]/8 px-3 py-2 text-[11px]">
                <span className="font-semibold text-[#1f5b46]">
                  {cart.coupon_code} applied
                </span>
                <button
                  type="button"
                  onClick={() => void removeOffer()}
                  className="text-stone-500 hover:text-rose-700"
                >
                  Remove
                </button>
              </div>
            ) : null}
          </section>
        </div>

        <aside className="rounded-[26px] border border-stone-900/10 bg-[#fffcf6] p-5 shadow-[0_28px_70px_-50px_rgba(28,25,23,0.7)] lg:sticky lg:top-24">
          <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-stone-500">
            The bill
          </p>
          <h2 className="mt-1 font-serif text-[25px] italic">No surprises</h2>
          <div className="mt-4 space-y-2.5 text-[12px]">
            <Row label={`Subtotal · ${cart.item_count} items`} value={formatCurrency(cart.subtotal)} />
            <Row label="Delivery fee" value={formatCurrency(cart.delivery_fee)} />
            {Number(cart.discount) > 0 ? (
              <Row
                label={`Offer ${cart.coupon_code ?? ""}`}
                value={`− ${formatCurrency(cart.discount)}`}
                tone="green"
              />
            ) : null}
            <Row label="Tax" value={formatCurrency(cart.tax)} />
            <div className="border-t border-stone-900/10 pt-3">
              <Row label="Total" value={formatCurrency(cart.total)} strong />
            </div>
            <p className="text-[10px] text-stone-400">
              No platform fee, no surge, no rain fee. Menu prices match the kitchen&apos;s own.
            </p>
            {Number(cart.rescue_saving ?? 0) > 0 ? (
              <Row
                label="Saved by rescuing surplus food"
                value={formatCurrency(cart.rescue_saving ?? 0)}
                tone="green"
              />
            ) : null}
          </div>
          {cart.nutrition ? (
            <div className="mt-4 rounded-2xl border border-[#f4b942]/40 bg-[#f4b942]/10 p-3">
              <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-[#8a5b0a]">
                This order, estimated
              </p>
              <p className="mt-1 font-serif text-[22px] leading-none">
                {Math.round(cart.nutrition.kcal)} kcal
              </p>
              <p className="mt-1 text-[11px] text-stone-600">
                {cart.nutrition.protein_g} g protein · {cart.nutrition.carbs_g} g carbs ·{" "}
                {cart.nutrition.fat_g} g fat
              </p>
              {cart.nutrition.allergens.length ? (
                <p className="mt-1 text-[10px] text-rose-800">
                  Contains: {cart.nutrition.allergens.join(", ")}
                </p>
              ) : null}
              <p className="mt-1 text-[9px] text-stone-400">
                Scaled to each dish&apos;s declared or measured portion.
              </p>
            </div>
          ) : null}

          {belowMinimum && restaurant ? (
            <div className="mt-4">
              <Notice tone="info">
                Add {formatCurrency(Number(restaurant.min_order_value) - Number(cart.subtotal))}{" "}
                more to reach this kitchen&apos;s minimum order.
              </Notice>
            </div>
          ) : null}

          <Btn
            size="lg"
            className="mt-4 w-full"
            disabled={belowMinimum}
            onClick={() => navigate("/customer/checkout")}
          >
            Review &amp; checkout →
          </Btn>
          <p className="mt-3 text-center text-[10px] leading-relaxed text-stone-400">
            Payment is simulated. ETA is generated by the FoodFlow promise engine and is
            not a guarantee.
          </p>
        </aside>
      </div>

      {restaurant ? (
        <div className="hidden overflow-hidden rounded-[26px] border border-stone-900/10 lg:block">
          <ProductArt
            cuisine={[]}
            name={restaurant.name}
            className="h-[120px]"
          />
        </div>
      ) : null}
    </div>
  );
}

function Row({
  label,
  value,
  strong,
  tone,
}: {
  label: string;
  value: string;
  strong?: boolean;
  tone?: "green";
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className={`${strong ? "font-semibold text-stone-900" : "text-stone-500"}`}>
        {label}
      </span>
      <span
        className={`${strong ? "text-[16px] font-bold" : ""} ${
          tone === "green" ? "font-semibold text-[#1f5b46]" : ""
        }`}
      >
        {value}
      </span>
    </div>
  );
}
