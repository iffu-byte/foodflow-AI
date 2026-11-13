import { useEffect, useState } from "react";

import {
  ApiError,
  getHonestStatus,
  getRestaurantTrust,
  getRescueLive,
  mediaUrl,
  type BrowseMenuItem,
  type HonestStatus,
  type NutritionView,
  type RescueDeal,
  type TrustProfile,
} from "../lib/api";
import { formatCurrency } from "../lib/format";
import { Btn, Modal, Notice, Spinner } from "./market";

const gradeTone: Record<string, string> = {
  A: "bg-[#1f5b46] text-white",
  B: "bg-[#4f7d3a] text-white",
  C: "bg-[#f4b942] text-stone-900",
  D: "bg-[#d94f2b] text-white",
};

export function TrustBadge({
  score,
  grade,
  compact = false,
}: {
  score: number | null | undefined;
  grade: string | null | undefined;
  compact?: boolean;
}) {
  if (score === null || score === undefined) return null;
  return (
    <span
      title="Trust score: licence, real location, kitchen photos, portion honesty and customer quantity ratings"
      className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-[10px] font-bold ${
        gradeTone[grade ?? "D"] ?? gradeTone.D
      }`}
    >
      <span aria-hidden>◆</span>
      {compact ? score : `Trust ${score}`}
    </span>
  );
}

const methodLabel: Record<string, string> = {
  photo_reference: "Photo-measured",
  container: "Container-measured",
  scale: "Weighed",
  pieces: "Counted",
  declared: "Declared by kitchen",
};

export function PortionLine({ item }: { item: BrowseMenuItem }) {
  const parts: string[] = [];
  if (item.portion_grams) parts.push(`≈ ${item.portion_grams} g`);
  if (item.portion_serves) parts.push(`serves ${item.portion_serves}`);
  if (item.portion_pieces) parts.push(`${item.portion_pieces} pc${item.portion_pieces > 1 ? "s" : ""}`);
  const method = item.portion_method ?? "unknown";
  const verified = ["photo_reference", "container", "scale", "pieces"].includes(method);
  if (!parts.length) {
    return (
      <p className="mt-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-rose-700/80">
        Quantity not declared
      </p>
    );
  }
  return (
    <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] font-semibold text-stone-700">
      <span>{parts.join(" · ")}</span>
      <span
        className={`rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-[0.08em] ${
          verified ? "bg-[#1f5b46]/10 text-[#1f5b46]" : "bg-stone-900/[0.06] text-stone-500"
        }`}
      >
        {verified ? "✓ " : ""}
        {methodLabel[method] ?? "Declared"}
      </span>
    </p>
  );
}

export function NutritionChips({ nutrition }: { nutrition: NutritionView | null | undefined }) {
  if (!nutrition) return null;
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1">
      <span
        title={`Estimate for ${nutrition.grams} g (${nutrition.grams_source} portion) · source: ${nutrition.source}`}
        className="rounded-full bg-[#f4b942]/20 px-2 py-0.5 text-[10px] font-bold text-[#7d5309]"
      >
        {nutrition.kcal} kcal
      </span>
      <span className="rounded-full bg-sky-700/10 px-2 py-0.5 text-[10px] font-semibold text-sky-900">
        {nutrition.protein_g} g protein
      </span>
      <span className="rounded-full bg-stone-900/[0.05] px-2 py-0.5 text-[10px] text-stone-500">
        {nutrition.carbs_g} g carbs · {nutrition.fat_g} g fat
      </span>
      {nutrition.allergens.slice(0, 4).map((allergen) => (
        <span
          key={allergen}
          className="rounded-full border border-rose-700/20 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.06em] text-rose-800"
        >
          {allergen}
        </span>
      ))}
      {nutrition.grams_source === "typical" ? (
        <span className="text-[9px] text-stone-400">typical portion</span>
      ) : null}
    </div>
  );
}

function daysAgo(value: string): string {
  const days = Math.floor((Date.now() - new Date(value).getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}

const verdictCopy: Record<string, { title: string; tone: string }> = {
  verified: { title: "Real kitchen found at this location", tone: "text-[#1f5b46]" },
  osm_match: { title: "Mapped food business matches this kitchen", tone: "text-[#1f5b46]" },
  osm_food_nearby: { title: "Food businesses at the pin, but not this name", tone: "text-[#8a5b0a]" },
  mismatch: { title: "Closest listing doesn't match", tone: "text-[#8a5b0a]" },
  closed: { title: "Map listing says closed", tone: "text-rose-800" },
  not_found: { title: "No matching listing near the pin", tone: "text-rose-800" },
  osm_no_food: { title: "No food business mapped at this pin", tone: "text-rose-800" },
  unchecked: { title: "Map check unavailable right now", tone: "text-stone-500" },
};

export function TrustPanel({ restaurantId }: { restaurantId: string }) {
  const [profile, setProfile] = useState<TrustProfile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);

  const load = (refresh = false) => {
    setLoading(true);
    setError(null);
    getRestaurantTrust(restaurantId, refresh)
      .then(setProfile)
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Could not check this kitchen."),
      )
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [restaurantId]);

  if (loading && !profile) {
    return (
      <section className="rounded-[26px] border border-stone-900/10 bg-[#fffcf6]/70 p-5">
        <Spinner label="Checking the real kitchen on the map" />
      </section>
    );
  }
  if (error || !profile) {
    return error ? <Notice>{error}</Notice> : null;
  }

  const reality = profile.reality;
  const verdict = verdictCopy[reality.verdict] ?? verdictCopy.unchecked;
  const match = reality.match;
  const osm = reality.osm;

  return (
    <section className="overflow-hidden rounded-[26px] border border-stone-900/10 bg-[#fffcf6]/80">
      <div className="flex flex-wrap items-center gap-4 border-b border-stone-900/8 p-4 sm:p-5">
        <div
          className={`flex h-16 w-16 shrink-0 flex-col items-center justify-center rounded-2xl ${
            gradeTone[profile.grade] ?? gradeTone.D
          }`}
        >
          <span className="font-serif text-[26px] leading-none">{profile.score}</span>
          <span className="text-[8px] font-bold uppercase tracking-[0.18em] opacity-80">
            Trust · {profile.grade}
          </span>
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-stone-500">
            Kitchen reality check
          </p>
          <h2 className={`mt-1 font-serif text-[22px] italic leading-tight ${verdict.tone}`}>
            {verdict.title}
          </h2>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {profile.badges.map((badge) => (
              <span
                key={badge}
                className="rounded-full bg-[#1f5b46]/10 px-2 py-0.5 text-[10px] font-semibold text-[#1f5b46]"
              >
                ✓ {badge}
              </span>
            ))}
            {profile.warnings.map((warning) => (
              <span
                key={warning}
                className="rounded-full bg-rose-700/10 px-2 py-0.5 text-[10px] font-semibold text-rose-800"
              >
                ! {warning}
              </span>
            ))}
          </div>
        </div>
        <div className="flex gap-2">
          <Btn size="sm" variant="outline" onClick={() => setOpen(true)}>
            Why this score
          </Btn>
          <Btn size="sm" variant="ghost" disabled={loading} onClick={() => load(true)}>
            {loading ? "Checking…" : "Re-check"}
          </Btn>
        </div>
      </div>

      <div className="grid gap-4 p-4 sm:p-5 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="space-y-3">
          {match && match.photos.length ? (
            <div>
              <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-stone-500">
                Photos of this location · Google Maps
              </p>
              <div className="mt-2 grid grid-cols-3 gap-1.5">
                {match.photos.slice(0, 6).map((photo) => (
                  <a
                    key={photo.url}
                    href={mediaUrl(photo.url) ?? undefined}
                    target="_blank"
                    rel="noreferrer"
                    className="group relative block aspect-square overflow-hidden rounded-xl bg-stone-200"
                    title={photo.attribution ? `Photo: ${photo.attribution}` : undefined}
                  >
                    <img
                      src={mediaUrl(photo.url) ?? undefined}
                      alt="Location photo from Google Maps"
                      loading="lazy"
                      className="h-full w-full object-cover transition group-hover:scale-105"
                    />
                  </a>
                ))}
              </div>
            </div>
          ) : (
            <div className="overflow-hidden rounded-2xl border border-stone-900/10">
              <iframe
                title="Kitchen pin on OpenStreetMap"
                className="h-[190px] w-full"
                loading="lazy"
                src={`https://www.openstreetmap.org/export/embed.html?bbox=${profile.lng - 0.004},${profile.lat - 0.0025},${profile.lng + 0.004},${profile.lat + 0.0025}&layer=mapnik&marker=${profile.lat},${profile.lng}`}
              />
              <p className="bg-stone-900/[0.03] px-3 py-1.5 text-[9px] text-stone-500">
                Map data © OpenStreetMap contributors · the pin is where this kitchen says it
                cooks
              </p>
            </div>
          )}

          {match ? (
            <div className="rounded-2xl border border-stone-900/10 bg-white/60 p-3 text-[11px] text-stone-600">
              <p className="font-semibold text-stone-900">{match.name}</p>
              <p className="mt-0.5">{match.address}</p>
              <p className="mt-1 text-[10px] text-stone-500">
                {match.distance_m !== null ? `${Math.round(match.distance_m)} m from the pin · ` : ""}
                {match.rating ? `★ ${match.rating} (${match.rating_count} Google ratings) · ` : ""}
                {match.business_status?.toLowerCase().replaceAll("_", " ")}
              </p>
              {match.maps_url ? (
                <a
                  href={match.maps_url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-1 inline-block text-[10px] font-semibold text-[#1f5b46] underline"
                >
                  Open in Google Maps
                </a>
              ) : null}
            </div>
          ) : null}

          {osm ? (
            <div className="rounded-2xl border border-stone-900/10 bg-white/60 p-3 text-[11px] text-stone-600">
              <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-stone-500">
                What OpenStreetMap shows at the pin
              </p>
              {osm.object_at_pin ? (
                <p className="mt-1">
                  Nearest mapped place to the pin:{" "}
                  <strong>
                    {osm.object_at_pin.name ||
                      `${osm.object_at_pin.type ?? "unknown"} (${osm.object_at_pin.category ?? ""})`}
                  </strong>
                  {osm.object_at_pin.distance_m !== null && osm.object_at_pin.distance_m !== undefined
                    ? ` · ${Math.round(osm.object_at_pin.distance_m)} m away`
                    : ""}
                </p>
              ) : null}
              {osm.food_places_at_pin.length ? (
                <ul className="mt-1 space-y-0.5">
                  {osm.food_places_at_pin.slice(0, 4).map((place) => (
                    <li key={`${place.name}-${place.distance_m}`}>
                      {place.name} · {place.amenity} ·{" "}
                      {place.distance_m !== null ? `${Math.round(place.distance_m)} m` : "?"}
                      {place.name_similarity >= 0.6 ? " · name matches" : ""}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-1">No food business is mapped within 80 m of this pin.</p>
              )}
            </div>
          ) : null}
        </div>

        <div className="space-y-3">
          <div className="rounded-2xl border border-stone-900/10 bg-white/60 p-3">
            <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-stone-500">
              Food licence
            </p>
            <p
              className={`mt-1 text-[12px] font-semibold ${
                profile.fssai.status === "format_ok" ? "text-[#1f5b46]" : "text-rose-800"
              }`}
            >
              {profile.fssai.number ? `FSSAI ${profile.fssai.number}` : "No FSSAI number"}
            </p>
            <p className="mt-0.5 text-[10px] text-stone-500">{profile.fssai.label}</p>
            <a
              href={profile.fssai.verify_url}
              target="_blank"
              rel="noreferrer"
              className="mt-1 inline-block text-[10px] font-semibold text-[#1f5b46] underline"
            >
              Verify on FoSCoS (govt portal)
            </a>
          </div>

          {profile.shared_kitchen.length ? (
            <div className="rounded-2xl border border-[#d94f2b]/25 bg-[#d94f2b]/[0.06] p-3 text-[11px] text-stone-700">
              <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-[#b13d1f]">
                Same kitchen, other names
              </p>
              <p className="mt-1">
                This kitchen also sells as{" "}
                <strong>{profile.shared_kitchen.map((row) => row.name).join(", ")}</strong>.
                {profile.kitchen_type === "dine_in"
                  ? " It lists itself as a dine-in restaurant."
                  : " It discloses that it is a shared/cloud kitchen."}
              </p>
            </div>
          ) : null}

          <div className="rounded-2xl border border-stone-900/10 bg-white/60 p-3">
            <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-stone-500">
              Kitchen photos from the restaurant
            </p>
            {profile.kitchen_photos.length ? (
              <div className="mt-2 grid grid-cols-3 gap-1.5">
                {profile.kitchen_photos.slice(0, 3).map((photo) => (
                  <figure key={photo.id} className="overflow-hidden rounded-xl bg-stone-200">
                    <img
                      src={mediaUrl(photo.url) ?? undefined}
                      alt={photo.caption || "Kitchen photo"}
                      className="aspect-square w-full object-cover"
                    />
                    <figcaption className="px-1.5 py-1 text-[9px] text-stone-500">
                      {daysAgo(photo.taken_at)}
                    </figcaption>
                  </figure>
                ))}
              </div>
            ) : (
              <p className="mt-1 text-[11px] text-stone-500">
                No kitchen photos yet. Ask the restaurant to add some.
              </p>
            )}
          </div>

          {reality.signals && reality.signals.reviews_read ? (
            <div className="rounded-2xl border border-stone-900/10 bg-white/60 p-3 text-[11px] text-stone-600">
              <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-stone-500">
                What Google reviewers say
              </p>
              <p className="mt-1">
                Of {reality.signals.reviews_read} recent reviews:{" "}
                {reality.signals.quantity_mentions} mention quantity,{" "}
                {reality.signals.hygiene_mentions} mention hygiene,{" "}
                {reality.signals.cloud_kitchen_mentions} call it delivery-only.
              </p>
            </div>
          ) : null}
        </div>
      </div>

      {open ? (
        <Modal title={`Trust score ${profile.score}/100`} onClose={() => setOpen(false)}>
          <div className="space-y-2.5">
            {profile.components.map((component) => (
              <div key={component.key}>
                <div className="flex items-center justify-between text-[12px] font-semibold">
                  <span>{component.label}</span>
                  <span>
                    {component.points}/{component.max}
                  </span>
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-stone-900/10">
                  <div
                    className="h-full rounded-full bg-[#1f5b46]"
                    style={{ width: `${(component.points / component.max) * 100}%` }}
                  />
                </div>
                <p className="mt-1 text-[11px] text-stone-500">{component.detail}</p>
              </div>
            ))}
            <p className="border-t border-stone-900/10 pt-2 text-[10px] text-stone-400">
              Checked {new Date(reality.checked_at).toLocaleString()} via{" "}
              {reality.provider === "google"
                ? "Google Maps"
                : reality.provider === "osm"
                  ? "OpenStreetMap"
                  : "no map provider"}
              . Ranking on FoodFlow is never paid.
            </p>
          </div>
        </Modal>
      ) : null}
    </section>
  );
}

function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);
  return now;
}

function countdown(until: string, now: number): string {
  const seconds = Math.max(0, Math.floor((new Date(until).getTime() - now) / 1000));
  const minutes = Math.floor(seconds / 60);
  return minutes >= 60
    ? `${Math.floor(minutes / 60)}h ${minutes % 60}m`
    : `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

export function RescueStrip({
  lat,
  lng,
  onAdd,
  busyId,
}: {
  lat?: number;
  lng?: number;
  onAdd: (deal: RescueDeal) => void;
  busyId: string | null;
}) {
  const [deals, setDeals] = useState<RescueDeal[]>([]);
  const now = useNow();

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      getRescueLive(lat, lng)
        .then((rows) => {
          if (!cancelled) setDeals(rows);
        })
        .catch(() => undefined);
    void load();
    const timer = window.setInterval(load, 30_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [lat, lng]);

  const live = deals.filter((deal) => new Date(deal.ends_at).getTime() > now);
  if (!live.length) return null;
  return (
    <section className="rounded-[26px] border border-[#1f5b46]/25 bg-[#1f5b46]/[0.06] p-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-[#1f5b46]">
            Rescue a meal · fresh food that would otherwise be thrown away
          </p>
          <h2 className="mt-1 font-serif text-[24px] italic leading-none">
            Prices drop until closing
          </h2>
        </div>
        <p className="text-[10px] text-stone-500">Updated every 30 s</p>
      </div>
      <div className="mt-3 flex gap-2.5 overflow-x-auto pb-1">
        {live.map((deal) => (
          <div
            key={deal.id}
            className="w-[230px] shrink-0 rounded-2xl border border-stone-900/10 bg-[#fffcf6] p-3"
          >
            <p className="truncate text-[10px] uppercase tracking-[0.12em] text-stone-500">
              {deal.restaurant_name}
              {deal.distance_km !== null ? ` · ${deal.distance_km.toFixed(1)} km` : ""}
            </p>
            <p className="mt-1 truncate text-[14px] font-semibold">{deal.name}</p>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="font-serif text-[22px] text-[#1f5b46]">
                {formatCurrency(deal.current_price)}
              </span>
              <span className="text-[11px] text-stone-400 line-through">
                {formatCurrency(deal.original_price)}
              </span>
              <span className="text-[10px] font-bold text-[#d94f2b]">−{deal.discount_pct}%</span>
            </div>
            <p className="mt-1 text-[10px] text-stone-500">
              {formatCurrency(deal.price_in_10_min)} in 10 min · floor{" "}
              {formatCurrency(deal.floor_price)}
            </p>
            <p className="mt-0.5 text-[10px] text-stone-500">
              {deal.qty_left} left · ends in {countdown(deal.ends_at, now)}
            </p>
            <Btn
              size="sm"
              className="mt-2 w-full"
              disabled={busyId === deal.id}
              onClick={() => onAdd(deal)}
            >
              {busyId === deal.id ? "Adding…" : "Rescue it"}
            </Btn>
          </div>
        ))}
      </div>
    </section>
  );
}

const ownerLabel: Record<string, string> = {
  restaurant: "Kitchen",
  platform: "FoodFlow (finding a rider)",
  rider: "Rider",
};

export function DelayBreakdown({ status }: { status: HonestStatus }) {
  const attribution = status.attribution;
  if (!attribution || !attribution.segments.length) return null;
  return (
    <div className="rounded-2xl border border-stone-900/10 bg-white/60 p-3">
      <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-stone-500">
        Where the time went
      </p>
      <div className="mt-2 space-y-1.5">
        {attribution.segments.map((segment) => (
          <div key={segment.stage} className="text-[11px]">
            <div className="flex justify-between gap-2">
              <span className="text-stone-700">
                {segment.stage}{" "}
                <span className="text-[9px] uppercase tracking-[0.08em] text-stone-400">
                  {ownerLabel[segment.owner]}
                </span>
              </span>
              <span className={segment.over_min > 2 ? "font-semibold text-rose-800" : "text-stone-500"}>
                {segment.actual_min} / {segment.expected_min} min
              </span>
            </div>
          </div>
        ))}
      </div>
      {attribution.message ? (
        <p className="mt-2 rounded-lg bg-[#f4b942]/15 px-2.5 py-2 text-[11px] text-[#7d5309]">
          {attribution.message}
        </p>
      ) : null}
    </div>
  );
}

export function HonestStatusCard({
  orderId,
  refreshKey,
  onCancel,
}: {
  orderId: string;
  refreshKey?: unknown;
  onCancel?: () => void;
}) {
  const [status, setStatus] = useState<HonestStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      getHonestStatus(orderId)
        .then((next) => {
          if (!cancelled) setStatus(next);
        })
        .catch(() => undefined);
    void load();
    const timer = window.setInterval(load, 15_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [orderId, refreshKey]);

  if (!status) return null;
  const waitingTone: Record<string, string> = {
    restaurant: "bg-violet-700/10 text-violet-900",
    platform: "bg-[#d94f2b]/10 text-[#9c3415]",
    rider: "bg-sky-700/10 text-sky-900",
    none: "bg-stone-900/[0.06] text-stone-600",
  };
  return (
    <section className="space-y-3 rounded-[24px] border border-stone-900/10 bg-[#fffcf6]/80 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-stone-500">
            Honest status · no frozen timers
          </p>
          <h3 className="mt-1 font-serif text-[22px] italic leading-tight">{status.headline}</h3>
          <p className="mt-1 text-[12px] text-stone-600">{status.detail}</p>
        </div>
        {status.waiting_on !== "none" ? (
          <span
            className={`rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.1em] ${waitingTone[status.waiting_on]}`}
          >
            Waiting on {status.waiting_on === "platform" ? "us" : status.waiting_on}
          </span>
        ) : null}
      </div>
      {status.live_eta_min !== null ? (
        <div className="grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-3">
          <div className="rounded-xl bg-stone-900/[0.04] p-2.5">
            <p className="text-[9px] uppercase tracking-[0.14em] text-stone-500">Live estimate</p>
            <p className="mt-0.5 font-serif text-[20px]">~{status.live_eta_min} min</p>
          </div>
          <div className="rounded-xl bg-stone-900/[0.04] p-2.5">
            <p className="text-[9px] uppercase tracking-[0.14em] text-stone-500">Promised</p>
            <p className="mt-0.5 font-serif text-[20px]">
              {status.promised_min_left !== null
                ? status.promised_min_left >= 0
                  ? `${Math.round(status.promised_min_left)} min left`
                  : `${Math.round(-status.promised_min_left)} min over`
                : "—"}
            </p>
          </div>
          <div className="rounded-xl bg-stone-900/[0.04] p-2.5">
            <p className="text-[9px] uppercase tracking-[0.14em] text-stone-500">Riders asked</p>
            <p className="mt-0.5 font-serif text-[20px]">{status.riders_asked}</p>
          </div>
        </div>
      ) : null}
      {status.running_late ? (
        <Notice tone="info">
          Running later than promised. If the delay is ours or the rider's, a credit is applied
          automatically at delivery — no chat needed.
        </Notice>
      ) : null}
      {status.batch ? (
        <div className="rounded-xl border border-[#1f5b46]/20 bg-[#1f5b46]/[0.05] p-3 text-[11px] text-[#1f5b46]">
          Shared ride: you are drop {status.batch.your_drop} of {status.batch.size}. You saved{" "}
          {formatCurrency(status.batch.saving)} and one extra trip.
        </div>
      ) : status.delivery_mode === "shared" ? (
        <div className="rounded-xl border border-[#1f5b46]/20 bg-[#1f5b46]/[0.05] p-3 text-[11px] text-[#1f5b46]">
          Shared ride chosen. If a same-route order is found, you'll see your drop number here.
        </div>
      ) : null}
      {status.free_cancel && onCancel ? (
        <div className="rounded-xl border border-[#d94f2b]/25 bg-[#d94f2b]/[0.06] p-3">
          <p className="text-[11px] text-stone-700">{status.free_cancel}</p>
          <Btn size="sm" variant="danger" className="mt-2" onClick={onCancel}>
            Cancel with full refund
          </Btn>
        </div>
      ) : null}
      {Number(status.compensation) > 0 ? (
        <Notice tone="success">
          {formatCurrency(status.compensation)} credited to you for this order.
        </Notice>
      ) : null}
      <DelayBreakdown status={status} />
      <p className="text-[9px] text-stone-400">{status.estimate_basis}</p>
    </section>
  );
}

export function OtpCard({ otp, status }: { otp: string | null | undefined; status: string }) {
  if (!otp || ["DELIVERED", "CANCELLED", "FAILED"].includes(status)) return null;
  return (
    <section className="rounded-[24px] bg-stone-900 p-4 text-[#f8f3e9]">
      <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-[#f4b942]">
        Delivery code
      </p>
      <p className="mt-1 font-mono text-[40px] font-bold leading-none tracking-[0.35em]">{otp}</p>
      <p className="mt-2 text-[11px] leading-relaxed text-stone-400">
        Share it only when the bag is in your hand. The rider can't mark this order delivered
        without it, and only within {150} m of your pin.
      </p>
    </section>
  );
}

export function PortionPhotoModal({
  item,
  onClose,
}: {
  item: BrowseMenuItem;
  onClose: () => void;
}) {
  return (
    <Modal title={`${item.name} · real portion`} onClose={onClose}>
      {item.portion_photo_url ? (
        <img
          src={mediaUrl(item.portion_photo_url) ?? undefined}
          alt={`${item.name} portion photo`}
          className="w-full rounded-2xl object-cover"
        />
      ) : null}
      <p className="mt-3 text-[12px] text-stone-600">
        {item.portion_grams ? `≈ ${item.portion_grams} g` : ""}
        {item.portion_serves ? ` · serves ${item.portion_serves}` : ""}
        {item.portion_confidence ? ` · ${Math.round(item.portion_confidence * 100)}% confidence` : ""}
      </p>
      <p className="mt-1 text-[10px] text-stone-400">
        Photographed by the kitchen with a reference object for scale
        {item.portion_verified_at
          ? ` on ${new Date(item.portion_verified_at).toLocaleDateString()}`
          : ""}
        . Not a stock or AI image.
      </p>
    </Modal>
  );
}
