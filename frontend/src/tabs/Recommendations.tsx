import { useCallback, useEffect, useState } from "react";

import {
  Badge,
  EmptyState,
  ErrorNote,
  Loading,
  Panel,
  ScoreBar,
  SectionHeading,
  SimulatedBadge,
} from "../components/ui";
import {
  getCustomers,
  getMenuRecommendations,
  getRestaurantRecommendations,
} from "../lib/api";
import type {
  Customer,
  MenuRecommendation,
  RestaurantRecommendation,
} from "../lib/api";
import { formatCurrency } from "../lib/format";

export default function Recommendations() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [customerId, setCustomerId] = useState<string | null>(null);
  const [restaurantRecs, setRestaurantRecs] = useState<RestaurantRecommendation[]>([]);
  const [restaurantId, setRestaurantId] = useState<string | null>(null);
  const [menuRecs, setMenuRecs] = useState<MenuRecommendation[]>([]);
  const [loadingCustomers, setLoadingCustomers] = useState(true);
  const [loadingRecs, setLoadingRecs] = useState(false);
  const [loadingMenu, setLoadingMenu] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getCustomers()
      .then((rows) => {
        if (cancelled) return;
        setCustomers(rows);
        setCustomerId((current) => current ?? rows[0]?.id ?? null);
      })
      .catch((failure) => {
        if (!cancelled) {
          setError(failure instanceof Error ? failure.message : "Could not load customers");
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingCustomers(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const loadRecs = useCallback(async (id: string) => {
    setLoadingRecs(true);
    try {
      const rows = await getRestaurantRecommendations(id, 8);
      setRestaurantRecs(rows);
      setRestaurantId(rows[0]?.restaurant.id ?? null);
      setError(null);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not load recommendations");
    } finally {
      setLoadingRecs(false);
    }
  }, []);

  useEffect(() => {
    if (!customerId) return;
    void loadRecs(customerId);
  }, [customerId, loadRecs]);

  useEffect(() => {
    if (!customerId || !restaurantId) {
      setMenuRecs([]);
      return;
    }
    let cancelled = false;
    setLoadingMenu(true);
    getMenuRecommendations(customerId, restaurantId)
      .then((rows) => {
        if (!cancelled) setMenuRecs(rows);
      })
      .catch((failure) => {
        if (!cancelled) {
          setError(failure instanceof Error ? failure.message : "Could not load menu picks");
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingMenu(false);
      });
    return () => {
      cancelled = true;
    };
  }, [customerId, restaurantId]);

  const customer = customers.find((row) => row.id === customerId) ?? null;
  const selectedRestaurant =
    restaurantRecs.find((rec) => rec.restaurant.id === restaurantId) ?? null;

  return (
    <div className="space-y-5">
      <SectionHeading
        title="Recommendation engine"
        caption="Budget, diet, distance, rating and order history blended into ranked picks."
        action={<SimulatedBadge />}
      />

      {error ? <ErrorNote message={error} /> : null}

      <Panel className="p-4">
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-3 text-xs font-medium uppercase tracking-[0.16em] text-stone-500">
            Customer
            <select
              value={customerId ?? ""}
              onChange={(event) => setCustomerId(event.target.value)}
              className="rounded-xl border border-white/10 bg-[#0b1210] px-3 py-2 text-sm normal-case tracking-normal text-stone-200 outline-none transition focus:border-emerald-400/40"
              disabled={loadingCustomers || customers.length === 0}
            >
              {customers.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
            </select>
          </label>
          {customer ? (
            <div className="flex flex-wrap gap-1.5">
              <Badge tone="neutral">budget {customer.budget_pref ?? "any"}</Badge>
              <Badge tone="mint">diet {customer.diet_pref ?? "any"}</Badge>
              <Badge tone="sky">
                {customer.home_lat.toFixed(3)}, {customer.home_lng.toFixed(3)}
              </Badge>
            </div>
          ) : null}
        </div>
      </Panel>

      {loadingCustomers || loadingRecs ? (
        <Loading label="Ranking restaurants" />
      ) : restaurantRecs.length === 0 ? (
        <EmptyState
          title="No restaurant picks"
          hint="Seed the database first so the recommender has restaurants and order history."
        />
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {restaurantRecs.map((rec, index) => {
            const selected = rec.restaurant.id === restaurantId;
            return (
              <button
                key={rec.restaurant.id}
                type="button"
                onClick={() => setRestaurantId(rec.restaurant.id)}
                className={`rounded-2xl border p-4 text-left transition ${
                  selected
                    ? "border-emerald-400/35 bg-emerald-400/[0.05]"
                    : "border-white/10 bg-[#0b1210]/90 hover:border-white/20"
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-3">
                    <span className="mt-0.5 font-mono text-[11px] text-stone-500">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <div>
                      <p className="text-sm font-medium text-stone-100">
                        {rec.restaurant.name}
                      </p>
                      <p className="mt-0.5 text-xs text-stone-500">
                        {rec.restaurant.cuisine.join(" / ")} · {rec.restaurant.rating} rating
                      </p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="font-mono text-lg text-stone-100">{rec.score.toFixed(3)}</p>
                    <p className="text-[10px] uppercase tracking-[0.12em] text-stone-500">
                      match
                    </p>
                  </div>
                </div>

                <div className="mt-3">
                  <ScoreBar value={rec.score} tone={selected ? "mint" : "sky"} />
                </div>

                <div className="mt-2 flex flex-wrap gap-1.5">
                  <Badge tone="neutral">{rec.distance_km.toFixed(1)} km</Badge>
                  <Badge tone="neutral">
                    prep ~{rec.restaurant.avg_prep_min} min
                  </Badge>
                  {rec.reasons.map((reason) => (
                    <Badge key={reason} tone={selected ? "mint" : "neutral"}>
                      {reason}
                    </Badge>
                  ))}
                </div>
              </button>
            );
          })}
        </div>
      )}

      {selectedRestaurant ? (
        <Panel className="overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/5 px-5 py-4">
            <div>
              <p className="text-[10px] uppercase tracking-[0.16em] text-stone-500">
                Menu picks
              </p>
              <h3 className="mt-1 font-serif text-xl italic text-stone-100">
                {selectedRestaurant.restaurant.name}
              </h3>
            </div>
            <Badge tone="amber">Simulated preferences</Badge>
          </div>

          {loadingMenu ? (
            <div className="px-5">
              <Loading label="Ranking dishes" />
            </div>
          ) : menuRecs.length === 0 ? (
            <div className="p-5">
              <EmptyState
                title="No dishes match this diet"
                hint="The vegetarian filter removed every item at this restaurant."
              />
            </div>
          ) : (
            <ul className="grid gap-x-6 divide-y divide-white/5 px-5 sm:grid-cols-2 sm:divide-y-0">
              {menuRecs.map((rec) => (
                <li key={rec.item.id} className="border-b border-white/5 py-4 last:border-0">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-2.5">
                      <span
                        className={`mt-1.5 h-2 w-2 shrink-0 rounded-sm ring-1 ${
                          rec.item.veg
                            ? "bg-emerald-400/80 ring-emerald-300/50"
                            : "bg-rose-400/80 ring-rose-300/50"
                        }`}
                      />
                      <div>
                        <p className="text-sm text-stone-200">{rec.item.name}</p>
                        <p className="mt-0.5 font-mono text-[11px] text-stone-500">
                          {rec.item.category} · {formatCurrency(rec.item.price)} · complexity{" "}
                          {rec.item.prep_complexity}
                        </p>
                      </div>
                    </div>
                    <span className="font-mono text-sm text-stone-300">
                      {rec.score.toFixed(3)}
                    </span>
                  </div>
                  <div className="mt-2 pl-[18px]">
                    <ScoreBar value={rec.score} tone={rec.item.veg ? "mint" : "rose"} />
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {rec.reasons.map((reason) => (
                        <Badge key={reason} tone="neutral">
                          {reason}
                        </Badge>
                      ))}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      ) : null}

      <p className="max-w-3xl text-xs leading-relaxed text-stone-500">
        Ranking blends kitchen distance, budget fit, diet compatibility, rating, popularity
        and the customer's cuisine history. Recommendations are illustrative and built on
        simulated order data.
      </p>
    </div>
  );
}
