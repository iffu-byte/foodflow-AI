import { useEffect, useMemo, useState } from "react";

import {
  addCartItem,
  ApiError,
  getCart,
  getMarketMenu,
  getMarketRestaurant,
  getMenuRecommendations,
  removeCartItem,
  updateCartItem,
  type AuthUser,
  type BrowseMenuItem,
  type BrowseRestaurant,
  type Cart,
  type MenuRecommendation,
} from "../../lib/api";
import { formatCurrency, formatMinutes } from "../../lib/format";
import { navigate } from "../../lib/session";
import {
  Btn,
  Empty,
  Modal,
  Notice,
  ProductArt,
  SimBadge,
  Spinner,
} from "../../components/market";
import {
  NutritionChips,
  PortionLine,
  PortionPhotoModal,
  TrustPanel,
} from "../../components/trust";

type DishFilter = "veg" | "protein" | "light" | "verified" | "rescue";

const dishFilters: Array<{ id: DishFilter; label: string }> = [
  { id: "veg", label: "Veg" },
  { id: "protein", label: "High protein 20 g+" },
  { id: "light", label: "Under 500 kcal" },
  { id: "verified", label: "Portion verified" },
  { id: "rescue", label: "Rescue deals" },
];

function matchesFilters(item: BrowseMenuItem, filters: Set<DishFilter>): boolean {
  if (filters.has("veg") && !item.veg) return false;
  if (filters.has("protein") && (item.nutrition?.protein_g ?? 0) < 20) return false;
  if (filters.has("light") && (item.nutrition?.kcal ?? 9999) >= 500) return false;
  if (
    filters.has("verified") &&
    !["photo_reference", "container", "scale", "pieces"].includes(item.portion_method ?? "")
  )
    return false;
  if (filters.has("rescue") && !item.rescue) return false;
  return true;
}

