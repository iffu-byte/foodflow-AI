import { useEffect, useState } from "react";

import {
  ApiError,
  checkout as placeOrder,
  getAddresses,
  getProfile,
  type Address,
  type Cart,
} from "../../lib/api";
import { formatCurrency } from "../../lib/format";
import { navigate } from "../../lib/session";
import { AddressModal } from "../../components/AddressModal";
import {
  Btn,
  Empty,
  Notice,
  SimBadge,
  Spinner,
} from "../../components/market";

export function CheckoutView({
  cart,
  onOrderPlaced,
}: {
  cart: Cart | null;
  onOrderPlaced: () => void;
}) {
  const [addresses, setAddresses] = useState<Address[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [phone, setPhone] = useState("");
  const [instructions, setInstructions] = useState("");
  const [payment, setPayment] = useState<"COD" | "UPI_DEMO">("UPI_DEMO");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAddress, setShowAddress] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getAddresses(), getProfile()])
      .then(([rows, me]) => {
        if (cancelled) return;
        setAddresses(rows);
        setPhone(me.phone ?? "");
        const preferred = rows.find((row) => row.is_default) ?? rows[0];
        setSelected(preferred?.id ?? null);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Could not load checkout.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!cart || cart.items.length === 0) {
    return (
      <Empty
        title="There is nothing to check out."
        hint="Your cart is empty. Start with a kitchen that sounds right."
        action={<Btn onClick={() => navigate("/customer")}>Find dinner</Btn>}
      />
    );
  }

  if (loading) return <Spinner label="Preparing checkout" />;

  const selectedAddress = addresses.find((address) => address.id === selected) ?? null;

  const submit = async () => {
    if (!selectedAddress) {
      setError("Choose a delivery address first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const order = await placeOrder({
        address_id: selectedAddress.id,
        phone: phone || undefined,
        instructions: instructions || undefined,
        payment_method: payment,
        coupon_code: cart.coupon_code,
      });
      onOrderPlaced();
      navigate(`/customer/orders/${order.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not place this order.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <button
        type="button"
        onClick={() => navigate("/customer/cart")}
        className="text-[11px] font-semibold uppercase tracking-[0.16em] text-stone-500 hover:text-stone-900"
      >
        ← Back to cart
      </button>

      <div>
        <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500">
          Last check
        </p>
        <h1 className="mt-1 font-serif text-[38px] italic leading-none">
          Where should it land?
        </h1>
      </div>

      {error ? <Notice>{error}</Notice> : null}

      <div className="grid gap-5 lg:grid-cols-[1fr_360px] lg:items-start">
        <div className="space-y-4">
          <section className="rounded-[26px] border border-stone-900/10 bg-[#fffcf6]/70 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-stone-500">
                  Delivery address
                </p>
                <h2 className="mt-1 font-serif text-[23px] italic">Pick a doorstep</h2>
              </div>
              <Btn size="sm" variant="outline" onClick={() => setShowAddress(true)}>
                + New
              </Btn>
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {addresses.map((address) => (
                <button
                  key={address.id}
                  type="button"
                  onClick={() => setSelected(address.id)}
                  className={`rounded-2xl border p-3 text-left transition ${
                    selected === address.id
                      ? "border-[#1f5b46] bg-[#1f5b46]/[0.06] ring-1 ring-[#1f5b46]/30"
                      : "border-stone-900/10 bg-white/40 hover:bg-white"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] font-bold uppercase tracking-[0.12em]">
                      {address.label}
                    </span>
                    <span className="flex items-center gap-2">
                      {address.is_default ? (
                        <span className="rounded-full bg-[#f4b942]/25 px-2 py-0.5 text-[8px] font-bold uppercase tracking-[0.1em] text-[#7d5309]">
                          Default
                        </span>
                      ) : null}
                      <span
                        className={`flex h-3.5 w-3.5 items-center justify-center rounded-full border ${
                          selected === address.id
                            ? "border-[#1f5b46]"
                            : "border-stone-400"
                        }`}
                      >
                        {selected === address.id ? (
                          <span className="h-1.5 w-1.5 rounded-full bg-[#1f5b46]" />
                        ) : null}
                      </span>
                    </span>
                  </div>
                  <p className="mt-1.5 text-[12px] leading-snug text-stone-600">
                    {address.line1}
                    {address.line2 ? `, ${address.line2}` : ""}
                  </p>
                  <p className="mt-0.5 text-[10px] uppercase tracking-[0.1em] text-stone-400">
                    {address.city} · {address.lat.toFixed(3)}, {address.lng.toFixed(3)}
                  </p>
                  {address.phone ? (
                    <p className="mt-1 text-[10px] text-stone-400">{address.phone}</p>
                  ) : null}
                </button>
              ))}
              {addresses.length === 0 ? (
                <div className="sm:col-span-2">
                  <Empty
                    title="No saved addresses."
                    hint="Add a doorstep to continue with this order."
                    action={<Btn onClick={() => setShowAddress(true)}>Add address</Btn>}
                  />
                </div>
              ) : null}
            </div>
          </section>

          <section className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-[24px] border border-stone-900/10 bg-[#fffcf6]/70 p-4">
              <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-stone-500">
                Contact
              </p>
              <h3 className="mt-1 font-serif text-[21px] italic">For the rider</h3>
              <label className="mt-3 block">
                <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-[0.12em] text-stone-500">
                  Phone
                </span>
                <input
                  value={phone}
                  onChange={(event) => setPhone(event.target.value)}
                  placeholder="+91…"
                  className="w-full rounded-xl border border-stone-900/15 bg-white/70 px-3 py-2 text-[13px] outline-none focus:border-[#1f5b46]/50"
                />
              </label>
            </div>
            <div className="rounded-[24px] border border-stone-900/10 bg-[#fffcf6]/70 p-4">
              <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-stone-500">
                Kitchen note
              </p>
              <h3 className="mt-1 font-serif text-[21px] italic">Anything we should know?</h3>
              <textarea
                value={instructions}
                onChange={(event) => setInstructions(event.target.value)}
                placeholder="Less spice, leave at the door, call on arrival…"
                rows={3}
                className="mt-3 w-full resize-none rounded-xl border border-stone-900/15 bg-white/70 px-3 py-2 text-[13px] outline-none focus:border-[#1f5b46]/50"
              />
            </div>
          </section>

          <section className="rounded-[24px] border border-stone-900/10 bg-[#fffcf6]/70 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-stone-500">
                  Payment
                </p>
                <h3 className="mt-1 font-serif text-[21px] italic">Demo money only</h3>
              </div>
              <SimBadge />
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {[
                {
                  id: "UPI_DEMO" as const,
                  label: "UPI · demo",
                  hint: "Marked paid instantly",
                  glyph: "₹",
                },
                {
                  id: "COD" as const,
                  label: "Cash on delivery",
                  hint: "Payment stays pending",
                  glyph: "◐",
                },
              ].map((method) => (
                <button
                  key={method.id}
                  type="button"
                  onClick={() => setPayment(method.id)}
                  className={`flex items-center gap-3 rounded-2xl border p-3 text-left transition ${
                    payment === method.id
                      ? "border-[#d94f2b] bg-[#d94f2b]/[0.05] ring-1 ring-[#d94f2b]/25"
                      : "border-stone-900/10 bg-white/40 hover:bg-white"
                  }`}
                >
                  <span className="flex h-8 w-8 items-center justify-center rounded-full bg-stone-900 text-[12px] text-[#f8f3e9]">
                    {method.glyph}
                  </span>
                  <span>
                    <span className="block text-[12px] font-semibold">{method.label}</span>
                    <span className="text-[10px] text-stone-500">{method.hint}</span>
                  </span>
                </button>
              ))}
            </div>
          </section>
        </div>

        <aside className="rounded-[26px] border border-stone-900/10 bg-[#fffcf6] p-5 shadow-[0_28px_70px_-50px_rgba(28,25,23,0.7)] lg:sticky lg:top-24">
          <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-stone-500">
            {cart.restaurant?.name ?? "Your order"}
          </p>
          <h2 className="mt-1 font-serif text-[25px] italic">The final bill</h2>
          <div className="mt-4 max-h-52 space-y-2 overflow-y-auto pr-1">
            {cart.items.map((line) => (
              <div key={line.id} className="flex items-start justify-between gap-3 text-[12px]">
                <span className="text-stone-600">
                  {line.name} <span className="text-stone-400">×{line.qty}</span>
                </span>
                <span className="font-semibold">{formatCurrency(line.line_total)}</span>
              </div>
            ))}
          </div>
          <div className="mt-3 space-y-2 border-t border-stone-900/10 pt-3 text-[12px]">
            <div className="flex justify-between text-stone-500">
              <span>Subtotal</span>
              <span>{formatCurrency(cart.subtotal)}</span>
            </div>
            <div className="flex justify-between text-stone-500">
              <span>Delivery</span>
              <span>{formatCurrency(cart.delivery_fee)}</span>
            </div>
            {Number(cart.discount) > 0 ? (
              <div className="flex justify-between font-semibold text-[#1f5b46]">
                <span>{cart.coupon_code}</span>
                <span>− {formatCurrency(cart.discount)}</span>
              </div>
            ) : null}
            <div className="flex justify-between text-stone-500">
              <span>Tax</span>
              <span>{formatCurrency(cart.tax)}</span>
            </div>
            <div className="flex items-center justify-between border-t border-stone-900/10 pt-3">
              <span className="font-semibold">Total</span>
              <span className="text-[19px] font-bold">{formatCurrency(cart.total)}</span>
            </div>
          </div>
          <Btn
            size="lg"
            className="mt-4 w-full"
            disabled={busy || !selectedAddress}
            onClick={() => void submit()}
          >
            {busy ? "Placing order…" : "Place order"}
          </Btn>
          <p className="mt-3 text-center text-[10px] leading-relaxed text-stone-400">
            Promised ETA is a simulated prediction based on kitchen load and city traffic.
          </p>
        </aside>
      </div>

      {showAddress ? (
        <AddressModal
          onClose={() => setShowAddress(false)}
          onSaved={(address) => {
            setAddresses((rows) => [...rows, address]);
            setSelected(address.id);
          }}
        />
      ) : null}
    </div>
  );
}
