import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiError,
  getManagerMenu,
  getManagerRestaurant,
  getRestaurantAnalytics,
  getRestaurantOrders,
  getTracking,
  getTrackingRoute,
  patchManagerMenuItem,
  restaurantOrderSocketUrl,
  restaurantOrderAction,
  type AuthUser,
  type BrowseMenuItem,
  type BrowseRestaurant,
  type LiveRiderLocation,
  type MarketOrder,
  type RestaurantAnalytics,
  type Tracking,
  type TrackingRoute,
} from "../lib/api";
import { RouteMap } from "../components/RouteMap";
import {
  formatCurrency,
  formatDateTime,
  timeAgo,
} from "../lib/format";
import {
  Btn,
  Empty,
  Field,
  MarketShell,
  Modal,
  Notice,
  ProductArt,
  SimBadge,
  Spinner,
  StatCard,
  StatusPill,
  type NavItem,
} from "../components/market";

type Tab = "board" | "menu" | "insights";
type SyncStatus = "connecting" | "live" | "reconnecting";

type RestaurantStreamMessage =
  | { type: "restaurant_ready"; restaurant_id: string; sent_at: string }
  | { type: "order_event"; order_id: string; sent_at: string }
  | {
      type: "rider_location";
      order_id: string;
      sent_at: string;
      rider: LiveRiderLocation;
    }
  | { type: "heartbeat"; sent_at: string };

