import { useEffect, useRef, useState } from "react";

import {
  ApiError,
  authOrderSocketUrl,
  cancelMyOrder,
  getMyOrder,
  getTracking,
  getTrackingRoute,
  reorder,
  reviewOrder,
  type Cart,
  type MarketOrder,
  type Tracking,
  type TrackingRoute,
} from "../../lib/api";
import {
  formatClock,
  formatCurrency,
  formatDateTime,
} from "../../lib/format";
import { navigate } from "../../lib/session";
import { RouteMap } from "../../components/RouteMap";
import {
  Btn,
  Modal,
  Notice,
  SimBadge,
  Spinner,
  StatusPill,
} from "../../components/market";

type TrackingMessage = {
  type?: string;
  order_id?: string;
  sent_at?: string;
  rider?: {
    id?: string;
    name?: string;
    lat?: number;
    lng?: number;
    location_source?: string;
    location_accuracy_m?: number | null;
    last_seen_at?: string | null;
  };
};

const terminal = new Set(["DELIVERED", "CANCELLED", "FAILED"]);
const steps = [
  { id: "PLACED", label: "Placed", hint: "Kitchen notified" },
  { id: "ACCEPTED", label: "Accepted", hint: "Order confirmed" },
  { id: "PREPARING", label: "Preparing", hint: "On the stove" },
  { id: "READY", label: "Ready", hint: "Waiting for rider" },
  { id: "PICKED_UP", label: "On the way", hint: "Rider has it" },
  { id: "DELIVERED", label: "Delivered", hint: "At your door" },
];

