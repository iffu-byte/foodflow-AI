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

// Three places, like the food apps people already use: find food, pay for it,
// and everything about you (orders, nutrition, addresses) in one account page.
const nav: NavItem[] = [
  { id: "discover", label: "Home" },
  { id: "cart", label: "Cart" },
  { id: "account", label: "Account" },
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

  const active =
    route === "/customer/cart" || route === "/customer/checkout"
      ? "cart"
      : route.startsWith("/customer/orders") || route === "/customer/profile"
        ? "account"
        : "discover";

  const onNavigate = (id: string) => {
    if (id === "cart") navigate("/customer/cart");
    else if (id === "account") navigate("/customer/profile");
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
  } else if (route === "/customer/cart" || route === "/customer/checkout") {
    // One page: what you're buying, then where it goes and how you pay.
    view = (
      <div className="space-y-8">
        <CartView cart={cart} onCartUpdated={setCart} embedded />
        {cart && cart.items.length > 0 ? (
          <CheckoutView
            cart={cart}
            embedded
            onOrderPlaced={() => {
              void refreshCart();
            }}
          />
        ) : null}
      </div>
    );
  } else if (route === "/customer/orders" || route === "/customer/profile") {
    view = (
      <div className="space-y-8">
        <OrdersView onCartUpdated={setCart} />
        <ProfileView user={user} />
      </div>
    );
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
