import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  notificationSocketUrl,
  getNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type AuthUser,
  type InboxNotification,
  type OrderStatus,
} from "../lib/api";
import { timeAgo } from "../lib/format";
import { navigate, signOut } from "../lib/session";

export type NavItem = {
  id: string;
  label: string;
  badge?: number;
};

export function MarketShell({
  user,
  roleLabel,
  nav,
  active,
  onNavigate,
  onCart,
  cartCount = 0,
  homePath,
  children,
}: {
  user: AuthUser;
  roleLabel: string;
  nav: NavItem[];
  active: string;
  onNavigate: (id: string) => void;
  onCart?: () => void;
  cartCount?: number;
  homePath: string;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-[#f3eee4] text-stone-900 antialiased">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_8%_0%,rgba(217,79,43,0.13),transparent_36%),radial-gradient(circle_at_92%_12%,rgba(31,91,70,0.1),transparent_34%)]" />
      <header className="sticky top-0 z-30 border-b border-stone-900/10 bg-[#f7f2e8]/90 backdrop-blur-xl">
        <div className="mx-auto flex h-[72px] max-w-[1400px] items-center gap-4 px-4 sm:px-6">
          <button
            type="button"
            onClick={() => navigate(homePath)}
            className="flex shrink-0 items-center gap-2.5"
          >
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#d94f2b] text-[11px] font-black tracking-tight text-[#fff8ee] shadow-[0_8px_24px_-12px_rgba(217,79,43,0.9)]">
              FF
            </span>
            <span className="text-left">
              <span className="block font-serif text-[19px] italic leading-none">
                FoodFlow
              </span>
              <span className="mt-1 block text-[9px] uppercase tracking-[0.24em] text-stone-500">
                {roleLabel}
              </span>
            </span>
          </button>

          <nav className="ml-2 hidden items-center gap-1 md:flex">
            {nav.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => onNavigate(item.id)}
                className={`relative rounded-full px-3.5 py-2 text-[13px] font-medium transition ${
                  active === item.id
                    ? "bg-stone-900 text-[#f8f3e9]"
                    : "text-stone-600 hover:bg-stone-900/[0.06] hover:text-stone-900"
                }`}
              >
                {item.label}
                {item.badge ? (
                  <span className="ml-1.5 inline-flex min-w-4 items-center justify-center rounded-full bg-[#d94f2b] px-1 text-[9px] font-bold text-white">
                    {item.badge}
                  </span>
                ) : null}
              </button>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            {onCart ? (
              <button
                type="button"
                onClick={onCart}
                className="relative flex h-10 items-center gap-2 rounded-full border border-stone-900/10 bg-white/60 px-3.5 text-[13px] font-semibold text-stone-800 transition hover:bg-white"
              >
                <span className="text-base leading-none">🛒</span>
                <span className="hidden sm:inline">Cart</span>
                {cartCount > 0 ? (
                  <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-[#d94f2b] px-1 text-[10px] font-bold text-white">
                    {cartCount}
                  </span>
                ) : null}
              </button>
            ) : null}
            <NotificationBell user={user} />
            <div className="hidden items-center gap-2 border-l border-stone-900/10 pl-2 sm:flex">
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-[#1f5b46] text-[11px] font-bold text-[#eef6ec]">
                {initials(user.name)}
              </div>
              <div className="max-w-[110px]">
                <p className="truncate text-[12px] font-semibold leading-tight">
                  {user.name}
                </p>
                <p className="truncate text-[10px] text-stone-500">{user.email}</p>
              </div>
            </div>
            <button
              type="button"
              onClick={signOut}
              className="rounded-full border border-stone-900/10 px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-stone-500 transition hover:border-stone-900/25 hover:text-stone-900"
            >
              Exit
            </button>
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto border-t border-stone-900/5 px-4 py-2 md:hidden">
          {nav.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => onNavigate(item.id)}
              className={`shrink-0 rounded-full px-3 py-1.5 text-[12px] font-medium ${
                active === item.id
                  ? "bg-stone-900 text-[#f8f3e9]"
                  : "text-stone-600"
              }`}
            >
              {item.label}
              {item.badge ? ` (${item.badge})` : ""}
            </button>
          ))}
        </nav>
      </header>
      <main className="relative mx-auto w-full max-w-[1400px] px-4 pb-24 pt-6 sm:px-6">
        {children}
      </main>
    </div>
  );
}