export default function RestaurantApp({
  user,
  route: _route,
}: {
  user: AuthUser;
  route: string;
}) {
  const [tab, setTab] = useState<Tab>("board");
  const [restaurant, setRestaurant] = useState<BrowseRestaurant | null>(null);
  const [menu, setMenu] = useState<BrowseMenuItem[]>([]);
  const [orders, setOrders] = useState<MarketOrder[]>([]);
  const [analytics, setAnalytics] = useState<RestaurantAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState<MarketOrder | null>(null);
  const [rejectReason, setRejectReason] = useState("Kitchen is at capacity");
  const [editing, setEditing] = useState<BrowseMenuItem | null>(null);
  const [editPrice, setEditPrice] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [syncStatus, setSyncStatus] = useState<SyncStatus>("connecting");
  const [riderLocations, setRiderLocations] = useState<
    Record<string, LiveRiderLocation>
  >({});
  const [trackingOrder, setTrackingOrder] = useState<MarketOrder | null>(null);
  const [liveTracking, setLiveTracking] = useState<Tracking | null>(null);
  const [liveRoute, setLiveRoute] = useState<TrackingRoute | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [place, items, board, stats] = await Promise.all([
        getManagerRestaurant(),
        getManagerMenu(),
        getRestaurantOrders(),
        getRestaurantAnalytics(),
      ]);
      setRestaurant(place);
      setMenu(items);
      setOrders(board);
      setAnalytics(stats);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not sync the restaurant.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      void refresh();
    }, 10000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    let cancelled = false;
    let socket: WebSocket | null = null;
    let retryTimer: number | undefined;
    let refreshTimer: number | undefined;
    let attempt = 0;

    const scheduleRefresh = () => {
      if (refreshTimer !== undefined) return;
      refreshTimer = window.setTimeout(() => {
        refreshTimer = undefined;
        void refresh();
      }, 120);
    };

    const connect = () => {
      if (cancelled) return;
      setSyncStatus(attempt === 0 ? "connecting" : "reconnecting");
      socket = new WebSocket(restaurantOrderSocketUrl());
      socket.onopen = () => {
        attempt = 0;
        setSyncStatus("live");
      };
      socket.onmessage = (event) => {
        let message: RestaurantStreamMessage;
        try {
          message = JSON.parse(event.data as string) as RestaurantStreamMessage;
        } catch {
          return;
        }
        if (message.type === "rider_location") {
          setRiderLocations((current) => ({
            ...current,
            [message.order_id]: message.rider,
          }));
          setLiveTracking((current) => {
            if (!current?.rider || current.order_id !== message.order_id) return current;
            return {
              ...current,
              rider: { ...current.rider, ...message.rider },
              simulated: message.rider.location_source !== "gps",
            };
          });
          return;
        }
        if (message.type === "restaurant_ready" || message.type === "order_event") {
          scheduleRefresh();
        }
      };
      socket.onclose = () => {
        if (cancelled) return;
        setSyncStatus("reconnecting");
        attempt += 1;
        retryTimer = window.setTimeout(connect, Math.min(1000 * 2 ** attempt, 8000));
      };
      socket.onerror = () => socket?.close();
    };

    connect();
    return () => {
      cancelled = true;
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
      if (refreshTimer !== undefined) window.clearTimeout(refreshTimer);
      socket?.close();
    };
  }, [refresh]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 3000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const act = async (
    order: MarketOrder,
    action: "accept" | "reject" | "prepare" | "ready",
    reason?: string,
  ) => {
    setBusy(order.id);
    setError(null);
    try {
      const next = await restaurantOrderAction(order.id, action, reason);
      setOrders((rows) => rows.map((row) => (row.id === next.id ? next : row)));
      setToast(
        action === "accept"
          ? "Order accepted. Start cooking when ready."
          : action === "reject"
            ? "Order rejected. The customer will be notified."
            : action === "prepare"
              ? "Kitchen started preparing."
              : "Order marked ready for pickup.",
      );
      setRejecting(null);
      void refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update this order.");
    } finally {
      setBusy(null);
    }
  };

  const openTracking = async (order: MarketOrder) => {
    setTrackingOrder(order);
    setLiveTracking(null);
    setLiveRoute(null);
    try {
      const [tracking, route] = await Promise.all([
        getTracking(order.id),
        getTrackingRoute(order.id),
      ]);
      setLiveTracking(tracking);
      setLiveRoute(route);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load rider tracking.");
    }
  };

  const toggleItem = async (item: BrowseMenuItem) => {
    setBusy(item.id);
    setError(null);
    try {
      const next = await patchManagerMenuItem(item.id, { available: !item.available });
      setMenu((rows) => rows.map((row) => (row.id === next.id ? next : row)));
      setToast(next.available ? `${next.name} is available.` : `${next.name} marked sold out.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update this dish.");
    } finally {
      setBusy(null);
    }
  };

  const saveItem = async () => {
    if (!editing) return;
    setBusy(editing.id);
    setError(null);
    try {
      const next = await patchManagerMenuItem(editing.id, {
        price: editPrice,
        description: editDescription,
      });
      setMenu((rows) => rows.map((row) => (row.id === next.id ? next : row)));
      setEditing(null);
      setToast(`${next.name} updated.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update this dish.");
    } finally {
      setBusy(null);
    }
  };

  const newOrders = orders.filter((order) => order.status === "PLACED");
  const nav: NavItem[] = [
    { id: "board", label: "Order board", badge: newOrders.length },
    { id: "menu", label: "Menu" },
    { id: "insights", label: "Insights" },
  ];

  if (loading && !restaurant) return <Spinner label="Opening the pass" />;
  if (!restaurant) {
    return (
      <div className="mx-auto max-w-xl py-16 text-center">
        <p className="font-serif text-[28px] italic">No kitchen assigned.</p>
        <p className="mt-2 text-sm text-stone-500">{error}</p>
      </div>
    );
  }

  return (
    <MarketShell
      user={user}
      roleLabel="Restaurant · the pass"
      nav={nav}
      active={tab}
      onNavigate={(id) => setTab(id as Tab)}
      homePath="/restaurant"
    >
      {error ? <div className="mb-4"><Notice>{error}</Notice></div> : null}
      {toast ? (
        <div className="fixed bottom-5 right-5 z-50 rounded-2xl bg-stone-900 px-4 py-3 text-[12px] font-medium text-[#f8f3e9] shadow-2xl">
          {toast}
        </div>
      ) : null}

      {tab === "board" ? (
        <Board
          restaurant={restaurant}
          orders={orders}
          analytics={analytics}
          busy={busy}
          riderLocations={riderLocations}
          syncStatus={syncStatus}
          onTrack={(order) => void openTracking(order)}
          onAccept={(order) => void act(order, "accept")}
          onReject={(order) => {
            setRejecting(order);
            setRejectReason("Kitchen is at capacity");
          }}
          onPrepare={(order) => void act(order, "prepare")}
          onReady={(order) => void act(order, "ready")}
        />
      ) : null}

      {tab === "menu" ? (
        <MenuBoard
          menu={menu}
          busy={busy}
          onToggle={(item) => void toggleItem(item)}
          onEdit={(item) => {
            setEditing(item);
            setEditPrice(item.price);
            setEditDescription(item.description);
          }}
        />
      ) : null}

      {tab === "insights" ? (
        <Insights
          restaurant={restaurant}
          analytics={analytics}
          orders={orders}
          menu={menu}
        />
      ) : null}

      {rejecting ? (
        <Modal title="Reject this order?" onClose={() => setRejecting(null)}>
          <p className="text-sm leading-relaxed text-stone-600">
            {rejecting.order_number ?? rejecting.id.slice(0, 8)} for{" "}
            {rejecting.delivery_address ?? "a customer"} will be cancelled. The reason is
            shared with the customer.
          </p>
          <label className="mt-4 block">
            <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-[0.14em] text-stone-500">
              Reason
            </span>
            <input
              value={rejectReason}
              onChange={(event) => setRejectReason(event.target.value)}
              className="w-full rounded-xl border border-stone-900/15 bg-white/70 px-3 py-2 text-[13px] outline-none focus:border-[#d94f2b]/50"
            />
          </label>
          <div className="mt-5 flex gap-2">
            <Btn variant="outline" className="flex-1" onClick={() => setRejecting(null)}>
              Keep order
            </Btn>
            <Btn
              variant="danger"
              className="flex-1"
              disabled={busy === rejecting.id}
              onClick={() => void act(rejecting, "reject", rejectReason)}
            >
              {busy === rejecting.id ? "Rejecting…" : "Reject order"}
            </Btn>
          </div>
        </Modal>
      ) : null}

      {editing ? (
        <Modal title={`Edit ${editing.name}`} onClose={() => setEditing(null)}>
          <div className="space-y-3">
            <Field
              label="Price"
              value={editPrice}
              onChange={setEditPrice}
              type="number"
              min={1}
              step={1}
              required
            />
            <label className="block">
              <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-[0.16em] text-stone-500">
                Description
              </span>
              <textarea
                value={editDescription}
                onChange={(event) => setEditDescription(event.target.value)}
                rows={3}
                className="w-full resize-none rounded-xl border border-stone-900/15 bg-white/70 px-3 py-2 text-[13px] outline-none focus:border-[#1f5b46]/50"
              />
            </label>
            <Btn
              className="w-full"
              disabled={busy === editing.id}
              onClick={() => void saveItem()}
            >
              {busy === editing.id ? "Saving…" : "Save dish"}
            </Btn>
          </div>
        </Modal>
      ) : null}

      {trackingOrder ? (
        <Modal
          title={`Live pickup map · ${trackingOrder.order_number ?? trackingOrder.id.slice(0, 8)}`}
          onClose={() => setTrackingOrder(null)}
        >
          {liveTracking ? (
            <RouteMap tracking={liveTracking} route={liveRoute} />
          ) : (
            <Spinner label="Loading rider location" />
          )}
          <p className="mt-3 text-[10px] leading-relaxed text-stone-500">
            Rider coordinates update in real time while this view is open. GPS and simulated
            fallback locations are labelled on the map.
          </p>
        </Modal>
      ) : null}
    </MarketShell>
  );
}

