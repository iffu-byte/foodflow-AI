import { useCallback, useEffect, useState } from "react";

import {
  acceptOffer,
  ApiError,
  getActiveDelivery,
  getDeliveryHistory,
  getEarnings,
  getOffers,
  getRiderProfile,
  getTracking,
  getTrackingRoute,
  rejectOffer,
  riderAssignmentAction,
  setRiderAvailability,
  type AssignmentAction,
  type AuthUser,
  type Earnings,
  type MarketOrder,
  type Offer,
  type RiderProfile,
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
  useRiderLocation,
  type RiderLocationMode,
} from "../lib/useRiderLocation";
import {
  Btn,
  Empty,
  MarketShell,
  Modal,
  Notice,
  SimBadge,
  Spinner,
  StatCard,
  StatusPill,
  type NavItem,
} from "../components/market";

type Tab = "overview" | "offers" | "delivery" | "earnings" | "history";

const navBase: NavItem[] = [
  { id: "overview", label: "Today" },
  { id: "offers", label: "Offers" },
  { id: "delivery", label: "Delivery" },
  { id: "earnings", label: "Earnings" },
  { id: "history", label: "History" },
];

const actionByStatus: Record<
  string,
  {
    action: "arrived-restaurant" | "pickup" | "arrived-customer" | "complete";
    label: string;
    hint: string;
  }
> = {
  ACCEPTED: {
    action: "arrived-restaurant",
    label: "I'm at the restaurant",
    hint: "Confirm arrival so the kitchen knows you are here.",
  },
  ARRIVED_AT_RESTAURANT: {
    action: "pickup",
    label: "Pick up the order",
    hint: "Collect the sealed bag and start the drop.",
  },
  PICKED_UP: {
    action: "arrived-customer",
    label: "I'm at the customer",
    hint: "Confirm arrival at the doorstep. Works only within 400 m of the customer's pin.",
  },
  ARRIVED_AT_CUSTOMER: {
    action: "complete",
    label: "Hand over with code",
    hint: "Hand over the bag, then enter the 4-digit code the customer reads out. "
      + "It only works within 150 m of their pin.",
  },
};

