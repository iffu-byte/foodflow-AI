import { useEffect } from "react";

import CustomerApp from "./apps/customer/CustomerApp";
import Login, { roleHome } from "./apps/Login";
import OpsConsole from "./apps/OpsConsole";
import RestaurantApp from "./apps/RestaurantApp";
import RiderApp from "./apps/RiderApp";
import { Btn } from "./components/market";
import { useHashRoute, useSession } from "./lib/session";

export default function App() {
  const user = useSession();
  const route = useHashRoute();

  useEffect(() => {
    if (!user) return;
    if (route === "/" || route === "/login") {
      window.location.hash = roleHome(user.role);
    }
  }, [route, user]);

  if (!user) {
    return <Login returnTo={route === "/" || route === "/login" ? undefined : route} />;
  }

  if (!route || route === "/" || route === "/login") {
    return null;
  }

  if (route.startsWith("/ops")) {
    return user.role === "admin" ? (
      <OpsConsole user={user} />
    ) : (
      <Denied role={user.role} />
    );
  }

  if (route.startsWith("/customer")) {
    return user.role === "customer" ? (
      <CustomerApp user={user} route={route} />
    ) : (
      <Denied role={user.role} />
    );
  }

  if (route.startsWith("/rider")) {
    return user.role === "rider" ? (
      <RiderApp user={user} route={route} />
    ) : (
      <Denied role={user.role} />
    );
  }

  if (route.startsWith("/restaurant")) {
    return user.role === "restaurant" ? (
      <RestaurantApp user={user} route={route} />
    ) : (
      <Denied role={user.role} />
    );
  }

  return <Denied role={user.role} />;
}

function Denied({ role }: { role: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[#f3eee4] px-5 text-stone-900">
      <div className="max-w-md rounded-[28px] border border-stone-900/10 bg-[#fffcf6] p-7 text-center shadow-[0_40px_100px_-60px_rgba(28,25,23,0.6)]">
        <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-stone-500">
          Role boundary
        </p>
        <h1 className="mt-2 font-serif text-[32px] italic leading-tight">
          This side of FoodFlow is not yours.
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-stone-500">
          You are signed in as <strong>{role}</strong>. Ask an admin if you expected access
          here, or return to your own workspace.
        </p>
        <Btn
          className="mt-5"
          onClick={() => {
            window.location.hash = roleHome(role as "customer" | "rider" | "restaurant" | "admin");
          }}
        >
          Return to my workspace
        </Btn>
      </div>
    </div>
  );
}