function Board({
  restaurant,
  orders,
  analytics,
  busy,
  riderLocations,
  syncStatus,
  onTrack,
  onAccept,
  onReject,
  onPrepare,
  onReady,
}: {
  restaurant: BrowseRestaurant;
  orders: MarketOrder[];
  analytics: RestaurantAnalytics | null;
  busy: string | null;
  riderLocations: Record<string, LiveRiderLocation>;
  syncStatus: SyncStatus;
  onTrack: (order: MarketOrder) => void;
  onAccept: (order: MarketOrder) => void;
  onReject: (order: MarketOrder) => void;
  onPrepare: (order: MarketOrder) => void;
  onReady: (order: MarketOrder) => void;
}) {
  const columns = [
    {
      id: "new",
      title: "New tickets",
      hint: "Accept within the promise window",
      rows: orders.filter((order) => order.status === "PLACED"),
      tint: "bg-[#d94f2b]/[0.055]",
    },
    {
      id: "kitchen",
      title: "On the stove",
      hint: "Accepted and preparing",
      rows: orders.filter(
        (order) => order.status === "ACCEPTED" || order.status === "PREPARING",
      ),
      tint: "bg-[#f4b942]/[0.08]",
    },
    {
      id: "ready",
      title: "Waiting for rider",
      hint: "Sealed, bagged and ready",
      rows: orders.filter((order) => order.status === "READY"),
      tint: "bg-[#1f5b46]/[0.06]",
    },
    {
      id: "lastmile",
      title: "Last mile",
      hint: "Picked up or recently delivered",
      rows: orders
        .filter((order) => order.status === "PICKED_UP" || order.status === "DELIVERED")
        .slice(0, 6),
      tint: "bg-stone-900/[0.035]",
    },
  ];

  return (
    <div className="space-y-5">
      <section className="overflow-hidden rounded-[30px] border border-stone-900/10 bg-[#171512] text-[#f8f3e9]">
        <div className="grid lg:grid-cols-[1.25fr_0.75fr]">
          <div className="relative z-10 p-5 sm:p-7">
            <div className="flex flex-wrap items-center gap-2">
              <span className="flex items-center gap-1.5 rounded-full border border-emerald-400/20 bg-emerald-400/10 px-2.5 py-1 text-[9px] font-bold uppercase tracking-[0.14em] text-emerald-300">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
                Accepting orders
              </span>
              <SimBadge />
            </div>
            <h1 className="mt-3 font-serif text-[42px] italic leading-[0.95] sm:text-[52px]">
              {restaurant.name}
            </h1>
            <p className="mt-2 max-w-xl text-[12px] leading-relaxed text-stone-400">
              {restaurant.description}
            </p>
            <div className="mt-5 flex flex-wrap gap-x-6 gap-y-3 border-t border-white/10 pt-4">
              {[
                ["New tickets", String(columns[0].rows.length)],
                ["On the stove", String(columns[1].rows.length)],
                ["Ready", String(columns[2].rows.length)],
                ["Rating", `★ ${Number(restaurant.rating).toFixed(1)}`],
              ].map(([label, value]) => (
                <div key={label}>
                  <p className="text-[9px] uppercase tracking-[0.16em] text-stone-500">
                    {label}
                  </p>
                  <p className="mt-1 font-serif text-[22px] leading-none">{value}</p>
                </div>
              ))}
            </div>
          </div>
          <ProductArt
            cuisine={restaurant.cuisine}
            name={restaurant.name}
            className="min-h-[190px] lg:min-h-full"
          />
        </div>
      </section>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-stone-500">
          {syncStatus === "live"
            ? "Live sync · orders and rider location update instantly"
            : "Reconnecting live sync · auto-refreshes every 10 sec"}
        </p>
        {analytics ? (
          <p className="text-[10px] uppercase tracking-[0.12em] text-stone-400">
            {analytics.completed_today} done today · {formatCurrency(analytics.revenue_today)} revenue
          </p>
        ) : null}
      </div>

      <div className="grid gap-3 xl:grid-cols-4 lg:grid-cols-2">
        {columns.map((column) => (
          <section
            key={column.id}
            className={`rounded-[22px] border border-stone-900/10 ${column.tint} p-2.5`}
          >
            <div className="flex items-start justify-between gap-2 px-1 py-1.5">
              <div>
                <h2 className="text-[12px] font-bold uppercase tracking-[0.1em]">
                  {column.title}
                </h2>
                <p className="mt-0.5 text-[9px] text-stone-500">{column.hint}</p>
              </div>
              <span className="flex h-6 min-w-6 items-center justify-center rounded-full bg-stone-900/[0.07] px-1.5 text-[10px] font-bold text-stone-600">
                {column.rows.length}
              </span>
            </div>
            <div className="mt-2 space-y-2">
              {column.rows.length === 0 ? (
                <p className="rounded-xl border border-dashed border-stone-900/10 px-3 py-6 text-center text-[10px] text-stone-400">
                  Nothing here right now.
                </p>
              ) : (
                column.rows.map((order) => (
                  <Ticket
                    key={order.id}
                    order={order}
                    busy={busy === order.id}
                    riderLocation={riderLocations[order.id]}
                    onTrack={() => onTrack(order)}
                    onAccept={() => onAccept(order)}
                    onReject={() => onReject(order)}
                    onPrepare={() => onPrepare(order)}
                    onReady={() => onReady(order)}
                  />
                ))
              )}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function Ticket({
  order,
  busy,
  riderLocation,
  onTrack,
  onAccept,
  onReject,
  onPrepare,
  onReady,
}: {
  order: MarketOrder;
  busy: boolean;
  riderLocation?: LiveRiderLocation;
  onTrack: () => void;
  onAccept: () => void;
  onReject: () => void;
  onPrepare: () => void;
  onReady: () => void;
}) {
  return (
    <article className="rounded-2xl border border-stone-900/10 bg-[#fffcf6] p-3 shadow-[0_10px_30px_-24px_rgba(28,25,23,0.7)]">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[9px] font-bold uppercase tracking-[0.12em] text-stone-400">
            {order.order_number ?? order.id.slice(0, 8)}
          </p>
          <p className="mt-0.5 text-[11px] font-semibold">
            {formatCurrency(order.total_amount)}
          </p>
        </div>
        <StatusPill status={order.status} />
      </div>
      <p className="mt-1 text-[9px] uppercase tracking-[0.1em] text-stone-400">
        {timeAgo(order.placed_at)} · {order.items.length} lines
      </p>
      <div className="mt-2 space-y-1 border-t border-stone-900/8 pt-2">
        {order.items.map((item) => (
          <p key={item.menu_item_id} className="flex justify-between gap-2 text-[11px]">
            <span className="text-stone-700">
              {item.name} <span className="text-stone-400">×{item.qty}</span>
            </span>
            <span className="shrink-0 text-stone-500">
              {formatCurrency(Number(item.unit_price) * item.qty)}
            </span>
          </p>
        ))}
      </div>
      {order.delivery_instructions ? (
        <p className="mt-2 rounded-lg bg-[#f4b942]/15 px-2 py-1.5 text-[9px] leading-snug text-[#7d5309]">
          “{order.delivery_instructions}”
        </p>
      ) : null}
      <div className="mt-2 flex items-center gap-2 border-t border-stone-900/8 pt-2 text-[9px] text-stone-500">
        <span>{order.payment_method.replace("_DEMO", " demo")}</span>
        <span>·</span>
        <span>{order.payment_status.replaceAll("_", " ")}</span>
      </div>
      {order.rider_name || riderLocation ? (
        <div className="mt-2 rounded-lg bg-sky-600/[0.07] px-2 py-1.5 text-[9px] text-sky-900">
          <p className="font-semibold">
            {riderLocation?.name ?? order.rider_name ?? "Assigned rider"}
            {riderLocation ? " · live location" : " · location pending"}
          </p>
          {riderLocation ? (
            <p className="mt-0.5 text-sky-800/75">
              {riderLocation.location_source === "gps" ? "GPS" : "Simulated"} · {riderLocation.lat.toFixed(4)}, {riderLocation.lng.toFixed(4)}
              {riderLocation.location_source === "gps" &&
              riderLocation.location_accuracy_m !== null
                ? ` (±${Math.round(riderLocation.location_accuracy_m)} m)`
                : ""}
            </p>
          ) : null}
          <button
            type="button"
            onClick={onTrack}
            className="mt-1.5 font-semibold text-sky-800 underline decoration-sky-800/40 underline-offset-2"
          >
            Open live pickup map
          </button>
        </div>
      ) : null}
      <div className="mt-2 flex flex-wrap gap-1.5">
        {order.status === "PLACED" ? (
          <>
            <Btn size="sm" variant="ghost" disabled={busy} onClick={onReject}>
              Reject
            </Btn>
            <Btn size="sm" className="flex-1" disabled={busy} onClick={onAccept}>
              {busy ? "…" : "Accept"}
            </Btn>
          </>
        ) : null}
        {order.status === "ACCEPTED" ? (
          <Btn size="sm" className="w-full" disabled={busy} onClick={onPrepare}>
            {busy ? "…" : "Start preparing"}
          </Btn>
        ) : null}
        {order.status === "PREPARING" ? (
          <Btn size="sm" className="w-full" disabled={busy} onClick={onReady}>
            {busy ? "…" : "Mark ready"}
          </Btn>
        ) : null}
        {order.status === "READY" ? (
          <p className="w-full rounded-full bg-[#1f5b46]/10 px-2 py-1.5 text-center text-[9px] font-semibold uppercase tracking-[0.1em] text-[#1f5b46]">
            Waiting for rider
          </p>
        ) : null}
        {order.status === "PICKED_UP" ? (
          <p className="w-full rounded-full bg-sky-600/10 px-2 py-1.5 text-center text-[9px] font-semibold uppercase tracking-[0.1em] text-sky-800">
            Rider has the bag
          </p>
        ) : null}
        {order.status === "DELIVERED" ? (
          <p className="w-full text-center text-[9px] uppercase tracking-[0.1em] text-stone-400">
            Delivered {order.actual_delivery_at ? timeAgo(order.actual_delivery_at) : ""}
          </p>
        ) : null}
      </div>
    </article>
  );
}

function MenuBoard({
  menu,
  busy,
  onToggle,
  onEdit,
}: {
  menu: BrowseMenuItem[];
  busy: string | null;
  onToggle: (item: BrowseMenuItem) => void;
  onEdit: (item: BrowseMenuItem) => void;
}) {
  const groups = useMemo(() => {
    const map = new Map<string, BrowseMenuItem[]>();
    for (const item of menu) {
      const rows = map.get(item.category) ?? [];
      rows.push(item);
      map.set(item.category, rows);
    }
    return Array.from(map.entries());
  }, [menu]);

  return (
    <div className="space-y-5">
      <div>
        <div className="flex items-center gap-2">
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500">
            Menu control
          </p>
          <SimBadge />
        </div>
        <h1 className="mt-1 font-serif text-[38px] italic leading-none">
          What leaves the kitchen.
        </h1>
        <p className="mt-2 text-[12px] text-stone-500">
          Sold-out dishes stay visible but cannot be added to a cart. Dishes already in a
          live cart may resist edits for a moment.
        </p>
      </div>

      {menu.length === 0 ? (
        <Empty title="No dishes loaded." hint="The menu has not been seeded for this kitchen." />
      ) : null}

      <div className="space-y-5">
        {groups.map(([category, items]) => (
          <section
            key={category}
            className="overflow-hidden rounded-[24px] border border-stone-900/10 bg-[#fffcf6]/70"
          >
            <div className="flex items-center justify-between bg-stone-900/[0.03] px-4 py-2.5">
              <h2 className="font-serif text-[21px] italic">{category}</h2>
              <span className="text-[9px] uppercase tracking-[0.12em] text-stone-400">
                {items.filter((item) => item.available).length}/{items.length} live
              </span>
            </div>
            {items.map((item, index) => (
              <div
                key={item.id}
                className={`flex flex-wrap items-center gap-3 px-4 py-3 ${
                  index > 0 ? "border-t border-stone-900/8" : ""
                }`}
              >
                <span
                  className={`flex h-3.5 w-3.5 items-center justify-center border ${
                    item.veg ? "border-emerald-700" : "border-rose-700"
                  }`}
                >
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${
                      item.veg ? "bg-emerald-700" : "bg-rose-700"
                    }`}
                  />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] font-semibold">
                    {item.name}
                    {!item.available ? (
                      <span className="ml-2 text-[10px] font-medium text-rose-700">
                        sold out
                      </span>
                    ) : null}
                  </p>
                  <p className="mt-0.5 line-clamp-1 text-[10px] text-stone-500">
                    {item.description}
                  </p>
                </div>
                <p className="text-[13px] font-bold">{formatCurrency(item.price)}</p>
                <Btn size="sm" variant="outline" onClick={() => onEdit(item)}>
                  Edit
                </Btn>
                <button
                  type="button"
                  disabled={busy === item.id}
                  onClick={() => onToggle(item)}
                  className={`relative h-6 w-11 rounded-full transition ${
                    item.available ? "bg-[#1f5b46]" : "bg-stone-300"
                  }`}
                  aria-label={item.available ? "Mark sold out" : "Mark available"}
                >
                  <span
                    className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition ${
                      item.available ? "left-[22px]" : "left-0.5"
                    }`}
                  />
                </button>
              </div>
            ))}
          </section>
        ))}
      </div>
    </div>
  );
}

function Insights({
  restaurant,
  analytics,
  orders,
  menu,
}: {
  restaurant: BrowseRestaurant;
  analytics: RestaurantAnalytics | null;
  orders: MarketOrder[];
  menu: BrowseMenuItem[];
}) {
  const topItems = useMemo(() => {
    const map = new Map<string, { name: string; qty: number }>();
    for (const order of orders) {
      if (order.status !== "DELIVERED") continue;
      for (const item of order.items) {
        const current = map.get(item.menu_item_id) ?? { name: item.name, qty: 0 };
        current.qty += item.qty;
        map.set(item.menu_item_id, current);
      }
    }
    return Array.from(map.values())
      .sort((a, b) => b.qty - a.qty)
      .slice(0, 5);
  }, [orders]);
  const max = Math.max(...topItems.map((item) => item.qty), 1);
  const active = orders.filter((order) =>
    ["PLACED", "ACCEPTED", "PREPARING", "READY", "PICKED_UP"].includes(order.status),
  ).length;

  return (
    <div className="space-y-5">
      <div>
        <div className="flex items-center gap-2">
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500">
            Kitchen intelligence
          </p>
          <SimBadge />
        </div>
        <h1 className="mt-1 font-serif text-[38px] italic leading-none">
          A quieter read of the day.
        </h1>
      </div>

      <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
        <StatCard
          label="Revenue today"
          value={formatCurrency(analytics?.revenue_today ?? "0")}
          hint="Delivered orders only"
          accent="orange"
        />
        <StatCard
          label="Orders done"
          value={analytics?.completed_today ?? 0}
          hint={`${active} live on the pass`}
          accent="green"
        />
        <StatCard
          label="Kitchen clock"
          value={
            analytics?.average_prep_min
              ? `${Math.round(analytics.average_prep_min)} min`
              : "—"
          }
          hint="Placed → delivered, rolling"
          accent="gold"
        />
        <StatCard
          label="Guest rating"
          value={`★ ${Number(restaurant.rating).toFixed(1)}`}
          hint={`${restaurant.rating_count} reviews`}
          accent="stone"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-[26px] border border-stone-900/10 bg-[#fffcf6]/70 p-4 sm:p-5">
          <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-stone-500">
            Menu health
          </p>
          <h2 className="mt-1 font-serif text-[24px] italic">Selling and showing</h2>
          <div className="mt-4 grid grid-cols-3 gap-2">
            {[
              ["Dishes", String(analytics?.menu_items ?? menu.length)],
              ["Available", String(analytics?.available_items ?? 0)],
              ["Sold out", String((analytics?.menu_items ?? 0) - (analytics?.available_items ?? 0))],
            ].map(([label, value]) => (
              <div key={label} className="rounded-xl bg-stone-900/[0.03] p-3 text-center">
                <p className="font-serif text-[24px] leading-none">{value}</p>
                <p className="mt-1 text-[9px] uppercase tracking-[0.1em] text-stone-500">
                  {label}
                </p>
              </div>
            ))}
          </div>
          <div className="mt-4">
            <p className="text-[9px] font-bold uppercase tracking-[0.16em] text-stone-500">
              Top delivered dishes
            </p>
            {topItems.length === 0 ? (
              <p className="mt-2 text-[11px] text-stone-500">
                Completed orders will reveal the popular plates.
              </p>
            ) : (
              <div className="mt-2 space-y-2">
                {topItems.map((item) => (
                  <div key={item.name}>
                    <div className="flex justify-between text-[10px]">
                      <span className="font-medium">{item.name}</span>
                      <span className="text-stone-500">{item.qty}</span>
                    </div>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-stone-900/8">
                      <div
                        className="h-full rounded-full bg-[#1f5b46]"
                        style={{ width: `${(item.qty / max) * 100}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>

        <section className="rounded-[26px] border border-stone-900/10 bg-[#fffcf6]/70 p-4 sm:p-5">
          <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-stone-500">
            Live load
          </p>
          <h2 className="mt-1 font-serif text-[24px] italic">The pass right now</h2>
          <div className="mt-3 space-y-2">
            {[
              ["PLACED", "Awaiting your yes"],
              ["ACCEPTED", "Confirmed, not started"],
              ["PREPARING", "On the stove"],
              ["READY", "Sealed, waiting"],
            ].map(([status, hint]) => {
              const count = orders.filter((order) => order.status === status).length;
              return (
                <div
                  key={status}
                  className="flex items-center justify-between rounded-xl bg-stone-900/[0.03] px-3 py-2"
                >
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-[0.1em]">
                      {status}
                    </p>
                    <p className="text-[9px] text-stone-500">{hint}</p>
                  </div>
                  <p className="font-serif text-[20px] leading-none">{count}</p>
                </div>
              );
            })}
          </div>
          <p className="mt-3 text-[10px] leading-relaxed text-stone-400">
            Metrics are computed from seeded simulator orders and live demo activity. The
            kitchen clock is a rolling duration, not a guarantee.
          </p>
        </section>
      </div>

      <section className="rounded-[26px] border border-stone-900/10 bg-[#fffcf6]/70 p-4">
        <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-stone-500">
          Recent activity
        </p>
        <h2 className="mt-1 font-serif text-[22px] italic">Orders through the pass</h2>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[520px] text-left text-[11px]">
            <thead>
              <tr className="border-b border-stone-900/10 text-[9px] uppercase tracking-[0.12em] text-stone-400">
                <th className="py-2 font-semibold">Order</th>
                <th className="py-2 font-semibold">Placed</th>
                <th className="py-2 font-semibold">Status</th>
                <th className="py-2 text-right font-semibold">Total</th>
              </tr>
            </thead>
            <tbody>
              {orders.slice(0, 12).map((order) => (
                <tr key={order.id} className="border-b border-stone-900/5">
                  <td className="py-2 font-medium">
                    {order.order_number ?? order.id.slice(0, 8)}
                  </td>
                  <td className="py-2 text-stone-500">
                    {formatDateTime(order.placed_at)}
                  </td>
                  <td className="py-2">
                    <StatusPill status={order.status} />
                  </td>
                  <td className="py-2 text-right font-semibold">
                    {formatCurrency(order.total_amount)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