export default function RiderApp({
  user,
  route: _route,
}: {
  user: AuthUser;
  route: string;
}) {
  const [tab, setTab] = useState<Tab>("overview");
  const [profile, setProfile] = useState<RiderProfile | null>(null);
  const [offers, setOffers] = useState<Offer[]>([]);
  const [active, setActive] = useState<AssignmentAction | null>(null);
  const [earnings, setEarnings] = useState<Earnings | null>(null);
  const [history, setHistory] = useState<MarketOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [otpOpen, setOtpOpen] = useState(false);
  const [otp, setOtp] = useState("");
  const [otpError, setOtpError] = useState<string | null>(null);
  const [deliveryTarget, setDeliveryTarget] = useState<{
    lat: number;
    lng: number;
  } | null>(null);
  const [activeTracking, setActiveTracking] = useState<Tracking | null>(null);
  const [activeRoute, setActiveRoute] = useState<TrackingRoute | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [me, nextOffers, nextActive, nextEarnings, nextHistory] =
        await Promise.all([
          getRiderProfile(),
          getOffers(),
          getActiveDelivery(),
          getEarnings(),
          getDeliveryHistory(),
        ]);
      setProfile(me);
      setOffers(nextOffers);
      setActive(nextActive ?? null);
      setEarnings(nextEarnings);
      setHistory(nextHistory);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not sync rider data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      void refresh();
    }, 12000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 3000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const online = profile ? profile.status !== "OFFLINE" : false;
  const activeOrderId = active?.order.id ?? null;
  const activeOrderStatus = active?.order.status ?? null;

  useEffect(() => {
    if (!activeOrderId) {
      setDeliveryTarget(null);
      setActiveTracking(null);
      setActiveRoute(null);
      return;
    }
    let cancelled = false;
    const loadTarget = async () => {
      try {
        const track = await getTracking(activeOrderId);
        if (cancelled) return;
        setDeliveryTarget(
          activeOrderStatus === "PICKED_UP"
            ? { lat: track.drop_lat, lng: track.drop_lng }
            : { lat: track.restaurant_lat, lng: track.restaurant_lng },
        );
        setActiveTracking(track);
        try {
          const route = await getTrackingRoute(activeOrderId);
          if (!cancelled) setActiveRoute(route);
        } catch {
          if (!cancelled) setActiveRoute(null);
        }
      } catch {
        // Keep the previous target; location updates remain best-effort.
      }
    };
    void loadTarget();
    const timer = window.setInterval(() => {
      void loadTarget();
    }, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeOrderId, activeOrderStatus]);

  const riderLocation = useRiderLocation({
    online,
    initialPosition: profile ? { lat: profile.lat, lng: profile.lng } : null,
    target: deliveryTarget,
    onProfile: (next) => {
      setProfile(next);
      setActiveTracking((current) => {
        if (!current?.rider) return current;
        return {
          ...current,
          rider: {
            ...current.rider,
            lat: next.lat,
            lng: next.lng,
            location_source: next.location_source,
            location_accuracy_m: next.location_accuracy_m,
            last_seen_at: next.last_seen_at,
          },
          simulated: next.location_source !== "gps",
        };
      });
    },
  });

  const toggleAvailability = async () => {
    if (!profile) return;
    setBusy("availability");
    try {
      const next = await setRiderAvailability(!online);
      setProfile(next);
      setToast(next.status === "OFFLINE" ? "You are offline." : "You are online and visible.");
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not change availability.");
    } finally {
      setBusy(null);
    }
  };

  const accept = async (offer: Offer) => {
    setBusy(offer.assignment_id);
    setError(null);
    try {
      const result = await acceptOffer(offer.assignment_id);
      setActive(result);
      setOffers((rows) => rows.filter((row) => row.assignment_id !== offer.assignment_id));
      setTab("delivery");
      setToast("Pickup accepted. Head to the restaurant.");
      void refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not accept this offer.");
      void refresh();
    } finally {
      setBusy(null);
    }
  };

  const pass = async (offer: Offer) => {
    setBusy(offer.assignment_id);
    setError(null);
    try {
      const result = await rejectOffer(offer.assignment_id, "rider passed");
      setOffers((rows) => rows.filter((row) => row.assignment_id !== offer.assignment_id));
      setToast(
        result.next_offer
          ? "Passed. Another offer is already waiting."
          : "Passed. We will keep looking.",
      );
      void refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not pass this offer.");
    } finally {
      setBusy(null);
    }
  };

  const runAction = async (code?: string) => {
    if (!active) return;
    const next = actionByStatus[active.status];
    if (!next) return;
    if (next.action === "complete" && !code) {
      setOtp("");
      setOtpError(null);
      setOtpOpen(true);
      return;
    }
    setBusy("action");
    setError(null);
    setOtpError(null);
    try {
      // Send a fresh position first so the geofence judges where you are now.
      if (next.action === "arrived-customer" || next.action === "complete") {
        await riderLocation.sendNow();
      }
      const result = await riderAssignmentAction(active.assignment_id, next.action, code);
      setOtpOpen(false);
      if (result.status === "COMPLETED") {
        setActive(null);
        setTab("earnings");
        setToast("Delivery complete. Earnings added to your ledger.");
      } else {
        setActive(result);
        setToast("Delivery updated.");
      }
      void refresh();
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Could not update this delivery.";
      if (code) setOtpError(message);
      else setError(message);
    } finally {
      setBusy(null);
    }
  };

  const pingNow = async () => {
    if (!profile) return;
    setBusy("ping");
    const sent = await riderLocation.sendNow();
    if (sent === "gps") {
      setToast("Live GPS location sent.");
    } else if (sent === "simulated") {
      setToast("Simulated location ping sent.");
    } else if (riderLocation.error) {
      setError(riderLocation.error);
    }
    setBusy(null);
  };

  const nav = navBase.map((item) =>
    item.id === "offers" && offers.length
      ? { ...item, badge: offers.length }
      : item,
  );

  const onNavigate = (id: string) => {
    setTab(id as Tab);
  };

  if (loading && !profile) return <Spinner label="Starting your shift" />;
  if (!profile) {
    return (
      <div className="mx-auto max-w-xl py-16 text-center">
        <p className="font-serif text-[28px] italic">Rider profile not available.</p>
        <p className="mt-2 text-sm text-stone-500">{error}</p>
      </div>
    );
  }

  return (
    <MarketShell
      user={user}
      roleLabel="Rider · last mile"
      nav={nav}
      active={tab}
      onNavigate={onNavigate}
      homePath="/rider"
    >
      {error ? <div className="mb-4"><Notice>{error}</Notice></div> : null}
      {toast ? (
        <div className="fixed bottom-5 right-5 z-50 rounded-2xl bg-stone-900 px-4 py-3 text-[12px] font-medium text-[#f8f3e9] shadow-2xl">
          {toast}
        </div>
      ) : null}

      {tab === "overview" ? (
        <Overview
          profile={profile}
          online={online}
          active={active}
          offers={offers}
          earnings={earnings}
          busy={busy}
          locationMode={riderLocation.mode}
          locationAccuracyM={riderLocation.accuracyM}
          onToggle={() => void toggleAvailability()}
          onOffers={() => setTab("offers")}
          onDelivery={() => setTab("delivery")}
          onPing={() => void pingNow()}
          onRetryGps={riderLocation.retryGps}
        />
      ) : null}

      {tab === "offers" ? (
        <OffersView
          offers={offers}
          online={online}
          busy={busy}
          locationMode={riderLocation.mode}
          locationAccuracyM={riderLocation.accuracyM}
          onToggle={() => void toggleAvailability()}
          onAccept={(offer) => void accept(offer)}
          onPass={(offer) => void pass(offer)}
          onRefresh={() => void refresh()}
        />
      ) : null}

      {tab === "delivery" ? (
        <DeliveryView
          active={active}
          tracking={activeTracking}
          route={activeRoute}
          busy={busy}
          locationMode={riderLocation.mode}
          locationAccuracyM={riderLocation.accuracyM}
          riderPosition={profile ? { lat: profile.lat, lng: profile.lng } : null}
          onAction={() => void runAction()}
          onPing={() => void pingNow()}
          onRetryGps={riderLocation.retryGps}
          onBrowseOffers={() => setTab("offers")}
        />
      ) : null}

      {tab === "earnings" ? <EarningsView earnings={earnings} /> : null}

      {tab === "history" ? <HistoryView history={history} /> : null}

      {otpOpen ? (
        <Modal title="Enter the customer's delivery code" onClose={() => setOtpOpen(false)}>
          <p className="text-[12px] text-stone-600">
            Ask the customer for the 4-digit code shown in their app. Wrong codes are
            counted; five wrong codes lock the order for support.
          </p>
          <input
            autoFocus
            inputMode="numeric"
            maxLength={4}
            value={otp}
            onChange={(event) => setOtp(event.target.value.replace(/\D/g, "").slice(0, 4))}
            onKeyDown={(event) => {
              if (event.key === "Enter" && otp.length === 4) void runAction(otp);
            }}
            className="mt-3 w-full rounded-2xl border border-stone-900/15 bg-white px-4 py-3 text-center font-mono text-[32px] tracking-[0.5em] outline-none focus:border-[#1f5b46]"
            placeholder="• • • •"
          />
          {otpError ? <div className="mt-2"><Notice>{otpError}</Notice></div> : null}
          <Btn
            className="mt-3 w-full"
            disabled={otp.length !== 4 || busy === "action"}
            onClick={() => void runAction(otp)}
          >
            {busy === "action" ? "Checking…" : "Confirm handover"}
          </Btn>
        </Modal>
      ) : null}
    </MarketShell>
  );
}

