import { useCallback, useEffect, useState } from "react";

import {
  Badge,
  Dot,
  EmptyState,
  ErrorNote,
  Loading,
  Panel,
  ScoreBar,
  SectionHeading,
  Stat,
  orderTone,
} from "../components/ui";
import {
  getOrderEvents,
  getOrders,
  getRestaurants,
} from "../lib/api";
import type { Order, OrderEvent, Restaurant } from "../lib/api";
import { formatClock, formatCurrency, shortId, timeAgo } from "../lib/format";
import { useOrderStream } from "../lib/useOrderStream";

function describeEvent(event: OrderEvent): string {
  const payload = event.payload as {
    to?: string;
    from?: string;
    reason?: string;
    flags?: string[];
    new_flags?: string[];
  };
  if (payload.reason) return payload.reason;
  if (payload.new_flags?.length) return `new flags: ${payload.new_flags.join(", ")}`;
  if (payload.flags?.length) return `flags: ${payload.flags.join(", ")}`;
  if (payload.to) return `${payload.from ?? "status"} to ${payload.to}`;
  return "order record";
}

function eventLabel(type: string): string {
  return type.replaceAll("_", " ");
}

export default function LiveBoard() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [restaurants, setRestaurants] = useState<Record<string, Restaurant>>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [events, setEvents] = useState<OrderEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const stream = useOrderStream(selectedId);

  const load = useCallback(async () => {
    try {
      const [rows, restaurantRows] = await Promise.all([
        getOrders(undefined, 80),
        getRestaurants(),
      ]);
      setOrders(rows);
      setRestaurants(
        Object.fromEntries(restaurantRows.map((restaurant) => [restaurant.id, restaurant])),
      );
      setSelectedId((current) =>
        current && rows.some((row) => row.id === current) ? current : rows[0]?.id ?? null,
      );
      setError(null);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not load orders");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 10_000);
    return () => window.clearInterval(timer);
  }, [load]);

  useEffect(() => {
    if (!selectedId) {
      setEvents([]);
      return;
    }
    let cancelled = false;
    getOrderEvents(selectedId)
      .then((rows) => {
        if (!cancelled) setEvents(rows);
      })
      .catch(() => {
        if (!cancelled) setEvents([]);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const base = orders.find((order) => order.id === selectedId) ?? null;
  const selected: Order | null =
    base && stream.orderId === selectedId && stream.order
      ? { ...base, ...stream.order }
      : base;
  const timeline =
    stream.orderId === selectedId && stream.events.length > 0 ? stream.events : events;

  const inFlight = orders.filter(
    (order) => !["DELIVERED", "CANCELLED", "FAILED"].includes(order.status),
  ).length;
  const ready = orders.filter((order) => order.status === "READY").length;
  const flagged = orders.filter((order) => order.delay_flags.length > 0).length;

  return (
    <div className="space-y-5">
      <SectionHeading
        title="Live order board"
        caption="Every transition streams over WebSocket as it happens."
        action={
          <Badge tone={stream.status === "live" ? "mint" : "amber"}>
            <Dot tone={stream.status === "live" ? "mint" : "amber"} />
            {stream.status === "live"
              ? "stream live"
              : stream.status === "reconnecting"
                ? "reconnecting"
                : "select an order"}
          </Badge>
        }
      />

      {error ? <ErrorNote message={error} /> : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="In flight" value={inFlight} hint="active orders in window" />
        <Stat label="Ready" value={ready} hint="waiting for a rider" tone="amber" />
        <Stat label="Flagged" value={flagged} hint="delay monitor flags" tone={flagged ? "rose" : "mint"} />
        <Stat
          label="Stream"
          value={stream.lastMessageAt ? formatClock(stream.lastMessageAt) : "--:--"}
          hint="last realtime message"
          tone={stream.status === "live" ? "mint" : "neutral"}
        />
      </div>

      {loading ? (
        <Loading label="Loading orders" />
      ) : orders.length === 0 ? (
        <EmptyState
          title="No orders yet"
          hint="Run the simulator or create an order through the API, then the board fills itself."
        />
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
          <Panel className="overflow-hidden">
            <div className="flex items-center justify-between border-b border-white/5 px-4 py-3">
              <p className="text-xs font-medium uppercase tracking-[0.18em] text-stone-500">
                Orders
              </p>
              <p className="font-mono text-xs text-stone-600">{orders.length} loaded</p>
            </div>
            <ul className="max-h-[620px] divide-y divide-white/5 overflow-y-auto">
              {orders.map((order) => {
                const restaurant = restaurants[order.restaurant_id];
                const active = order.id === selectedId;
                return (
                  <li key={order.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(order.id)}
                      className={`flex w-full items-start gap-3 px-4 py-3 text-left transition ${
                        active
                          ? "bg-emerald-400/[0.07]"
                          : "hover:bg-white/[0.03]"
                      }`}
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-mono text-xs text-stone-400">
                            #{shortId(order.id)}
                          </span>
                          <Badge tone={orderTone(order.status)}>{order.status}</Badge>
                        </div>
                        <p className="mt-1.5 truncate text-sm text-stone-200">
                          {restaurant?.name ?? "Unknown restaurant"}
                        </p>
                        <div className="mt-1 flex items-center gap-3 font-mono text-[11px] text-stone-500">
                          <span>{formatCurrency(order.total_price)}</span>
                          <span>{order.items.reduce((sum, item) => sum + item.qty, 0)} items</span>
                          <span>{timeAgo(order.placed_at)}</span>
                          {order.delay_flags.length > 0 ? (
                            <span className="text-rose-300">flagged</span>
                          ) : null}
                        </div>
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          </Panel>

          <div className="space-y-4">
            <Panel className="p-5">
              {selected ? (
                <>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-stone-500">
                        order #{shortId(selected.id)}
                      </p>
                      <h3 className="mt-1 font-serif text-2xl italic text-stone-100">
                        {restaurants[selected.restaurant_id]?.name ?? "Order detail"}
                      </h3>
                    </div>
                    <div className="flex flex-col items-end gap-1.5">
                      <Badge tone={orderTone(selected.status)}>{selected.status}</Badge>
                      <span className="font-mono text-xs text-stone-500">
                        {formatCurrency(selected.total_price)}
                      </span>
                    </div>
                  </div>

                  <div className="mt-5 grid grid-cols-2 gap-3 text-sm">
                    <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
                      <p className="text-[10px] uppercase tracking-[0.16em] text-stone-500">
                        Promised ETA
                      </p>
                      <p className="mt-1 font-mono text-stone-200">
                        {formatClock(selected.promised_eta_at)}
                      </p>
                    </div>
                    <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
                      <p className="text-[10px] uppercase tracking-[0.16em] text-stone-500">
                        Deadline
                      </p>
                      <p className="mt-1 font-mono text-stone-200">
                        {formatClock(selected.deadline_at)}
                      </p>
                    </div>
                    <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
                      <p className="text-[10px] uppercase tracking-[0.16em] text-stone-500">
                        Rider
                      </p>
                      <p className="mt-1 truncate font-mono text-stone-200">
                        {selected.rider_id ? `#${shortId(selected.rider_id)}` : "unassigned"}
                      </p>
                    </div>
                    <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
                      <p className="text-[10px] uppercase tracking-[0.16em] text-stone-500">
                        Drop
                      </p>
                      <p className="mt-1 font-mono text-stone-200">
                        {selected.drop_lat.toFixed(3)}, {selected.drop_lng.toFixed(3)}
                      </p>
                    </div>
                  </div>

                  {selected.delay_flags.length > 0 ? (
                    <div className="mt-4 flex flex-wrap gap-1.5">
                      {selected.delay_flags.map((flag) => (
                        <Badge key={flag} tone="rose">
                          {flag}
                        </Badge>
                      ))}
                    </div>
                  ) : null}

                  <div className="mt-5">
                    <p className="text-[10px] uppercase tracking-[0.16em] text-stone-500">
                      Items
                    </p>
                    <ul className="mt-2 divide-y divide-white/5">
                      {selected.items.map((item) => (
                        <li
                          key={item.menu_item_id}
                          className="flex items-center justify-between py-1.5 text-sm"
                        >
                          <span className="text-stone-300">
                            {item.qty} x {item.name}
                          </span>
                          <span className="font-mono text-xs text-stone-500">
                            {formatCurrency(Number(item.unit_price) * item.qty)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  <div className="mt-5 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-white/5 bg-white/[0.02] px-3 py-2.5">
                    <div className="flex items-center gap-2 text-xs text-stone-400">
                      <Dot tone={stream.rider ? "mint" : "neutral"} />
                      {stream.rider
                        ? `${stream.rider.name} - ${
                            stream.rider.location_source === "gps"
                              ? "live GPS"
                              : "simulated"
                          } at ${stream.rider.lat.toFixed(3)}, ${stream.rider.lng.toFixed(3)}${
                            stream.rider.location_accuracy_m !== null
                              ? ` (+/- ${Math.round(stream.rider.location_accuracy_m)} m)`
                              : ""
                          }`
                        : "no live rider telemetry"}
                    </div>
                    <span className="font-mono text-[11px] text-stone-600">
                      {stream.lastMessageAt ? timeAgo(stream.lastMessageAt) : "waiting"}
                    </span>
                  </div>

                  <div className="mt-5">
                    <div className="flex items-center justify-between">
                      <p className="text-[10px] uppercase tracking-[0.16em] text-stone-500">
                        Event stream
                      </p>
                      <span className="font-mono text-[11px] text-stone-600">
                        {timeline.length} events
                      </span>
                    </div>
                    <ol className="mt-3 max-h-56 space-y-3 overflow-y-auto border-l border-white/10 pl-4">
                      {timeline
                        .slice()
                        .reverse()
                        .slice(0, 14)
                        .map((event) => (
                          <li key={event.id} className="relative">
                            <span className="absolute -left-[21px] top-1.5 h-1.5 w-1.5 rounded-full bg-emerald-400/70" />
                            <div className="flex items-baseline justify-between gap-3">
                              <p className="text-sm capitalize text-stone-300">
                                {eventLabel(event.type)}
                              </p>
                              <span className="shrink-0 font-mono text-[11px] text-stone-600">
                                {formatClock(event.created_at)}
                              </span>
                            </div>
                            <p className="mt-0.5 text-xs text-stone-500">
                              {describeEvent(event)}
                            </p>
                          </li>
                        ))}
                    </ol>
                  </div>
                </>
              ) : (
                <EmptyState title="Nothing selected" hint="Pick an order on the left." />
              )}
            </Panel>

            {selected ? (
              <Panel className="p-5">
                <p className="text-[10px] uppercase tracking-[0.16em] text-stone-500">
                  Order confidence
                </p>
                <div className="mt-3 space-y-3">
                  <div>
                    <div className="flex items-center justify-between text-xs text-stone-500">
                      <span>Activity coverage</span>
                      <span className="font-mono">
                        {Math.min(100, timeline.length * 12)}%
                      </span>
                    </div>
                    <div className="mt-1.5">
                      <ScoreBar value={Math.min(1, timeline.length / 8)} />
                    </div>
                  </div>
                  <p className="text-xs leading-relaxed text-stone-500">
                    Promised timings and delay flags are generated from simulated city
                    traffic and kitchen load.
                  </p>
                </div>
              </Panel>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