export function OrderDetailView({
  orderId,
  onCartUpdated,
}: {
  orderId: string;
  onCartUpdated: (cart: Cart) => void;
}) {
  const [order, setOrder] = useState<MarketOrder | null>(null);
  const [tracking, setTracking] = useState<Tracking | null>(null);
  const [route, setRoute] = useState<TrackingRoute | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState("Plans changed");
  const [rating, setRating] = useState(5);
  const [riderRating, setRiderRating] = useState(0);
  const [comment, setComment] = useState("");
  const [reviewError, setReviewError] = useState<string | null>(null);
  const mounted = useRef(true);
  const trackingRef = useRef<Tracking | null>(null);
  const lastRouteRequestAt = useRef(0);

  const refreshRoute = async (force = false) => {
    const now = Date.now();
    if (!force && now - lastRouteRequestAt.current < 12000) return;
    lastRouteRequestAt.current = now;
    try {
      const next = await getTrackingRoute(orderId);
      if (mounted.current) setRoute(next);
    } catch {
      // The map keeps the last valid route and can draw its local fallback.
    }
  };

  const load = async () => {
    const row = await getMyOrder(orderId);
    if (!mounted.current) return;
    setOrder(row);
    if (!terminal.has(row.status)) {
      try {
        const track = await getTracking(orderId);
        if (mounted.current) {
          trackingRef.current = track;
          setTracking(track);
          await refreshRoute(true);
        }
      } catch {
        // Tracking becomes useful once a rider is assigned; keep the last snapshot.
      }
    } else {
      try {
        const track = await getTracking(orderId);
        if (mounted.current) {
          trackingRef.current = track;
          setTracking(track);
        }
      } catch {
        if (mounted.current) {
          trackingRef.current = null;
          setTracking(null);
          setRoute(null);
        }
      }
    }
  };

  useEffect(() => {
    mounted.current = true;
    setLoading(true);
    setError(null);
    void load()
      .catch((err) => {
        if (mounted.current) {
          setError(err instanceof ApiError ? err.message : "Could not load this order.");
        }
      })
      .finally(() => {
        if (mounted.current) setLoading(false);
      });

    const timer = window.setInterval(() => {
      void load().catch(() => undefined);
    }, 12000);

    let socket: WebSocket | null = null;
    try {
      socket = new WebSocket(authOrderSocketUrl(orderId));
      socket.onmessage = (event) => {
        let message: TrackingMessage;
        try {
          message = JSON.parse(event.data as string) as TrackingMessage;
        } catch {
          void load().catch(() => undefined);
          return;
        }

        if (message.type === "heartbeat") return;
        if (message.type !== "rider_location" || message.rider?.lat == null || message.rider.lng == null) {
          void load().catch(() => undefined);
          return;
        }

        const current = trackingRef.current;
        if (!current || current.order_id !== message.order_id || !current.rider) {
          void load().catch(() => undefined);
          return;
        }

        const next: Tracking = {
          ...current,
          rider: {
            ...current.rider,
            lat: message.rider.lat,
            lng: message.rider.lng,
            location_source:
              message.rider.location_source ?? current.rider.location_source,
            location_accuracy_m:
              message.rider.location_accuracy_m ??
              current.rider.location_accuracy_m,
            last_seen_at:
              message.rider.last_seen_at ?? current.rider.last_seen_at,
          },
          points: [
            ...current.points,
            {
              lat: message.rider.lat,
              lng: message.rider.lng,
              created_at: message.sent_at ?? new Date().toISOString(),
            },
          ].slice(-100),
          simulated: message.rider.location_source !== "gps",
        };
        trackingRef.current = next;
        setTracking(next);
        void refreshRoute();
      };
    } catch {
      socket = null;
    }

    return () => {
      mounted.current = false;
      window.clearInterval(timer);
      socket?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orderId]);

  const cancel = async () => {
    setBusy("cancel");
    setError(null);
    try {
      const next = await cancelMyOrder(orderId, cancelReason);
      setOrder(next);
      setCancelOpen(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not cancel this order.");
    } finally {
      setBusy(null);
    }
  };

  const submitReview = async () => {
    setBusy("review");
    setReviewError(null);
    try {
      await reviewOrder(orderId, {
        restaurant_rating: rating,
        rider_rating: riderRating || undefined,
        comment: comment || undefined,
      });
      setReviewOpen(false);
      await load();
    } catch (err) {
      setReviewError(err instanceof ApiError ? err.message : "Could not save your review.");
    } finally {
      setBusy(null);
    }
  };

  const again = async () => {
    setBusy("again");
    try {
      onCartUpdated(await reorder(orderId));
      navigate("/customer/cart");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not rebuild that cart.");
    } finally {
      setBusy(null);
    }
  };

  if (loading && !order) return <Spinner label="Opening your order" />;
  if (!order) {
    return (
      <div className="mx-auto max-w-xl py-16 text-center">
        <p className="font-serif text-[28px] italic">This order is out of reach.</p>
        <p className="mt-2 text-sm text-stone-500">{error}</p>
        <Btn className="mt-5" onClick={() => navigate("/customer/orders")}>
          Back to orders
        </Btn>
      </div>
    );
  }

  const currentIndex = steps.findIndex((step) => step.id === order.status);
  const cancelled = order.status === "CANCELLED" || order.status === "FAILED";
  const delivered = order.status === "DELIVERED";
  const eta = tracking?.eta_minutes;
  const promised = order.promised_eta_at ?? tracking?.promised_eta_at ?? null;

  return (
    <div className="space-y-5">
      <button
        type="button"
        onClick={() => navigate("/customer/orders")}
        className="text-[11px] font-semibold uppercase tracking-[0.16em] text-stone-500 hover:text-stone-900"
      >
        ← All orders
      </button>

      {error ? <Notice>{error}</Notice> : null}

      <section className="relative overflow-hidden rounded-[30px] border border-stone-900/10 bg-[#171512] p-5 text-[#f8f3e9] sm:p-7">
        <div className="pointer-events-none absolute -right-20 -top-20 h-64 w-64 rounded-full bg-[radial-gradient(circle,rgba(217,79,43,0.45),transparent_62%)]" />
        <div className="relative flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <StatusPill status={order.status} />
              <span className="text-[10px] uppercase tracking-[0.16em] text-stone-500">
                {order.order_number ?? order.id.slice(0, 8)}
              </span>
            </div>
            <h1 className="mt-2 font-serif text-[38px] italic leading-none sm:text-[46px]">
              {order.restaurant_name}
            </h1>
            <p className="mt-2 text-[12px] text-stone-400">
              Placed {formatDateTime(order.placed_at)} · {order.items.length} lines ·{" "}
              {order.payment_method.replace("_DEMO", " demo").toLowerCase()}
            </p>
          </div>
          <div className="text-right">
            <p className="font-serif text-[34px] leading-none">
              {formatCurrency(order.total_amount)}
            </p>
            <p className="mt-1 text-[9px] uppercase tracking-[0.14em] text-stone-500">
              {order.payment_status.replaceAll("_", " ")}
            </p>
          </div>
        </div>

        {!cancelled ? (
          <div className="relative mt-6">
            <div className="flex items-center">
              {steps.map((step, index) => {
                const done = currentIndex >= index;
                return (
                  <div key={step.id} className="flex flex-1 items-center last:flex-none">
                    <div className="flex flex-col items-center gap-1.5">
                      <span
                        className={`flex h-6 w-6 items-center justify-center rounded-full border text-[9px] font-bold ${
                          done
                            ? "border-[#f4b942] bg-[#f4b942] text-stone-900"
                            : "border-white/20 text-stone-500"
                        }`}
                      >
                        {done ? "✓" : index + 1}
                      </span>
                      <span
                        className={`hidden text-[8px] font-semibold uppercase tracking-[0.1em] sm:block ${
                          done ? "text-[#f4b942]" : "text-stone-600"
                        }`}
                      >
                        {step.label}
                      </span>
                    </div>
                    {index < steps.length - 1 ? (
                      <span
                        className={`mx-1 h-px flex-1 sm:mx-2 ${
                          currentIndex > index ? "bg-[#f4b942]" : "bg-white/15"
                        }`}
                      />
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <p className="mt-4 rounded-xl border border-rose-400/20 bg-rose-400/10 px-3 py-2 text-[12px] text-rose-200">
            This order was {order.status.toLowerCase()}. No delivery is in progress.
          </p>
        )}
      </section>

      {!cancelled ? (
        <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
          {tracking ? (
            <RouteMap tracking={tracking} route={route} />
          ) : (
            <div className="flex min-h-[250px] flex-col items-center justify-center rounded-[24px] border border-dashed border-stone-900/15 bg-[#fffcf6]/40 p-6 text-center">
              <p className="font-serif text-[22px] italic text-stone-600">
                The route appears here when a rider joins.
              </p>
              <p className="mt-2 max-w-sm text-[11px] text-stone-500">
                The kitchen is moving through the order. Location pings will stream in
                once the delivery is assigned.
              </p>
            </div>
          )}

          <div className="space-y-3">
            <div className="rounded-[24px] border border-stone-900/10 bg-[#fffcf6] p-4">
              <div className="flex items-center justify-between">
                <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-stone-500">
                  Promise engine
                </p>
                <SimBadge />
              </div>
              <p className="mt-2 font-serif text-[38px] leading-none text-stone-900">
                {delivered
                  ? "Delivered"
                  : eta !== null && eta !== undefined
                    ? `${Math.round(eta)} min`
                    : "Calculating"}
              </p>
              <p className="mt-1 text-[11px] text-stone-500">
                {delivered && order.actual_delivery_at
                  ? `At your door ${formatClock(order.actual_delivery_at)}`
                  : tracking?.low_minutes != null && tracking?.high_minutes != null
                    ? `${Math.round(tracking.low_minutes)}–${Math.round(tracking.high_minutes)} min window`
                    : "A window appears once the kitchen and rider settle."}
              </p>
              {promised ? (
                <p className="mt-3 border-t border-stone-900/10 pt-2.5 text-[10px] uppercase tracking-[0.1em] text-stone-400">
                  Promised by {formatClock(promised)}
                </p>
              ) : null}
            </div>

            <div className="rounded-[24px] border border-stone-900/10 bg-[#fffcf6]/70 p-4">
              <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-stone-500">
                Delivery partner
              </p>
              {tracking?.rider ? (
                <>
                  <div className="mt-2 flex items-center gap-2.5">
                    <span className="flex h-9 w-9 items-center justify-center rounded-full bg-[#1f5b46] text-[11px] font-bold text-white">
                      {tracking.rider.name
                        .split(" ")
                        .map((part) => part[0])
                        .join("")
                        .slice(0, 2)}
                    </span>
                    <div>
                      <p className="text-[13px] font-semibold">{tracking.rider.name}</p>
                      <p className="text-[10px] text-stone-500">
                        {tracking.rider.vehicle.replaceAll("_", " ")}
                      </p>
                    </div>
                  </div>
                  <p className="mt-2 text-[10px] leading-relaxed text-stone-500">
                    {tracking.rider.location_source === "gps"
                      ? "Live GPS"
                      : "Simulated ping"}{" "}
                    {tracking.rider.last_seen_at
                      ? new Date(tracking.rider.last_seen_at).toLocaleTimeString("en-GB", {
                          hour: "2-digit",
                          minute: "2-digit",
                        })
                      : "pending"}
                    {tracking.rider.location_source === "gps" &&
                    tracking.rider.location_accuracy_m !== null
                      ? ` (+/- ${Math.round(tracking.rider.location_accuracy_m)} m)`
                      : ""}
                  </p>
                  {tracking.rider.phone ? (
                    <p className="mt-1 text-[11px] font-semibold">{tracking.rider.phone}</p>
                  ) : null}
                </>
              ) : (
                <p className="mt-2 text-[11px] leading-relaxed text-stone-500">
                  We are matching this order with the nearest rider. The promise updates
                  automatically when someone accepts.
                </p>
              )}
            </div>

            {!terminal.has(order.status) && order.status !== "PICKED_UP" ? (
              <Btn
                variant="outline"
                className="w-full"
                onClick={() => setCancelOpen(true)}
              >
                Cancel order
              </Btn>
            ) : null}
          </div>
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <section className="overflow-hidden rounded-[26px] border border-stone-900/10 bg-[#fffcf6]/70">
          <div className="border-b border-stone-900/8 px-4 py-3">
            <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-stone-500">
              Kitchen receipt
            </p>
          </div>
          {order.items.map((item, index) => (
            <div
              key={item.menu_item_id}
              className={`flex items-center justify-between gap-3 px-4 py-3 text-[12px] ${
                index > 0 ? "border-t border-stone-900/8" : ""
              }`}
            >
              <span>
                {item.name} <span className="text-stone-400">×{item.qty}</span>
              </span>
              <span className="font-semibold">
                {formatCurrency(Number(item.unit_price) * item.qty)}
              </span>
            </div>
          ))}
          <div className="space-y-2 border-t border-stone-900/10 bg-stone-900/[0.02] px-4 py-3 text-[11px]">
            <div className="flex justify-between text-stone-500">
              <span>Subtotal</span>
              <span>{formatCurrency(order.subtotal)}</span>
            </div>
            <div className="flex justify-between text-stone-500">
              <span>Delivery</span>
              <span>{formatCurrency(order.delivery_fee)}</span>
            </div>
            {Number(order.discount) > 0 ? (
              <div className="flex justify-between font-semibold text-[#1f5b46]">
                <span>Offer</span>
                <span>− {formatCurrency(order.discount)}</span>
              </div>
            ) : null}
            <div className="flex justify-between text-stone-500">
              <span>Tax</span>
              <span>{formatCurrency(order.tax)}</span>
            </div>
            <div className="flex justify-between border-t border-stone-900/10 pt-2 text-[14px] font-bold">
              <span>Paid / payable</span>
              <span>{formatCurrency(order.total_amount)}</span>
            </div>
          </div>
        </section>

        <div className="space-y-3">
          <section className="rounded-[24px] border border-stone-900/10 bg-[#fffcf6]/70 p-4">
            <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-stone-500">
              Dropping at
            </p>
            <p className="mt-2 text-[12px] font-semibold">
              {order.delivery_address ?? "Address on file"}
            </p>
            {order.customer_phone ? (
              <p className="mt-1 text-[10px] text-stone-500">{order.customer_phone}</p>
            ) : null}
            {order.delivery_instructions ? (
              <p className="mt-2 rounded-lg bg-[#f4b942]/15 px-2.5 py-2 text-[10px] leading-relaxed text-[#7d5309]">
                “{order.delivery_instructions}”
              </p>
            ) : null}
          </section>

          {order.status === "DELIVERED" ? (
            <section className="rounded-[24px] border border-[#1f5b46]/20 bg-[#1f5b46]/[0.06] p-4">
              <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-[#1f5b46]">
                {order.can_review ? "One last thing" : "Thank you"}
              </p>
              <p className="mt-1 font-serif text-[21px] italic">
                {order.can_review ? "How did dinner land?" : "Hope it hit the spot."}
              </p>
              {order.can_review ? (
                <Btn
                  size="sm"
                  className="mt-3 w-full"
                  onClick={() => setReviewOpen(true)}
                >
                  Rate this order
                </Btn>
              ) : null}
              <Btn
                size="sm"
                variant="outline"
                className="mt-2 w-full"
                disabled={busy === "again"}
                onClick={() => void again()}
              >
                {busy === "again" ? "Rebuilding…" : "Order it again"}
              </Btn>
            </section>
          ) : null}
        </div>
      </div>

      {reviewOpen ? (
        <Modal title="Tell us about dinner" onClose={() => setReviewOpen(false)}>
          <div className="space-y-4">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-stone-500">
                {order.restaurant_name}
              </p>
              <Stars value={rating} onChange={setRating} />
            </div>
            {tracking?.rider ? (
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-stone-500">
                  {tracking.rider.name} · optional
                </p>
                <Stars
                  value={riderRating}
                  onChange={(value) => setRiderRating(value === riderRating ? 0 : value)}
                />
              </div>
            ) : null}
            <label className="block">
              <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-[0.14em] text-stone-500">
                A note
              </span>
              <textarea
                value={comment}
                onChange={(event) => setComment(event.target.value)}
                rows={3}
                placeholder="Warm, fast, worth repeating…"
                className="w-full resize-none rounded-xl border border-stone-900/15 bg-white/70 px-3 py-2 text-[13px] outline-none focus:border-[#1f5b46]/50"
              />
            </label>
            {reviewError ? <Notice>{reviewError}</Notice> : null}
            <Btn
              className="w-full"
              disabled={busy === "review"}
              onClick={() => void submitReview()}
            >
              {busy === "review" ? "Saving…" : "Submit review"}
            </Btn>
          </div>
        </Modal>
      ) : null}

      {cancelOpen ? (
        <Modal title="Cancel this order?" onClose={() => setCancelOpen(false)}>
          <p className="text-sm leading-relaxed text-stone-600">
            The kitchen and rider will be notified. This cannot be undone.
          </p>
          <label className="mt-4 block">
            <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-[0.14em] text-stone-500">
              Reason
            </span>
            <input
              value={cancelReason}
              onChange={(event) => setCancelReason(event.target.value)}
              className="w-full rounded-xl border border-stone-900/15 bg-white/70 px-3 py-2 text-[13px] outline-none focus:border-[#d94f2b]/50"
            />
          </label>
          <div className="mt-5 flex gap-2">
            <Btn variant="outline" className="flex-1" onClick={() => setCancelOpen(false)}>
              Keep order
            </Btn>
            <Btn
              variant="danger"
              className="flex-1"
              disabled={busy === "cancel"}
              onClick={() => void cancel()}
            >
              {busy === "cancel" ? "Cancelling…" : "Cancel order"}
            </Btn>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}

function Stars({
  value,
  onChange,
}: {
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="mt-1.5 flex gap-1">
      {[1, 2, 3, 4, 5].map((star) => (
        <button
          key={star}
          type="button"
          onClick={() => onChange(star)}
          className={`text-[24px] leading-none transition ${
            star <= value ? "text-[#f4b942]" : "text-stone-300 hover:text-[#f4b942]/60"
          }`}
          aria-label={`${star} stars`}
        >
          ★
        </button>
      ))}
    </div>
  );
}