function Overview({
  profile,
  online,
  active,
  offers,
  earnings,
  busy,
  locationMode,
  locationAccuracyM,
  onToggle,
  onOffers,
  onDelivery,
  onPing,
  onRetryGps,
}: {
  profile: RiderProfile;
  online: boolean;
  active: AssignmentAction | null;
  offers: Offer[];
  earnings: Earnings | null;
  busy: string | null;
  locationMode: RiderLocationMode;
  locationAccuracyM: number | null;
  onToggle: () => void;
  onOffers: () => void;
  onDelivery: () => void;
  onPing: () => void;
  onRetryGps: () => void;
}) {
  const locationText = locationLabel(locationMode, locationAccuracyM);

  return (
    <div className="space-y-5">
      <section className="relative overflow-hidden rounded-[30px] bg-[#171512] p-5 text-[#f8f3e9] sm:p-8">
        <div className="pointer-events-none absolute -right-24 -top-20 h-80 w-80 rounded-full bg-[radial-gradient(circle,rgba(31,91,70,0.9),transparent_64%)]" />
        <div className="pointer-events-none absolute bottom-0 left-1/3 h-56 w-56 rounded-full bg-[radial-gradient(circle,rgba(217,79,43,0.35),transparent_68%)]" />
        <div className="relative flex flex-wrap items-start justify-between gap-5">
          <div>
            <div className="flex items-center gap-2">
              <span
                className={`h-2 w-2 rounded-full ${
                  online ? "bg-emerald-400" : "bg-stone-600"
                }`}
              />
              <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-400">
                {online ? "On shift · visible to dispatch" : "Off shift · hidden"}
              </span>
            </div>
            <h1 className="mt-3 font-serif text-[40px] italic leading-[0.96] sm:text-[52px]">
              {greeting()}, {profile.name.split(" ")[0]}.
            </h1>
            <p className="mt-2 max-w-md text-[13px] leading-relaxed text-stone-400">
              {online
                ? active
                  ? "You have a live delivery. The next best action is waiting below."
                  : offers.length
                    ? `${offers.length} offer${offers.length === 1 ? "" : "s"} matched to your position.`
                    : "You are online. We will surface the nearest ready order."
                : "Go online when you are ready to take offers."}
            </p>
            <p className="mt-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-stone-500">
              {online ? locationText : "Go online to share location"}
            </p>
            <div className="mt-5 flex flex-wrap gap-2">
              <Btn
                variant={online ? "outline" : "primary"}
                disabled={busy === "availability"}
                onClick={onToggle}
              >
                {busy === "availability"
                  ? "Updating…"
                  : online
                    ? "Go offline"
                    : "Go online"}
              </Btn>
              <Btn
                variant="dark"
                onClick={onPing}
                disabled={busy === "ping" || !online}
              >
                {locationMode === "live" ? "Refresh GPS" : "Send location ping"}
              </Btn>
              {locationMode === "denied" ? (
                <Btn variant="ghost" onClick={onRetryGps}>
                  Retry GPS
                </Btn>
              ) : null}
            </div>
          </div>
          <div className="rounded-2xl border border-white/10 bg-white/[0.06] p-4 text-right backdrop-blur">
            <p className="text-[9px] uppercase tracking-[0.18em] text-stone-500">
              Today&apos;s earnings
            </p>
            <p className="mt-1 font-serif text-[38px] leading-none text-[#f4b942]">
              {formatCurrency(profile.today_earnings)}
            </p>
            <p className="mt-1 text-[10px] text-stone-500">
              {profile.today_deliveries} deliveries · ★{" "}
              {profile.average_rating.toFixed(1)}
            </p>
            <div className="mt-3 flex items-center justify-end gap-2">
              <SimBadge />
            </div>
          </div>
        </div>
      </section>

      <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
        <StatCard
          label="This week"
          value={formatCurrency(profile.week_earnings)}
          hint={`${profile.total_deliveries} lifetime drops`}
          accent="green"
        />
        <StatCard
          label="This month"
          value={formatCurrency(profile.month_earnings)}
          hint="Simulated payout ledger"
          accent="gold"
        />
        <StatCard
          label="Open offers"
          value={offers.length}
          hint={online ? "Refreshes every 12 sec" : "Go online to receive"}
          accent="orange"
        />
        <StatCard
          label="Vehicle"
          value={profile.vehicle.replaceAll("_", " ")}
          hint={profile.vehicle_registration ?? "Unregistered"}
          accent="stone"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
        <section className="rounded-[26px] border border-stone-900/10 bg-[#fffcf6]/70 p-4 sm:p-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-stone-500">
                Live delivery
              </p>
              <h2 className="mt-1 font-serif text-[24px] italic">
                {active ? "One bag, one promise" : "No delivery in hand"}
              </h2>
            </div>
            {active ? <StatusPill status={active.status} /> : null}
          </div>
          {active ? (
            <div className="mt-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-[13px] font-semibold">
                    {active.order.restaurant_name}
                  </p>
                  <p className="mt-1 text-[11px] text-stone-500">
                    {active.order.order_number ?? active.order.id.slice(0, 8)} ·{" "}
                    {active.order.items.length} lines
                  </p>
                </div>
                <p className="text-[16px] font-bold">
                  {formatCurrency(active.order.total_amount)}
                </p>
              </div>
              <p className="mt-2 text-[11px] leading-relaxed text-stone-500">
                {actionByStatus[active.status]?.hint ??
                  "This delivery is being coordinated."}
              </p>
              <Btn size="sm" className="mt-3" onClick={onDelivery}>
                Open live delivery →
              </Btn>
            </div>
          ) : (
            <div className="mt-4">
              <p className="text-[12px] leading-relaxed text-stone-500">
                {online
                  ? "Dispatch is monitoring restaurant-ready orders. Keep your location fresh."
                  : "You will not receive offers until you go online."}
              </p>
              <div className="mt-3 flex gap-2">
                <Btn size="sm" variant="outline" onClick={onOffers}>
                  See offers
                </Btn>
                <Btn size="sm" variant="ghost" onClick={onToggle}>
                  {online ? "Pause shift" : "Start shift"}
                </Btn>
              </div>
            </div>
          )}
        </section>

        <section className="rounded-[26px] border border-stone-900/10 bg-[#fffcf6]/70 p-4 sm:p-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-stone-500">
                Waiting for you
              </p>
              <h2 className="mt-1 font-serif text-[24px] italic">Offer radar</h2>
            </div>
            <span className="rounded-full bg-[#d94f2b]/10 px-2.5 py-1 text-[10px] font-bold text-[#b13d1f]">
              {offers.length}
            </span>
          </div>
          {offers.length === 0 ? (
            <p className="mt-4 text-[12px] leading-relaxed text-stone-500">
              No live offers. You are still in the candidate pool; the next ready order
              will find you.
            </p>
          ) : (
            <div className="mt-3 space-y-2">
              {offers.slice(0, 2).map((offer) => (
                <button
                  key={offer.assignment_id}
                  type="button"
                  onClick={onOffers}
                  className="w-full rounded-xl border border-stone-900/10 bg-white/50 p-3 text-left transition hover:bg-white"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-[12px] font-semibold">
                      {offer.restaurant_name}
                    </span>
                    <span className="text-[13px] font-bold text-[#1f5b46]">
                      {formatCurrency(offer.estimated_earnings)}
                    </span>
                  </div>
                  <p className="mt-1 text-[10px] text-stone-500">
                    {offer.pickup_distance_km.toFixed(1)} km pickup ·{" "}
                    {offer.delivery_distance_km.toFixed(1)} km drop
                  </p>
                </button>
              ))}
            </div>
          )}
          <Btn size="sm" variant="outline" className="mt-3" onClick={onOffers}>
            Open offers
          </Btn>
        </section>
      </div>

      <section className="rounded-[26px] border border-stone-900/10 bg-[#fffcf6]/70 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-stone-500">
              Rider health
            </p>
            <h2 className="mt-1 font-serif text-[22px] italic">Ready for the last mile</h2>
          </div>
          <span className="text-[10px] uppercase tracking-[0.14em] text-stone-500">
            {profile.verification_status.replaceAll("_", " ")} · capacity{" "}
            {profile.capacity}
          </span>
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          {[
            ["Average rating", `★ ${profile.average_rating.toFixed(2)}`],
            ["Lifetime drops", String(profile.total_deliveries)],
            [
              "Last ping",
              profile.last_seen_at ? timeAgo(profile.last_seen_at) : "Not yet",
            ],
          ].map(([label, value]) => (
            <div key={label} className="rounded-xl bg-stone-900/[0.03] px-3 py-2.5">
              <p className="text-[9px] uppercase tracking-[0.12em] text-stone-500">
                {label}
              </p>
              <p className="mt-1 text-[13px] font-semibold">{value}</p>
            </div>
          ))}
        </div>
        {earnings && earnings.entries.length > 0 ? (
          <p className="mt-3 text-[10px] text-stone-500">
            Latest drop: {earnings.entries[0].restaurant_name} ·{" "}
            {formatCurrency(earnings.entries[0].amount)}
          </p>
        ) : null}
      </section>
    </div>
  );
}