export function RestaurantView({
  restaurantId,
  user,
  cart,
  onCartUpdated,
}: {
  restaurantId: string;
  user: AuthUser;
  cart: Cart | null;
  onCartUpdated: (cart: Cart) => void;
}) {
  const [restaurant, setRestaurant] = useState<BrowseRestaurant | null>(null);
  const [menu, setMenu] = useState<BrowseMenuItem[]>([]);
  const [recommended, setRecommended] = useState<MenuRecommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyItem, setBusyItem] = useState<string | null>(null);
  const [added, setAdded] = useState<string | null>(null);
  const [conflict, setConflict] = useState<BrowseMenuItem | null>(null);
  const [resetting, setResetting] = useState(false);
  const [filters, setFilters] = useState<Set<DishFilter>>(new Set());
  const [photoItem, setPhotoItem] = useState<BrowseMenuItem | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([
      getMarketRestaurant(restaurantId),
      getMarketMenu(restaurantId),
      getMenuRecommendations(user.id, restaurantId).catch(() => []),
    ])
      .then(([row, items, picks]) => {
        if (cancelled) return;
        setRestaurant(row);
        setMenu(items);
        setRecommended(picks);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Could not load this kitchen.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [restaurantId, user.id]);

  useEffect(() => {
    if (!added) return;
    const timer = window.setTimeout(() => setAdded(null), 2400);
    return () => window.clearTimeout(timer);
  }, [added]);

  const cartLines = useMemo(() => {
    const map = new Map<string, { id: string; qty: number }>();
    if (cart?.restaurant?.id === restaurantId) {
      for (const line of cart.items) {
        map.set(line.menu_item_id, { id: line.id, qty: line.qty });
      }
    }
    return map;
  }, [cart, restaurantId]);

  const groups = useMemo(() => {
    const map = new Map<string, BrowseMenuItem[]>();
    for (const item of menu.filter((entry) => matchesFilters(entry, filters))) {
      const group = map.get(item.category) ?? [];
      group.push(item);
      map.set(item.category, group);
    }
    return Array.from(map.entries());
  }, [menu, filters]);

  const add = async (item: BrowseMenuItem) => {
    setBusyItem(item.id);
    setError(null);
    try {
      const next = await addCartItem(item.id, 1, item.rescue?.id);
      onCartUpdated(next);
      setAdded(item.rescue ? `${item.name} (rescue price)` : item.name);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setConflict(item);
      } else {
        setError(err instanceof ApiError ? err.message : "Could not add this item.");
      }
    } finally {
      setBusyItem(null);
    }
  };

  const setQty = async (lineId: string, qty: number) => {
    setBusyItem(lineId);
    try {
      const next = qty <= 0 ? await removeCartItem(lineId) : await updateCartItem(lineId, qty);
      onCartUpdated(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update your cart.");
    } finally {
      setBusyItem(null);
    }
  };

  const startFresh = async () => {
    if (!conflict) return;
    setResetting(true);
    try {
      const current = await getCart();
      for (const line of current.items) {
        await removeCartItem(line.id);
      }
      const next = await addCartItem(conflict.id, 1, conflict.rescue?.id);
      onCartUpdated(next);
      setAdded(conflict.name);
      setConflict(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not rebuild the cart.");
    } finally {
      setResetting(false);
    }
  };

  if (loading) {
    return (
      <div className="py-16">
        <Spinner label="Opening the kitchen" />
      </div>
    );
  }

  if (!restaurant) {
    return (
      <Empty
        title="This kitchen is not available."
        hint={error ?? "It may have closed for the evening."}
        action={<Btn onClick={() => navigate("/customer")}>Back to discovery</Btn>}
      />
    );
  }

  const otherRestaurant =
    cart?.restaurant && cart.restaurant.id !== restaurant.id ? cart.restaurant.name : null;

  return (
    <div className="space-y-5">
      <button
        type="button"
        onClick={() => navigate("/customer")}
        className="text-[11px] font-semibold uppercase tracking-[0.16em] text-stone-500 hover:text-stone-900"
      >
        ← All kitchens
      </button>

      <section className="overflow-hidden rounded-[30px] border border-stone-900/10 bg-[#171512] text-[#f8f3e9]">
        <div className="grid lg:grid-cols-[1.2fr_0.8fr]">
          <div className="relative z-10 p-6 sm:p-8">
            <div className="flex flex-wrap items-center gap-2">
              <SimBadge />
              <span className="rounded-full border border-white/15 px-2.5 py-1 text-[9px] font-bold uppercase tracking-[0.14em] text-stone-400">
                {restaurant.cuisine.map((entry) => entry.replaceAll("_", " ")).join(" · ")}
              </span>
            </div>
            <h1 className="mt-4 font-serif text-[42px] italic leading-[0.95] sm:text-[54px]">
              {restaurant.name}
            </h1>
            <p className="mt-3 max-w-xl text-[13px] leading-relaxed text-stone-400">
              {restaurant.description}
            </p>
            <div className="mt-6 flex flex-wrap gap-x-6 gap-y-3 border-t border-white/10 pt-5">
              {[
                ["Rating", `★ ${Number(restaurant.rating).toFixed(1)}`, `${restaurant.rating_count} reviews`],
                ["Kitchen time", formatMinutes(restaurant.avg_prep_min), "fresh, not fast"],
                ["Delivery", formatCurrency(restaurant.delivery_fee), `free over ₹499`],
                ["Minimum", formatCurrency(restaurant.min_order_value), "order value"],
              ].map(([label, value, hint]) => (
                <div key={label}>
                  <p className="text-[9px] uppercase tracking-[0.18em] text-stone-500">
                    {label}
                  </p>
                  <p className="mt-1 font-serif text-[20px] leading-none">{value}</p>
                  <p className="mt-1 text-[9px] text-stone-600">{hint}</p>
                </div>
              ))}
            </div>
          </div>
          <ProductArt
            cuisine={restaurant.cuisine}
            name={restaurant.name}
            className="min-h-[240px] lg:min-h-full"
          />
        </div>
      </section>

      {otherRestaurant ? (
        <Notice tone="info">
          Your cart currently has dishes from <strong>{otherRestaurant}</strong>. Adding
          something here will ask before starting a fresh cart.
        </Notice>
      ) : null}
      {error ? <Notice>{error}</Notice> : null}

      <TrustPanel restaurantId={restaurant.id} />

      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-stone-500">
          Filter dishes
        </span>
        {dishFilters.map((filter) => {
          const on = filters.has(filter.id);
          return (
            <button
              key={filter.id}
              type="button"
              onClick={() =>
                setFilters((current) => {
                  const next = new Set(current);
                  if (next.has(filter.id)) next.delete(filter.id);
                  else next.add(filter.id);
                  return next;
                })
              }
              className={`rounded-full border px-3 py-1.5 text-[11px] font-semibold transition ${
                on
                  ? "border-stone-900 bg-stone-900 text-[#f8f3e9]"
                  : "border-stone-900/15 bg-white/40 text-stone-600 hover:bg-white"
              }`}
            >
              {filter.label}
            </button>
          );
        })}
        <span className="ml-auto text-[10px] text-stone-400">
          Calories are estimates for the stated portion
        </span>
      </div>

      {recommended.length > 0 ? (
        <section className="rounded-[26px] border border-[#b47816]/25 bg-[#f4b942]/10 p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-[#8a5b0a]">
                Simulated affinity · from your history
              </p>
              <h2 className="mt-1 font-serif text-[23px] italic">You might like these</h2>
            </div>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {recommended.slice(0, 3).map((pick) => (
              <button
                key={pick.item.id}
                type="button"
                onClick={() => {
                  const item = menu.find((entry) => entry.id === pick.item.id);
                  if (item) void add(item);
                }}
                className="rounded-2xl border border-stone-900/10 bg-[#fffcf6]/80 p-3 text-left transition hover:bg-white"
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="text-[13px] font-semibold">{pick.item.name}</p>
                  <span className="text-[12px] font-semibold text-[#8a5b0a]">
                    {formatCurrency(pick.item.price)}
                  </span>
                </div>
                <p className="mt-1 line-clamp-2 text-[10px] leading-snug text-stone-500">
                  {pick.reasons[0]}
                </p>
              </button>
            ))}
          </div>
        </section>
      ) : null}

      <section className="grid gap-6 lg:grid-cols-[1fr_280px]">
        <div className="space-y-6">
          {groups.length === 0 ? (
            <Empty
              title="No dishes match these filters."
              hint="Clear a filter to see the full menu."
              action={
                <Btn variant="outline" onClick={() => setFilters(new Set())}>
                  Clear filters
                </Btn>
              }
            />
          ) : null}
          {groups.map(([category, items]) => (
            <div key={category}>
              <div className="mb-3 flex items-end justify-between gap-3">
                <h2 className="font-serif text-[27px] italic leading-none">{category}</h2>
                <span className="text-[9px] uppercase tracking-[0.16em] text-stone-400">
                  {items.length} dishes
                </span>
              </div>
              <div className="overflow-hidden rounded-[24px] border border-stone-900/10 bg-[#fffcf6]/70">
                {items.map((item, index) => {
                  const line = cartLines.get(item.id);
                  return (
                    <div
                      key={item.id}
                      className={`flex gap-3 p-4 ${
                        index > 0 ? "border-t border-stone-900/8" : ""
                      }`}
                    >
                      <div className="pt-1">
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
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-[14px] font-semibold leading-tight">
                              {item.name}
                            </p>
                            {item.rescue ? (
                              <p className="mt-1 flex flex-wrap items-baseline gap-1.5 text-[12px] font-semibold">
                                <span className="text-[#1f5b46]">
                                  {formatCurrency(item.rescue.current_price)}
                                </span>
                                <span className="text-[11px] text-stone-400 line-through">
                                  {formatCurrency(item.price)}
                                </span>
                                <span className="rounded-full bg-[#1f5b46] px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-[0.08em] text-white">
                                  Rescue · {item.rescue.qty_left} left
                                </span>
                              </p>
                            ) : (
                              <p className="mt-1 text-[12px] font-semibold text-stone-700">
                                {formatCurrency(item.price)}
                              </p>
                            )}
                            <PortionLine item={item} />
                          </div>
                          {line ? (
                            <div className="flex items-center rounded-full border border-[#1f5b46]/30 bg-[#1f5b46]/5">
                              <button
                                type="button"
                                disabled={busyItem === line.id}
                                onClick={() => void setQty(line.id, line.qty - 1)}
                                className="px-2.5 py-1.5 text-[14px] text-[#1f5b46]"
                              >
                                −
                              </button>
                              <span className="min-w-5 text-center text-[12px] font-bold text-[#1f5b46]">
                                {line.qty}
                              </span>
                              <button
                                type="button"
                                disabled={busyItem === line.id}
                                onClick={() => void setQty(line.id, line.qty + 1)}
                                className="px-2.5 py-1.5 text-[14px] text-[#1f5b46]"
                              >
                                +
                              </button>
                            </div>
                          ) : (
                            <Btn
                              size="sm"
                              variant="outline"
                              disabled={!item.available || busyItem === item.id}
                              onClick={() => void add(item)}
                            >
                              {item.available
                                ? busyItem === item.id
                                  ? "…"
                                  : "Add +"
                                : "Sold out"}
                            </Btn>
                          )}
                        </div>
                        <p className="mt-1.5 max-w-xl text-[11px] leading-snug text-stone-500">
                          {item.description}
                        </p>
                        <NutritionChips nutrition={item.nutrition} />
                        {item.portion_photo_url ? (
                          <button
                            type="button"
                            onClick={() => setPhotoItem(item)}
                            className="mt-1.5 text-[10px] font-semibold text-[#1f5b46] underline"
                          >
                            See the real portion photo
                          </button>
                        ) : null}
                        <div className="mt-2 flex flex-wrap gap-1">
                          {item.tags.slice(0, 3).map((tag) => (
                            <span
                              key={tag}
                              className="rounded-full bg-stone-900/[0.05] px-2 py-0.5 text-[9px] font-medium uppercase tracking-[0.08em] text-stone-500"
                            >
                              {tag}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        <aside className="hidden lg:block">
          <div className="sticky top-24 rounded-[24px] border border-stone-900/10 bg-[#fffcf6]/70 p-4">
            <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-stone-500">
              Good to know
            </p>
            <h3 className="mt-1 font-serif text-[22px] italic">A little kitchen note</h3>
            <p className="mt-2 text-[11px] leading-relaxed text-stone-500">
              Every prep time and recommendation here is generated from simulated city
              data. The ETA promise updates as the kitchen and rider move.
            </p>
            <div className="mt-4 space-y-2 border-t border-stone-900/10 pt-3 text-[11px] text-stone-600">
              <p className="flex justify-between gap-2">
                <span>Min order</span>
                <span className="font-semibold">
                  {formatCurrency(restaurant.min_order_value)}
                </span>
              </p>
              <p className="flex justify-between gap-2">
                <span>Delivery fee</span>
                <span className="font-semibold">
                  {formatCurrency(restaurant.delivery_fee)}
                </span>
              </p>
              <p className="flex justify-between gap-2">
                <span>Free delivery</span>
                <span className="font-semibold">₹499+</span>
              </p>
            </div>
            {cart?.restaurant?.id === restaurant.id && cart.item_count > 0 ? (
              <Btn
                className="mt-4 w-full"
                onClick={() => navigate("/customer/cart")}
              >
                View cart · {formatCurrency(cart.total)}
              </Btn>
            ) : null}
          </div>
        </aside>
      </section>

      {cart?.restaurant?.id === restaurant.id && cart.item_count > 0 ? (
        <div className="fixed inset-x-3 bottom-3 z-40 lg:hidden">
          <button
            type="button"
            onClick={() => navigate("/customer/cart")}
            className="flex w-full items-center justify-between rounded-2xl bg-[#1f5b46] px-4 py-3.5 text-[#f3f8f1] shadow-[0_20px_50px_-20px_rgba(31,91,70,0.8)]"
          >
            <span className="text-[12px] font-semibold">
              {cart.item_count} item{cart.item_count === 1 ? "" : "s"} ·{" "}
              {formatCurrency(cart.total)}
            </span>
            <span className="text-[10px] font-bold uppercase tracking-[0.14em]">
              View cart →
            </span>
          </button>
        </div>
      ) : null}

      {added ? (
        <div className="fixed bottom-5 right-5 z-50 rounded-2xl bg-stone-900 px-4 py-3 text-[12px] font-medium text-[#f8f3e9] shadow-2xl">
          {added} added to cart
        </div>
      ) : null}

      {photoItem ? (
        <PortionPhotoModal item={photoItem} onClose={() => setPhotoItem(null)} />
      ) : null}

      {conflict ? (
        <Modal title="Start a fresh cart?" onClose={() => setConflict(null)}>
          <p className="text-sm leading-relaxed text-stone-600">
            Your cart already holds dishes from{" "}
            <strong>{cart?.restaurant?.name ?? "another restaurant"}</strong>. A cart can
            only contain one kitchen. Replace it with <strong>{conflict.name}</strong> from{" "}
            {restaurant.name}?
          </p>
          <div className="mt-5 flex gap-2">
            <Btn variant="outline" className="flex-1" onClick={() => setConflict(null)}>
              Keep old cart
            </Btn>
            <Btn
              className="flex-1"
              disabled={resetting}
              onClick={() => void startFresh()}
            >
              {resetting ? "Rebuilding…" : "Start fresh"}
            </Btn>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
