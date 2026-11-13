import { useEffect, useState } from "react";

import { getCart, type AuthUser, type Cart } from "../../lib/api";
import { navigate } from "../../lib/session";
import { MarketShell, type NavItem } from "../../components/market";
import { CartView } from "./CartView";
import { CheckoutView } from "./CheckoutView";
import { Home } from "./Home";
import { OrderDetailView } from "./OrderDetailView";
import { OrdersView } from "./OrdersView";
import { ProfileView } from "./ProfileView";
import { RestaurantView } from "./RestaurantView";

const nav: NavItem[] = [
  { id: "discover", label: "Discover" },
  { id: "orders", label: "Orders" },
  { id: "profile", label: "Profile" },
];

export default function CustomerApp({
  user,
  route,
}: {
  user: AuthUser;
  route: string;
}) {
  const [cart, setCart] = useState<Cart | null>(null);

  const refreshCart = async () => {
    try {
      const next = await getCart();
      setCart(next);
      return next;
    } catch {
      return null;
    }
  };

  useEffect(() => {
    void refreshCart();
  }, []);

  const active = route.startsWith("/customer/orders")
    ? "orders"
    : route === "/customer/profile"
      ? "profile"
      : "discover";

  const onNavigate = (id: string) => {
    if (id === "orders") navigate("/customer/orders");
    else if (id === "profile") navigate("/customer/profile");
    else navigate("/customer");
  };

  const restaurantMatch = route.match(/^\/customer\/restaurants\/([^/]+)$/);
  const orderMatch = route.match(/^\/customer\/orders\/([^/]+)$/);

  let view: React.ReactNode;
  if (restaurantMatch) {
    view = (
      <RestaurantView
        restaurantId={restaurantMatch[1]}
        user={user}
        cart={cart}
        onCartUpdated={setCart}
      />
    );
  } else if (orderMatch) {
    view = <OrderDetailView orderId={orderMatch[1]} onCartUpdated={setCart} />;
  } else if (route === "/customer/cart") {
    view = <CartView cart={cart} onCartUpdated={setCart} />;
  } else if (route === "/customer/checkout") {
    view = (
      <CheckoutView
        cart={cart}
        onOrderPlaced={() => {
          void refreshCart();
        }}
      />
    );
  } else if (route === "/customer/orders") {
    view = <OrdersView onCartUpdated={setCart} />;
  } else if (route === "/customer/profile") {
    view = <ProfileView user={user} />;
  } else {
    view = <Home user={user} onCartUpdated={setCart} />;
  }

  return (
    <MarketShell
      user={user}
      roleLabel="Customer · Hyderabad"
      nav={nav}
      active={active}
      onNavigate={onNavigate}
      onCart={() => navigate("/customer/cart")}
      cartCount={cart?.item_count ?? 0}
      homePath="/customer"
    >
      {view}
    </MarketShell>
  );
}
