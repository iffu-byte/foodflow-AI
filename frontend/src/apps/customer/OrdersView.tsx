import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  getMyOrders,
  reorder,
  type Cart,
  type MarketOrder,
} from "../../lib/api";
import { formatCurrency, formatDateTime } from "../../lib/format";
import { navigate } from "../../lib/session";
import {
  Btn,
  Empty,
  Notice,
  Spinner,
  StatusPill,
} from "../../components/market";

const terminal = new Set(["DELIVERED", "CANCELLED", "FAILED"]);

export function OrdersView({
  onCartUpdated,
}: {
  onCartUpdated: (cart: Cart) => void;
}) {
  const [orders, setOrders] = useState<MarketOrder[]>([]);
  const [tab, setTab] = useState<"active" | "past">("active");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    void getMyOrders()
      .then((rows) => {
        setOrders(rows);
        if (!rows.some((row) => !terminal.has(row.status))) setTab("past");
      })
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : "Could not load your orders.");
      })
      .finally(() => setLoading(false));
  }, []);

  const visible = useMemo(
    () =>
      orders.filter((order) =>
        tab === "active" ? !terminal.has(order.status) : terminal.has(order.status),
      ),
    [orders, tab],
  );

  const activeCount = orders.filter((order) => !terminal.has(order.status)).length;

  const again = async (orderId: string) => {
    setBusy(orderId);
    setError(null);
    try {
      onCartUpdated(await reorder(orderId));
      navigate("/customer/cart");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not rebuild that cart.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500">
            Your table history
          </p>
          <h1 className="mt-1 font-serif text-[38px] italic leading-none">
            Orders, remembered.
          </h1>
        </div>
        <div className="flex rounded-full border border-stone-900/10 bg-white/40 p-1">
          {[
            { id: "active" as const, label: `Active${activeCount ? ` · ${activeCount}` : ""}` },
            { id: "past" as const, label: "Past" },
          ].map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              className={`rounded-full px-4 py-1.5 text-[11px] font-semibold transition ${
                tab === item.id
                  ? "bg-stone-900 text-[#f8f3e9]"
                  : "text-stone-500 hover:text-stone-900"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {error ? <Notice>{error}</Notice> : null}
      {loading ? <Spinner label="Finding your orders" /> : null}

      {!loading && visible.length === 0 ? (
        <Empty
          title={tab === "active" ? "Nothing on the way right now." : "No past orders yet."}
          hint={
            tab === "active"
              ? "The next great dinner is one kitchen away."
              : "Finish your first order and it will live here."
          }
          action={<Btn onClick={() => navigate("/customer")}>Browse kitchens</Btn>}
        />
      ) : null}

      <div className="space-y-3">
        {visible.map((order) => (
          <article
            key={order.id}
            className="overflow-hidden rounded-[24px] border border-stone-900/10 bg-[#fffcf6]/70"
          >
            <div className="flex flex-wrap items-start gap-3 p-4 sm:p-5">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[#1f5b46] font-serif text-[20px] italic text-[#f1f7ef]">
                {order.restaurant_name.slice(0, 1)}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="font-serif text-[21px] italic leading-none">
                    {order.restaurant_name}
                  </h2>
                  <StatusPill status={order.status} />
                </div>
                <p className="mt-1.5 text-[11px] text-stone-500">
                  {order.order_number ?? order.id.slice(0, 8)} ·{" "}
                  {formatDateTime(order.placed_at)} · {order.items.length} lines
                </p>
                <p className="mt-1 line-clamp-1 text-[11px] text-stone-500">
                  {order.items.map((item) => `${item.name} ×${item.qty}`).join(", ")}
                </p>
              </div>
              <div className="text-right">
                <p className="font-serif text-[22px] leading-none">
                  {formatCurrency(order.total_amount)}
                </p>
                <p className="mt-1 text-[9px] uppercase tracking-[0.12em] text-stone-400">
                  {order.payment_method.replace("_DEMO", " demo").toLowerCase()}
                </p>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2 border-t border-stone-900/8 bg-stone-900/[0.02] px-4 py-2.5 sm:px-5">
              <span className="text-[10px] text-stone-500">
                {order.status === "DELIVERED"
                  ? order.can_review
                    ? "How was it?"
                    : "Delivered. Thanks for ordering."
                  : order.promised_eta_at
                    ? `Promised by ${new Date(order.promised_eta_at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}`
                    : "Finding the right promise…"}
              </span>
              <div className="ml-auto flex items-center gap-2">
                {order.can_review ? (
                  <Btn
                    size="sm"
                    variant="outline"
                    onClick={() => navigate(`/customer/orders/${order.id}`)}
                  >
                    Rate order
                  </Btn>
                ) : null}
                <Btn
                  size="sm"
                  variant="ghost"
                  onClick={() => navigate(`/customer/orders/${order.id}`)}
                >
                  {terminal.has(order.status) ? "Receipt →" : "Track →"}
                </Btn>
                {terminal.has(order.status) ? (
                  <Btn
                    size="sm"
                    variant="outline"
                    disabled={busy === order.id}
                    onClick={() => void again(order.id)}
                  >
                    {busy === order.id ? "…" : "Order again"}
                  </Btn>
                ) : null}
              </div>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
