import { useEffect, useState } from "react";

import { clearSession, getStoredUser, type AuthUser } from "./api";

export function useSession(): AuthUser | null {
  const [user, setUser] = useState<AuthUser | null>(() => getStoredUser());

  useEffect(() => {
    const sync = () => setUser(getStoredUser());
    window.addEventListener("foodflow.session", sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener("foodflow.session", sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  return user;
}

export function signOut(): void {
  clearSession();
  window.location.hash = "/login";
}

export function useHashRoute(): string {
  const [route, setRoute] = useState(() => window.location.hash.replace(/^#/, "") || "/");

  useEffect(() => {
    const sync = () => {
      setRoute(window.location.hash.replace(/^#/, "") || "/");
      window.scrollTo({ top: 0, behavior: "smooth" });
    };
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  return route;
}

export function navigate(path: string): void {
  window.location.hash = path;
}