function OffersView({
  offers,
  online,
  busy,
  locationMode,
  locationAccuracyM,
  onToggle,
  onAccept,
  onPass,
  onRefresh,
}: {
  offers: Offer[];
  online: boolean;
  busy: string | null;
  locationMode: RiderLocationMode;
  locationAccuracyM: number | null;
  onToggle: () => void;
  onAccept: (offer: Offer) => void;
  onPass: (offer: Offer) => void;
  onRefresh: () => void;
}) {
  const now = useNow();
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500">
              Dispatch radar
            </p>
            <SimBadge />
          </div>
          <h1 className="mt-1 font-serif text-[38px] italic leading-none">
            Offers near you.
          </h1>
          <p className="mt-2 text-[12px] text-stone-500">
            Ranked by route ETA, load and vehicle fit. Offers expire in 20 seconds.
          </p>
          <p className="mt-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-stone-500">
            {online
              ? locationLabel(locationMode, locationAccuracyM)
              : "Go online to share location"}
          </p>
        </div>
        <div className="flex gap-2">
          <Btn size="sm" variant="outline" onClick={onRefresh}>
            Refresh
          </Btn>
          <Btn
            size="sm"
            variant={online ? "ghost" : "primary"}
            disabled={busy === "availability"}
            onClick={onToggle}
          >
            {online ? "Go offline" : "Go online"}
          </Btn>
        </div>
      </div>

      {!online ? (
        <Notice tone="info">
          You are offline, so dispatch is not sending offers. Go online above to join the
          candidate pool.
        </Notice>
      ) : null}

      {offers.length === 0 ? (
        <Empty
          title={online ? "The radar is quiet." : "You are off shift."}
          hint={
            online
              ? "No ready order needs you this second. This list refreshes every 12 seconds."
              : "Start a shift to receive live delivery offers."
          }
          action={
            online ? (
              <Btn variant="outline" onClick={onRefresh}>
                Check again
              </Btn>
            ) : (
              <Btn onClick={onToggle}>Go online</Btn>
            )
          }
        />
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        {offers.map((offer) => {
          const remaining = Math.max(
            0,
            Math.floor((new Date(offer.expires_at).getTime() - now) / 1000),
          );
          const urgent = remaining <= 20;
          return (
            <article
              key={offer.assignment_id}
              className="overflow-hidden rounded-[26px] border border-stone-900/10 bg-[#fffcf6]"
            >
              <div className="flex items-start justify-between gap-3 border-b border-stone-900/8 bg-[#1f5b46] px-4 py-3 text-[#f1f7ef]">
                <div>
                  <p className="text-[9px] font-bold uppercase tracking-[0.18em] opacity-70">
                    {offer.order_number ?? offer.order_id.slice(0, 8)}
                  </p>
                  <h2 className="mt-0.5 font-serif text-[22px] italic leading-none">
                    {offer.restaurant_name}
                  </h2>
                  {offer.batched_with ? (
                    <p className="mt-1.5 inline-block rounded-full bg-[#f4b942] px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.1em] text-stone-900">
                      Same-route drop · rides with {offer.batched_with}
                      {offer.batch_extra_km !== null && offer.batch_extra_km !== undefined
                        ? ` · +${offer.batch_extra_km} km`
                        : ""}
                    </p>
                  ) : null}
                </div>
                <div className="text-right">
                  <p className="font-serif text-[26px] leading-none text-[#f4b942]">
                    {formatCurrency(offer.estimated_earnings)}
                  </p>
                  <p className="text-[8px] uppercase tracking-[0.14em] opacity-60">
                    estimated earning
                  </p>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2 p-4">
                <div className="rounded-xl bg-stone-900/[0.03] p-2.5">
                  <p className="text-[8px] uppercase tracking-[0.14em] text-stone-500">
                    To pickup
                  </p>
                  <p className="mt-1 text-[15px] font-semibold">
                    {offer.pickup_distance_km.toFixed(1)} km
                  </p>
                  <p className="text-[9px] text-stone-500">
                    ~{Math.round(offer.pickup_eta_min)} min
                  </p>
                </div>
                <div className="rounded-xl bg-stone-900/[0.03] p-2.5">
                  <p className="text-[8px] uppercase tracking-[0.14em] text-stone-500">
                    Then drop
                  </p>
                  <p className="mt-1 text-[15px] font-semibold">
                    {offer.delivery_distance_km.toFixed(1)} km
                  </p>
                  <p className="text-[9px] text-stone-500">
                    {Math.round(offer.estimated_delivery_min)} min total
                  </p>
                </div>
                <div className="col-span-2 rounded-xl bg-stone-900/[0.03] p-2.5">
                  <p className="text-[8px] uppercase tracking-[0.14em] text-stone-500">
                    Pickup from
                  </p>
                  <p className="mt-0.5 truncate text-[11px] font-medium">
                    {offer.restaurant_address ?? "Restaurant address in the city"}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2 border-t border-stone-900/8 px-4 py-3">
                <span
                  className={`text-[10px] font-bold uppercase tracking-[0.1em] ${
                    urgent ? "text-rose-700" : "text-stone-500"
                  }`}
                >
                  {remaining > 0
                    ? `Expires in ${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, "0")}`
                    : "Expired"}
                </span>
                <div className="ml-auto flex gap-2">
                  <Btn
                    size="sm"
                    variant="ghost"
                    disabled={busy === offer.assignment_id || remaining <= 0}
                    onClick={() => onPass(offer)}
                  >
                    Pass
                  </Btn>
                  <Btn
                    size="sm"
                    disabled={busy === offer.assignment_id || remaining <= 0 || !online}
                    onClick={() => onAccept(offer)}
                  >
                    {busy === offer.assignment_id ? "…" : "Accept pickup"}
                  </Btn>
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}

function DeliveryView({
  active,
  tracking,
  route,
  busy,
  locationMode,
  locationAccuracyM,
  riderPosition,
  onAction,
  onPing,
  onRetryGps,
  onBrowseOffers,
}: {
  active: AssignmentAction | null;
  tracking: Tracking | null;
  route: TrackingRoute | null;
  busy: string | null;
  locationMode: RiderLocationMode;
  locationAccuracyM: number | null;
  riderPosition: { lat: number; lng: number } | null;
  onAction: () => void;
  onPing: () => void;
  onRetryGps: () => void;
  onBrowseOffers: () => void;
}) {
  if (!active) {
    return (
      <Empty
        title="No bag in hand."
        hint="Accept an offer and the step-by-step delivery flow will appear here."
        action={<Btn onClick={onBrowseOffers}>Open offers</Btn>}
      />
    );
  }
  const action = actionByStatus[active.status];
  const steps = [
    ["ACCEPTED", "Accepted"],
    ["ARRIVED_AT_RESTAURANT", "At restaurant"],
    ["PICKED_UP", "Picked up"],
    ["ARRIVED_AT_CUSTOMER", "At customer"],
    ["COMPLETED", "Complete"],
  ];
  const currentIndex = steps.findIndex(([status]) => status === active.status);
  const toDropM = riderPosition
    ? Math.round(
        Math.hypot(
          (riderPosition.lat - active.order.drop_lat) * 111_320,
          (riderPosition.lng - active.order.drop_lng) *
            111_320 *
            Math.cos((active.order.drop_lat * Math.PI) / 180),
        ),
      )
    : null;
  const onTheRoad = active.status === "PICKED_UP" || active.status === "ARRIVED_AT_CUSTOMER";

  return (
    <div className="space-y-5">
      <div>
        <div className="flex items-center gap-2">
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500">
            Live delivery
          </p>
          <SimBadge />
        </div>
        <h1 className="mt-1 font-serif text-[38px] italic leading-none">
          {action ? action.label : "Delivery complete."}
        </h1>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_340px] lg:items-start">
        <section className="overflow-hidden rounded-[26px] border border-stone-900/10 bg-[#fffcf6]">
          <div className="bg-[#1f5b46] px-4 py-4 text-[#f1f7ef] sm:px-5">
            <p className="text-[9px] font-bold uppercase tracking-[0.18em] opacity-70">
              {active.order.order_number ?? active.order.id.slice(0, 8)}
            </p>
            <h2 className="mt-1 font-serif text-[28px] italic leading-none">
              {active.order.restaurant_name}
            </h2>
            <p className="mt-2 text-[11px] opacity-70">
              {active.order.items.length} lines ·{" "}
              {formatCurrency(active.order.total_amount)} customer bill
            </p>
          </div>
          <div className="p-4 sm:p-5">
            <div className="flex items-center">
              {steps.map(([id, label], index) => (
                <div key={id} className="flex flex-1 items-center last:flex-none">
                  <div className="flex flex-col items-center gap-1.5">
                    <span
                      className={`flex h-6 w-6 items-center justify-center rounded-full border text-[8px] font-bold ${
                        currentIndex >= index
                          ? "border-[#1f5b46] bg-[#1f5b46] text-white"
                          : "border-stone-300 text-stone-400"
                      }`}
                    >
                      {currentIndex >= index ? "✓" : index + 1}
                    </span>
                    <span className="hidden text-[8px] font-semibold uppercase tracking-[0.05em] text-stone-500 sm:block">
                      {label}
                    </span>
                  </div>
                  {index < steps.length - 1 ? (
                    <span
                      className={`mx-1 h-px flex-1 ${
                        currentIndex > index ? "bg-[#1f5b46]" : "bg-stone-200"
                      }`}
                    />
                  ) : null}
                </div>
              ))}
            </div>

            {tracking ? (
              <div className="mt-5">
                <RouteMap tracking={tracking} route={route} />
              </div>
            ) : null}

            <div className="mt-5 rounded-2xl border border-stone-900/10 bg-stone-900/[0.02] p-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-[9px] font-bold uppercase tracking-[0.14em] text-stone-500">
                    Delivery address
                  </p>
                  <p className="mt-1 text-[12px] font-semibold">
                    {active.order.delivery_address ?? "Customer pin on file"}
                  </p>
                  {active.order.customer_phone ? (
                    <p className="mt-0.5 text-[10px] text-stone-500">
                      {active.order.customer_phone}
                    </p>
                  ) : null}
                </div>
                <p className="text-[10px] uppercase tracking-[0.1em] text-stone-400">
                  {active.order.drop_lat.toFixed(3)},{" "}
                  {active.order.drop_lng.toFixed(3)}
                </p>
              </div>
              {active.order.delivery_instructions ? (
                <p className="mt-2 rounded-lg bg-[#f4b942]/15 px-2.5 py-2 text-[10px] leading-relaxed text-[#7d5309]">
                  “{active.order.delivery_instructions}”
                </p>
              ) : null}
            </div>

            {active.batch && active.batch.length > 1 ? (
              <div className="mt-4 rounded-2xl border border-[#1f5b46]/25 bg-[#1f5b46]/[0.06] p-3">
                <p className="text-[9px] font-bold uppercase tracking-[0.14em] text-[#1f5b46]">
                  Shared ride · {active.batch.length} drops, in this order
                </p>
                <ol className="mt-1.5 space-y-1 text-[11px] text-stone-700">
                  {active.batch.map((drop) => (
                    <li key={drop.assignment_id} className="flex justify-between gap-2">
                      <span>
                        {drop.sequence}. {drop.order_number} · {drop.delivery_address ?? "pin"}
                      </span>
                      <span className="text-[9px] uppercase tracking-[0.08em] text-stone-500">
                        {drop.status.replaceAll("_", " ").toLowerCase()}
                      </span>
                    </li>
                  ))}
                </ol>
              </div>
            ) : null}

            {onTheRoad && toDropM !== null ? (
              <div
                className={`mt-4 rounded-2xl border p-3 text-[11px] ${
                  toDropM <= 150
                    ? "border-[#1f5b46]/30 bg-[#1f5b46]/[0.06] text-[#1f5b46]"
                    : "border-stone-900/10 bg-stone-900/[0.03] text-stone-600"
                }`}
              >
                <strong>{toDropM.toLocaleString()} m</strong> from the customer&apos;s pin ·{" "}
                {toDropM <= 150
                  ? "inside the handover zone"
                  : "handover unlocks within 150 m"}
              </div>
            ) : null}

            {action ? (
              <div className="mt-4 rounded-2xl border border-[#d94f2b]/20 bg-[#d94f2b]/[0.05] p-4">
                <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-[#b13d1f]">
                  Next action
                </p>
                <p className="mt-1 text-[12px] text-stone-600">{action.hint}</p>
                <Btn
                  className="mt-3 w-full"
                  disabled={busy === "action"}
                  onClick={onAction}
                >
                  {busy === "action" ? "Updating…" : action.label}
                </Btn>
              </div>
            ) : null}

            <div className="mt-3 flex items-center justify-between gap-2">
              <p className="text-[10px] text-stone-500">
                {locationMode === "live"
                  ? `Live GPS updates stream to the customer${
                      locationAccuracyM !== null
                        ? ` (+/- ${Math.round(locationAccuracyM)} m)`
                        : ""
                    }.`
                  : "Simulated location updates stream to the customer while GPS is unavailable."}
              </p>
              <div className="flex shrink-0 gap-2">
                {locationMode === "denied" ? (
                  <Btn
                    size="sm"
                    variant="ghost"
                    onClick={onRetryGps}
                  >
                    Retry GPS
                  </Btn>
                ) : null}
                <Btn
                  size="sm"
                  variant="outline"
                  disabled={busy === "ping"}
                  onClick={onPing}
                >
                  {locationMode === "live" ? "Refresh GPS" : "Ping now"}
                </Btn>
              </div>
            </div>
          </div>
        </section>

        <aside className="space-y-3">
          <section className="rounded-[24px] border border-stone-900/10 bg-[#fffcf6]/70 p-4">
            <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-stone-500">
              Order contents
            </p>
            <div className="mt-2 space-y-1.5">
              {active.order.items.map((item) => (
                <p key={item.menu_item_id} className="flex justify-between gap-2 text-[11px]">
                  <span className="text-stone-600">
                    {item.name} ×{item.qty}
                  </span>
                  <span className="font-semibold">
                    {formatCurrency(Number(item.unit_price) * item.qty)}
                  </span>
                </p>
              ))}
            </div>
            <p className="mt-3 border-t border-stone-900/10 pt-2 text-[9px] uppercase tracking-[0.1em] text-stone-400">
              {active.order.payment_method.replace("_DEMO", " demo")} ·{" "}
              {active.order.payment_status.replaceAll("_", " ")}
            </p>
          </section>

          <section className="rounded-[24px] border border-stone-900/10 bg-[#fffcf6]/70 p-4">
            <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-stone-500">
              Kitchen
            </p>
            <p className="mt-2 text-[12px] font-semibold">
              {active.order.restaurant_name}
            </p>
            <p className="mt-1 text-[10px] leading-relaxed text-stone-500">
              Placed {formatDateTime(active.order.placed_at)}. Collect the sealed bag only
              after the kitchen confirms pickup.
            </p>
          </section>
        </aside>
      </div>
    </div>
  );
}

function EarningsView({ earnings }: { earnings: Earnings | null }) {
  if (!earnings) {
    return <Spinner label="Counting your day" />;
  }
  const max = Math.max(
    ...earnings.entries.map((entry) => Number(entry.amount)),
    1,
  );
  return (
    <div className="space-y-5">
      <div>
        <div className="flex items-center gap-2">
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500">
            Rider ledger
          </p>
          <SimBadge />
        </div>
        <h1 className="mt-1 font-serif text-[38px] italic leading-none">
          Every drop, accounted for.
        </h1>
      </div>

      <div className="grid grid-cols-3 gap-2.5">
        <StatCard label="Today" value={formatCurrency(earnings.today)} accent="orange" />
        <StatCard label="This week" value={formatCurrency(earnings.week)} accent="green" />
        <StatCard label="This month" value={formatCurrency(earnings.month)} accent="gold" />
      </div>

      {earnings.entries.length === 0 ? (
        <Empty
          title="No completed drops yet."
          hint="Accept an offer, finish the delivery, and the ledger starts here."
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[240px_1fr] lg:items-start">
          <aside className="rounded-[24px] border border-stone-900/10 bg-[#fffcf6]/70 p-4">
            <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-stone-500">
              Lately
            </p>
            <p className="mt-1 font-serif text-[23px] italic">Drop rhythm</p>
            <div className="mt-4 flex h-28 items-end gap-1.5">
              {earnings.entries
                .slice(0, 12)
                .reverse()
                .map((entry) => (
                  <div
                    key={entry.order_id}
                    className="flex-1 rounded-t bg-[#1f5b46]/70"
                    style={{
                      height: `${Math.max(8, (Number(entry.amount) / max) * 100)}%`,
                    }}
                    title={`${entry.restaurant_name} · ${formatCurrency(entry.amount)}`}
                  />
                ))}
            </div>
            <p className="mt-3 text-[10px] leading-relaxed text-stone-500">
              {earnings.completed_deliveries} completed{" "}
              {earnings.completed_deliveries === 1 ? "drop" : "drops"} in this ledger.
            </p>
          </aside>

          <section className="overflow-hidden rounded-[26px] border border-stone-900/10 bg-[#fffcf6]/70">
            {earnings.entries.map((entry, index) => (
              <div
                key={entry.order_id}
                className={`flex items-center gap-3 px-4 py-3 ${
                  index > 0 ? "border-t border-stone-900/8" : ""
                }`}
              >
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#1f5b46]/10 font-serif text-[15px] italic text-[#1f5b46]">
                  {entry.restaurant_name.slice(0, 1)}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[12px] font-semibold">
                    {entry.restaurant_name}
                  </p>
                  <p className="mt-0.5 text-[9px] uppercase tracking-[0.1em] text-stone-400">
                    {entry.order_number ?? entry.order_id.slice(0, 8)} ·{" "}
                    {entry.distance_km.toFixed(1)} km · {timeAgo(entry.created_at)}
                  </p>
                </div>
                <p className="text-[14px] font-bold text-[#1f5b46]">
                  + {formatCurrency(entry.amount)}
                </p>
              </div>
            ))}
          </section>
        </div>
      )}
    </div>
  );
}

function HistoryView({ history }: { history: MarketOrder[] }) {
  return (
    <div className="space-y-5">
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500">
          Completed deliveries
        </p>
        <h1 className="mt-1 font-serif text-[38px] italic leading-none">
          The miles behind you.
        </h1>
      </div>
      {history.length === 0 ? (
        <Empty
          title="No completed deliveries yet."
          hint="Your first accepted offer will start this history."
          action={null}
        />
      ) : (
        <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
          {history.map((order) => (
            <article
              key={order.id}
              className="rounded-[24px] border border-stone-900/10 bg-[#fffcf6]/70 p-4"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[9px] font-bold uppercase tracking-[0.14em] text-stone-400">
                  {order.order_number ?? order.id.slice(0, 8)}
                </span>
                <StatusPill status={order.status} />
              </div>
              <h2 className="mt-1 font-serif text-[21px] italic leading-tight">
                {order.restaurant_name}
              </h2>
              <p className="mt-1 text-[10px] text-stone-500">
                {formatDateTime(order.actual_delivery_at ?? order.placed_at)}
              </p>
              <div className="mt-3 flex items-center justify-between border-t border-stone-900/8 pt-2 text-[10px]">
                <span className="text-stone-500">{order.items.length} lines</span>
                <span className="font-semibold">
                  {formatCurrency(order.total_amount)} bill
                </span>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

function locationLabel(
  mode: RiderLocationMode,
  accuracyM: number | null,
): string {
  if (mode === "live") {
    return `Live GPS${accuracyM !== null ? ` (+/- ${Math.round(accuracyM)} m)` : ""}`;
  }
  if (mode === "locating") return "Acquiring GPS fix";
  if (mode === "denied") return "GPS permission blocked";
  if (mode === "simulated") return "Simulated location fallback";
  return "Location off";
}

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}