export function NotificationBell({ user }: { user: AuthUser }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<InboxNotification[]>([]);
  const wrap = useRef<HTMLDivElement | null>(null);
  const unread = items.filter((item) => !item.is_read).length;

  const load = () => {
    void getNotifications(25)
      .then(setItems)
      .catch(() => undefined);
  };

  useEffect(() => {
    load();
    const socket = new WebSocket(notificationSocketUrl());
    socket.onmessage = () => load();
    return () => socket.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user.id]);

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, []);

  return (
    <div ref={wrap} className="relative">
      <button
        type="button"
        onClick={() => {
          setOpen((value) => !value);
          if (!open) load();
        }}
        className="relative flex h-10 w-10 items-center justify-center rounded-full border border-stone-900/10 bg-white/60 text-[15px] transition hover:bg-white"
        aria-label="Notifications"
      >
        🔔
        {unread > 0 ? (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-[#d94f2b] px-0.5 text-[9px] font-bold text-white">
            {unread}
          </span>
        ) : null}
      </button>
      {open ? (
        <div className="absolute right-0 z-50 mt-2 w-[340px] overflow-hidden rounded-2xl border border-stone-900/10 bg-[#fffcf6] shadow-[0_30px_80px_-30px_rgba(28,25,23,0.5)]">
          <div className="flex items-center justify-between border-b border-stone-900/10 px-4 py-3">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-stone-500">
              Activity
            </p>
            <button
              type="button"
              onClick={() => {
                void markAllNotificationsRead().then(load);
              }}
              className="text-[11px] font-semibold text-[#d94f2b]"
            >
              Mark all read
            </button>
          </div>
          <div className="max-h-[360px] overflow-y-auto">
            {items.length === 0 ? (
              <p className="px-4 py-8 text-center text-sm text-stone-500">
                Quiet for now.
              </p>
            ) : (
              items.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => {
                    if (!item.is_read) void markNotificationRead(item.id).then(load);
                    if (item.order_id) {
                      const role = user.role;
                      if (role === "rider") navigate("/rider");
                      else if (role === "restaurant") navigate("/restaurant");
                      else navigate(`/customer/orders/${item.order_id}`);
                    }
                    setOpen(false);
                  }}
                  className={`flex w-full gap-3 border-b border-stone-900/5 px-4 py-3 text-left transition hover:bg-stone-900/[0.03] ${
                    item.is_read ? "opacity-60" : ""
                  }`}
                >
                  <span
                    className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${
                      item.is_read ? "bg-stone-300" : "bg-[#d94f2b]"
                    }`}
                  />
                  <span className="min-w-0">
                    <span className="block text-[13px] font-semibold">
                      {item.title}
                    </span>
                    <span className="mt-0.5 block text-[12px] leading-snug text-stone-600">
                      {item.body}
                    </span>
                    <span className="mt-1 block text-[10px] uppercase tracking-[0.12em] text-stone-400">
                      {timeAgo(item.created_at)}
                    </span>
                  </span>
                </button>
              ))
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function initials(name: string): string {
  return name
    .split(" ")
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

const cuisineThemes: Record<string, { bg: string; ink: string; glyph: string }> = {
  biryani: {
    bg: "bg-[linear-gradient(135deg,#f4b942_0%,#d94f2b_52%,#6d1f1a_100%)]",
    ink: "text-[#fff5e5]",
    glyph: "B",
  },
  north_indian: {
    bg: "bg-[linear-gradient(135deg,#ffcf70_0%,#d94f2b_55%,#7a2c1b_100%)]",
    ink: "text-[#fff5e5]",
    glyph: "N",
  },
  south_indian: {
    bg: "bg-[linear-gradient(135deg,#d7e8b2_0%,#3f7b56_52%,#173c2b_100%)]",
    ink: "text-[#f4f8e8]",
    glyph: "D",
  },
  chinese: {
    bg: "bg-[linear-gradient(135deg,#f0c05a_0%,#9e2a20_48%,#251b19_100%)]",
    ink: "text-[#fff3dc]",
    glyph: "W",
  },
  italian: {
    bg: "bg-[linear-gradient(135deg,#f3d9b1_0%,#c8553d_50%,#4f1f18_100%)]",
    ink: "text-[#fff8ea]",
    glyph: "P",
  },
  fast_food: {
    bg: "bg-[linear-gradient(135deg,#f7d86e_0%,#b25c22_55%,#2c1c14_100%)]",
    ink: "text-[#fff4dc]",
    glyph: "F",
  },
  desserts: {
    bg: "bg-[linear-gradient(135deg,#f7d8d1_0%,#cf7e95_50%,#5d2b43_100%)]",
    ink: "text-[#fff2ee]",
    glyph: "S",
  },
  cafe: {
    bg: "bg-[linear-gradient(135deg,#e8d7c0_0%,#8f6b4c_52%,#3b2a20_100%)]",
    ink: "text-[#fff4e4]",
    glyph: "C",
  },
};

export function ProductArt({
  cuisine,
  name,
  className = "",
  label = true,
}: {
  cuisine: string[];
  name: string;
  className?: string;
  label?: boolean;
}) {
  const key =
    cuisine.find((entry) => cuisineThemes[entry]) ??
    (cuisine.includes("desserts") ? "desserts" : "cafe");
  const theme = cuisineThemes[key] ?? cuisineThemes.cafe;
  return (
    <div
      className={`relative overflow-hidden ${theme.bg} ${theme.ink} ${className}`}
    >
      <div className="absolute -right-10 -top-12 h-44 w-44 rounded-full border border-white/20" />
      <div className="absolute -right-2 top-6 h-24 w-24 rounded-full bg-white/10" />
      <div className="absolute -bottom-10 left-8 h-32 w-32 rotate-12 rounded-[38%] border border-white/15 bg-white/5" />
      <div className="relative flex h-full flex-col justify-between p-5">
        <span className="text-[9px] uppercase tracking-[0.26em] opacity-70">
          {cuisine.slice(0, 2).join(" · ").replaceAll("_", " ")}
        </span>
        <div className="flex items-end justify-between gap-3">
          <span className="max-w-[75%] font-serif text-[24px] italic leading-[0.95]">
            {name}
          </span>
          <span className="font-serif text-[56px] leading-none opacity-25">
            {theme.glyph}
          </span>
        </div>
        {label ? null : (
          <span className="text-[9px] uppercase tracking-[0.22em] opacity-60">
            Simulated menu
          </span>
        )}
      </div>
    </div>
  );
}

export function StatusPill({ status }: { status: OrderStatus | string }) {
  const map: Record<string, string> = {
    PLACED: "bg-sky-600/10 text-sky-800 ring-sky-700/20",
    ACCEPTED: "bg-violet-600/10 text-violet-800 ring-violet-700/20",
    PREPARING: "bg-amber-500/15 text-amber-800 ring-amber-700/25",
    READY: "bg-emerald-600/10 text-emerald-800 ring-emerald-700/20",
    PICKED_UP: "bg-cyan-600/10 text-cyan-800 ring-cyan-700/20",
    DELIVERED: "bg-emerald-700 text-emerald-50 ring-emerald-800",
    CANCELLED: "bg-rose-600/10 text-rose-800 ring-rose-700/20",
    FAILED: "bg-rose-600/10 text-rose-800 ring-rose-700/20",
    offline: "bg-stone-500/10 text-stone-600 ring-stone-500/20",
    idle: "bg-emerald-600/10 text-emerald-800 ring-emerald-700/20",
    to_pickup: "bg-amber-500/15 text-amber-800 ring-amber-700/25",
    to_drop: "bg-sky-600/10 text-sky-800 ring-sky-700/20",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.12em] ring-1 ${
        map[status] ?? "bg-stone-500/10 text-stone-600 ring-stone-500/20"
      }`}
    >
      {status.replaceAll("_", " ")}
    </span>
  );
}

export function Btn({
  children,
  onClick,
  variant = "primary",
  size = "md",
  disabled,
  type = "button",
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "dark" | "outline" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
  disabled?: boolean;
  type?: "button" | "submit";
  className?: string;
}) {
  const variants = {
    primary:
      "bg-[#d94f2b] text-[#fff8ee] hover:bg-[#c44322] shadow-[0_12px_28px_-16px_rgba(217,79,43,0.9)]",
    dark: "bg-stone-900 text-[#f8f3e9] hover:bg-stone-800",
    outline:
      "border border-stone-900/15 bg-white/40 text-stone-800 hover:bg-white",
    ghost: "text-stone-600 hover:bg-stone-900/[0.06] hover:text-stone-900",
    danger: "bg-rose-700 text-white hover:bg-rose-800",
  };
  const sizes = {
    sm: "px-3 py-1.5 text-[12px]",
    md: "px-4 py-2.5 text-[13px]",
    lg: "px-5 py-3 text-[14px]",
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center justify-center gap-2 rounded-full font-semibold transition disabled:cursor-not-allowed disabled:opacity-40 ${variants[variant]} ${sizes[size]} ${className}`}
    >
      {children}
    </button>
  );
}

export function Field({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  required,
  className = "",
  min,
  max,
  step,
}: {
  label: string;
  value: string | number;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
  required?: boolean;
  className?: string;
  min?: number;
  max?: number;
  step?: number;
}) {
  return (
    <label className={`block ${className}`}>
      <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-[0.16em] text-stone-500">
        {label}
      </span>
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        required={required}
        min={min}
        max={max}
        step={step}
        className="w-full rounded-xl border border-stone-900/15 bg-white/70 px-3.5 py-2.5 text-sm text-stone-900 outline-none transition placeholder:text-stone-400 focus:border-[#d94f2b]/60 focus:ring-2 focus:ring-[#d94f2b]/15"
      />
    </label>
  );
}

export function Notice({
  tone = "error",
  children,
}: {
  tone?: "error" | "success" | "info";
  children: ReactNode;
}) {
  const styles = {
    error: "border-rose-700/20 bg-rose-600/[0.06] text-rose-800",
    success: "border-emerald-700/20 bg-emerald-600/[0.07] text-emerald-900",
    info: "border-stone-900/10 bg-white/50 text-stone-700",
  };
  return (
    <div className={`rounded-xl border px-3.5 py-2.5 text-[13px] ${styles[tone]}`}>
      {children}
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-10 text-sm text-stone-500">
      <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-stone-300 border-t-[#d94f2b]" />
      {label}
    </div>
  );
}

export function Empty({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-[24px] border border-dashed border-stone-900/15 px-6 py-14 text-center">
      <p className="font-serif text-[22px] italic text-stone-700">{title}</p>
      {hint ? <p className="mt-2 max-w-md text-sm text-stone-500">{hint}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function StatCard({
  label,
  value,
  hint,
  accent = "stone",
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  accent?: "stone" | "orange" | "green" | "gold";
}) {
  const dots = {
    stone: "bg-stone-400",
    orange: "bg-[#d94f2b]",
    green: "bg-[#1f5b46]",
    gold: "bg-[#c08a1c]",
  };
  return (
    <div className="rounded-[22px] border border-stone-900/10 bg-[#fffcf6]/80 p-4">
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-stone-500">
          {label}
        </p>
        <span className={`h-1.5 w-1.5 rounded-full ${dots[accent]}`} />
      </div>
      <p className="mt-2.5 font-serif text-[28px] leading-none text-stone-900">
        {value}
      </p>
      {hint ? <p className="mt-1.5 text-[11px] text-stone-500">{hint}</p> : null}
    </div>
  );
}

export function SimBadge() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-700/20 bg-amber-400/10 px-2.5 py-1 text-[9px] font-bold uppercase tracking-[0.14em] text-amber-800">
      <span className="h-1 w-1 rounded-full bg-amber-600" />
      Simulated data
    </span>
  );
}

export function Modal({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-stone-950/30 p-0 backdrop-blur-sm sm:items-center sm:p-6">
      <div
        className={`max-h-[92vh] w-full overflow-y-auto rounded-t-[28px] border border-stone-900/10 bg-[#fffcf6] p-5 shadow-[0_40px_120px_-30px_rgba(28,25,23,0.7)] sm:rounded-[28px] ${
          wide ? "sm:max-w-3xl" : "sm:max-w-lg"
        }`}
      >
        <div className="mb-4 flex items-center justify-between gap-4">
          <h3 className="font-serif text-[24px] italic leading-none">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-full border border-stone-900/10 text-stone-500 transition hover:bg-stone-900/5 hover:text-stone-900"
            aria-label="Close"
          >
            ×
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
