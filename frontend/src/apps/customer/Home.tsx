import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  browseRestaurants,
  getMyOrders,
  getRestaurantRecommendations,
  reorder,
  type AuthUser,
  type BrowseRestaurant,
  type Cart,
  type MarketOrder,
  type RestaurantRecommendation,
} from "../../lib/api";
import {
  formatCurrency,
  formatMinutes,
  timeAgo,
} from "../../lib/format";
import { navigate } from "../../lib/session";
import {
  Btn,
  Empty,
  Notice,
  ProductArt,
  SimBadge,
  Spinner,
} from "../../components/market";

const cuisines = [
  { id: "", label: "Everything" },
  { id: "biryani", label: "Biryani" },
  { id: "north_indian", label: "North Indian" },
  { id: "south_indian", label: "South Indian" },
  { id: "italian", label: "Italian" },
  { id: "chinese", label: "Chinese" },
  { id: "fast_food", label: "Fast food" },
  { id: "desserts", label: "Desserts" },
  { id: "cafe", label: "Cafe" },
];

export function Home({
  user,
  onCartUpdated,
}: {
  user: AuthUser;
  onCartUpdated: (cart: Cart) => void;
}) {
  const [restaurants, setRestaurants] = useState<BrowseRestaurant[]>([]);
  const [orders, setOrders] = useState<MarketOrder[]>([]);
  const [recommendations, setRecommendations] = useState<RestaurantRecommendation[]>([]);
  const [q, setQ] = useState("");
  const [cuisine, setCuisine] = useState("");
  const [vegOnly, setVegOnly] = useState(false);
  const [topRated, setTopRated] = useState(false);
  const [sort, setSort] = useState<"recommended" | "rating" | "fastest">("recommended");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reordering, setReordering] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError(null);
      browseRestaurants({
        q: q.trim() || undefined,
        cuisine: cuisine || undefined,
        veg: vegOnly || undefined,
        min_rating: topRated ? 4 : undefined,
      })
        .then((rows) => {
          if (!cancelled) setRestaurants(rows);
        })
        .catch((err) => {
          if (!cancelled) {
            setError(err instanceof ApiError ? err.message : "Could not load kitchens.");
          }
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 220);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [q, cuisine, vegOnly, topRated]);

  useEffect(() => {
    void getMyOrders()
      .then(setOrders)
      .catch(() => undefined);
    void getRestaurantRecommendations(user.id, 4)
      .then(setRecommendations)
      .catch(() => undefined);
  }, [user.id]);

  const sorted = useMemo(() => {
    const rows = [...restaurants];
    if (sort === "rating") {
      rows.sort((a, b) => Number(b.rating) - Number(a.rating));
    } else if (sort === "fastest") {
      rows.sort((a, b) => a.avg_prep_min - b.avg_prep_min);
    }
    return rows;
  }, [restaurants, sort]);

  const past = orders.filter((order) => order.status === "DELIVERED").slice(0, 3);
  const featured =
    restaurants.find(
      (restaurant) => restaurant.id === recommendations[0]?.restaurant.id,
    ) ?? restaurants[0];
  const featuredReason = recommendations[0]?.reasons?.[0];

  const orderAgain = async (orderId: string) => {
    setReordering(orderId);
    try {
      const cart = await reorder(orderId);
      onCartUpdated(cart);
      navigate("/customer/cart");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not rebuild that cart.");
    } finally {
      setReordering(null);
    }
  };

  return (
    <div className="space-y-8">
      <section className="relative overflow-hidden rounded-[30px] bg-[#171512] px-5 py-7 text-[#f8f3e9] sm:px-8 sm:py-9">
        <div className="pointer-events-none absolute -right-20 -top-24 h-80 w-80 rounded-full bg-[radial-gradient(circle,rgba(217,79,43,0.55),transparent_62%)]" />
        <div className="pointer-events-none absolute bottom-0 left-1/3 h-56 w-56 rounded-full bg-[radial-gradient(circle,rgba(31,91,70,0.6),transparent_66%)]" />
        <div className="relative grid gap-8 lg:grid-cols-[1.15fr_0.85fr] lg:items-center">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-semibold uppercase tracking-[0.24em] text-[#e8a27d]">
                {new Date().toLocaleDateString("en-GB", {
                  weekday: "long",
                  day: "numeric",
                  month: "short",
                })}
              </span>
              <span className="h-1 w-1 rounded-full bg-stone-600" />
              <span className="text-[10px] uppercase tracking-[0.18em] text-stone-500">
                Hyderabad
              </span>
            </div>
            <h1 className="mt-3 max-w-2xl font-serif text-[38px] italic leading-[0.97] tracking-[-0.015em] sm:text-[50px]">
              What sounds good
              <br />
              tonight, {user.name.split(" ")[0]}?
            </h1>
            <p className="mt-3 max-w-md text-[13px] leading-relaxed text-stone-400">
              Thirty neighbourhood kitchens, one honest ETA. Pick a craving and we will
              handle the rest.
            </p>

            <div className="mt-6 flex items-center gap-2 rounded-full border border-white/15 bg-white/[0.08] p-1.5 pl-4 backdrop-blur">
              <span className="text-stone-400">⌕</span>
              <input
                value={q}
                onChange={(event) => setQ(event.target.value)}
                placeholder="Search biryani, pizza, a late-night filter coffee…"
                className="min-w-0 flex-1 bg-transparent py-1.5 text-[13px] text-[#f8f3e9] outline-none placeholder:text-stone-500"
              />
              {q ? (
                <button
                  type="button"
                  onClick={() => setQ("")}
                  className="px-2 text-[11px] text-stone-500 hover:text-white"
                >
                  Clear
                </button>
              ) : null}
              <span className="hidden rounded-full bg-[#d94f2b] px-3 py-2 text-[10px] font-bold uppercase tracking-[0.12em] sm:block">
                Search
              </span>
            </div>

            <div className="mt-4 flex flex-wrap gap-1.5">
              {cuisines.slice(1, 6).map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setCuisine(cuisine === item.id ? "" : item.id)}
                  className={`rounded-full border px-2.5 py-1 text-[10px] font-medium transition ${
                    cuisine === item.id
                      ? "border-[#f4b942]/60 bg-[#f4b942]/15 text-[#f4b942]"
                      : "border-white/15 text-stone-400 hover:border-white/30 hover:text-stone-200"
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>

          {featured ? (
            <button
              type="button"
              onClick={() => navigate(`/customer/restaurants/${featured.id}`)}
              className="group relative overflow-hidden rounded-[24px] bg-[#fffcf6] text-left text-stone-900 shadow-[0_30px_80px_-40px_rgba(0,0,0,0.8)] transition hover:-translate-y-0.5"
            >
              <ProductArt
                cuisine={featured.cuisine}
                name={featured.name}
                className="h-[150px]"
              />
              <div className="p-4">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[9px] font-bold uppercase tracking-[0.18em] text-[#d94f2b]">
                    Tonight&apos;s pick
                  </span>
                  <SimBadge />
                </div>
                <p className="mt-1.5 font-serif text-[21px] italic leading-tight">
                  {featured.name}
                </p>
                <p className="mt-1 line-clamp-2 text-[11px] leading-snug text-stone-500">
                  {featuredReason || featured.description}
                </p>
                <div className="mt-3 flex items-center gap-3 text-[10px] font-semibold uppercase tracking-[0.08em] text-stone-500">
                  <span>★ {Number(featured.rating).toFixed(1)}</span>
                  <span>{featured.avg_prep_min} min</span>
                  <span className="ml-auto text-[#1f5b46] group-hover:underline">
                    Open menu →
                  </span>
                </div>
              </div>
            </button>
          ) : null}
        </div>
      </section>

      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        {[
          [`${restaurants.length || 30}`, "kitchens live"],
          ["25 min", "median promise"],
          ["₹499+", "free delivery"],
          ["4 sides", "one order flow"],
        ].map(([value, label]) => (
          <div
            key={label}
            className="rounded-2xl border border-stone-900/10 bg-white/40 px-3.5 py-3"
          >
            <p className="font-serif text-[20px] leading-none">{value}</p>
            <p className="mt-1 text-[9px] uppercase tracking-[0.16em] text-stone-500">
              {label}
            </p>
          </div>
        ))}
      </div>

      {past.length > 0 ? (
        <section>
          <div className="mb-3 flex items-end justify-between gap-3">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500">
                Muscle memory
              </p>
              <h2 className="mt-1 font-serif text-[26px] italic leading-none">
                Order it again
              </h2>
            </div>
            <button
              type="button"
              onClick={() => navigate("/customer/orders")}
              className="text-[11px] font-semibold text-stone-500 hover:text-stone-900"
            >
              See all orders →
            </button>
          </div>
          <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
            {past.map((order) => (
              <div
                key={order.id}
                className="flex items-center gap-3 rounded-2xl border border-stone-900/10 bg-[#fffcf6]/70 p-3"
              >
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-[#1f5b46] font-serif text-[18px] italic text-[#f1f7ef]">
                  {order.restaurant_name.slice(0, 1)}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-semibold">
                    {order.restaurant_name}
                  </p>
                  <p className="mt-0.5 truncate text-[10px] text-stone-500">
                    {order.items.map((item) => `${item.name} ×${item.qty}`).join(", ")}
                  </p>
                  <p className="mt-0.5 text-[9px] uppercase tracking-[0.12em] text-stone-400">
                    {timeAgo(order.placed_at)} · {formatCurrency(order.total_amount)}
                  </p>
                </div>
                <Btn
                  size="sm"
                  variant="outline"
                  disabled={reordering === order.id}
                  onClick={() => void orderAgain(order.id)}
                >
                  {reordering === order.id ? "…" : "Again"}
                </Btn>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500">
              The neighbourhood
            </p>
            <h2 className="mt-1 font-serif text-[30px] italic leading-none">
              All kitchens
            </h2>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setVegOnly((value) => !value)}
              className={`rounded-full border px-3 py-1.5 text-[11px] font-semibold transition ${
                vegOnly
                  ? "border-[#1f5b46] bg-[#1f5b46] text-white"
                  : "border-stone-900/15 bg-white/40 text-stone-600"
              }`}
            >
              Pure veg
            </button>
            <button
              type="button"
              onClick={() => setTopRated((value) => !value)}
              className={`rounded-full border px-3 py-1.5 text-[11px] font-semibold transition ${
                topRated
                  ? "border-[#b47816] bg-[#f4b942] text-stone-900"
                  : "border-stone-900/15 bg-white/40 text-stone-600"
              }`}
            >
              ★ 4.0+
            </button>
            <select
              value={sort}
              onChange={(event) =>
                setSort(event.target.value as "recommended" | "rating" | "fastest")
              }
              className="rounded-full border border-stone-900/15 bg-white/40 px-3 py-1.5 text-[11px] font-semibold text-stone-600 outline-none"
            >
              <option value="recommended">Recommended</option>
              <option value="rating">Top rated</option>
              <option value="fastest">Fastest</option>
            </select>
          </div>
        </div>

        <div className="mt-4 flex gap-1.5 overflow-x-auto pb-2">
          {cuisines.map((item) => (
            <button
              key={item.id || "all"}
              type="button"
              onClick={() => setCuisine(item.id)}
              className={`shrink-0 rounded-full border px-3.5 py-1.5 text-[11px] font-medium transition ${
                cuisine === item.id
                  ? "border-stone-900 bg-stone-900 text-[#f8f3e9]"
                  : "border-stone-900/12 bg-white/40 text-stone-600 hover:bg-white"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>

        {error ? <div className="mt-3"><Notice>{error}</Notice></div> : null}
        {loading ? <Spinner label="Setting the tables" /> : null}
        {!loading && sorted.length === 0 ? (
          <Empty
            title="Nothing matches that craving yet."
            hint="Try a wider cuisine, clear the veg filter, or search a dish instead."
            action={
              <Btn
                variant="outline"
                onClick={() => {
                  setQ("");
                  setCuisine("");
                  setVegOnly(false);
                  setTopRated(false);
                }}
              >
                Reset filters
              </Btn>
            }
          />
        ) : null}
        <div className="mt-2 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {sorted.map((restaurant) => (
            <button
              key={restaurant.id}
              type="button"
              onClick={() => navigate(`/customer/restaurants/${restaurant.id}`)}
              className="group overflow-hidden rounded-[24px] border border-stone-900/10 bg-[#fffcf6]/70 text-left transition hover:-translate-y-1 hover:border-stone-900/20 hover:shadow-[0_28px_60px_-40px_rgba(28,25,23,0.6)]"
            >
              <ProductArt
                cuisine={restaurant.cuisine}
                name={restaurant.name}
                className="h-[150px]"
              />
              <div className="p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <h3 className="truncate font-serif text-[20px] italic leading-tight">
                      {restaurant.name}
                    </h3>
                    <p className="mt-1 truncate text-[10px] uppercase tracking-[0.12em] text-stone-500">
                      {restaurant.cuisine.map((entry) => entry.replaceAll("_", " ")).join(" · ")}
                    </p>
                  </div>
                  <span className="flex shrink-0 items-center gap-1 rounded-full bg-[#1f5b46] px-2 py-1 text-[10px] font-bold text-white">
                    ★ {Number(restaurant.rating).toFixed(1)}
                  </span>
                </div>
                <p className="mt-2 line-clamp-2 text-[11px] leading-snug text-stone-500">
                  {restaurant.description}
                </p>
                <div className="mt-3 flex items-center gap-3 border-t border-stone-900/8 pt-3 text-[10px] font-semibold uppercase tracking-[0.1em] text-stone-500">
                  <span>{formatMinutes(restaurant.avg_prep_min)}</span>
                  <span>{formatCurrency(restaurant.delivery_fee)} delivery</span>
                  {restaurant.distance_km !== null ? (
                    <span className="ml-auto">
                      {restaurant.distance_km.toFixed(1)} km
                    </span>
                  ) : null}
                </div>
              </div>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
