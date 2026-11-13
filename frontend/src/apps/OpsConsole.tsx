import { useEffect, useState } from "react";

import { Badge, Dot, SimulatedBadge } from "../components/ui";
import { API_URL, type AuthUser } from "../lib/api";
import { signOut } from "../lib/session";
import Dispatch from "../tabs/Dispatch";
import LiveBoard from "../tabs/LiveBoard";
import Models from "../tabs/Models";
import Monitor from "../tabs/Monitor";
import Recommendations from "../tabs/Recommendations";

type TabId = "live" | "dispatch" | "monitor" | "models" | "recs";

type ApiState = "checking" | "online" | "offline";

const tabs: Array<{
  id: TabId;
  index: string;
  label: string;
  hint: string;
  title: string;
  description: string;
}> = [
  {
    id: "live",
    index: "01",
    label: "Live board",
    hint: "Orders and tracking",
    title: "The city, in motion.",
    description:
      "Watch every order transition, rider ping and ETA commitment as it lands on the stream.",
  },
  {
    id: "dispatch",
    index: "02",
    label: "Dispatch",
    hint: "Candidate ranking",
    title: "Put the right rider on it.",
    description:
      "Score idle riders against pickup distance, active load and vehicle capacity, then commit.",
  },
  {
    id: "monitor",
    index: "03",
    label: "Delay monitor",
    hint: "Risk and stalls",
    title: "Catch slippage early.",
    description:
      "Deadline pressure, kitchen stalls and quiet riders surfaced before the promise breaks.",
  },
  {
    id: "models",
    index: "04",
    label: "Learning loop",
    hint: "ETA model registry",
    title: "Promises that learn.",
    description:
      "Retrain on fresh simulator rows, compare validation error and promote only real gains.",
  },
  {
    id: "recs",
    index: "05",
    label: "Recommendations",
    hint: "Customer affinity",
    title: "Know the next order.",
    description:
      "Restaurant and dish picks shaped by budget, diet, distance, rating and cuisine history.",
  },
];

const apiStyles: Record<ApiState, string> = {
  checking: "bg-amber-400/10 text-amber-300 ring-amber-400/30",
  online: "bg-emerald-400/10 text-emerald-300 ring-emerald-400/30",
  offline: "bg-rose-400/10 text-rose-300 ring-rose-400/30",
};

const apiLabels: Record<ApiState, string> = {
  checking: "Connecting",
  online: "API online",
  offline: "API offline",
};

export default function OpsConsole({ user }: { user: AuthUser }) {
  const [tab, setTab] = useState<TabId>("live");
  const [apiState, setApiState] = useState<ApiState>("checking");
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    let cancelled = false;

    const check = async () => {
      try {
        const response = await fetch(`${API_URL}/healthz`);
        if (!cancelled) setApiState(response.ok ? "online" : "offline");
      } catch {
        if (!cancelled) setApiState("offline");
      }
    };

    void check();
    const timer = window.setInterval(check, 10_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const current = tabs.find((entry) => entry.id === tab) ?? tabs[0];

  return (
    <main className="min-h-screen bg-[#060a08] text-stone-200 antialiased">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_top_left,rgba(16,185,129,0.09),transparent_42%),radial-gradient(circle_at_85%_5%,rgba(56,189,248,0.06),transparent_38%)]" />
      <div className="relative mx-auto grid max-w-[1500px] gap-5 px-4 py-5 lg:grid-cols-[232px_minmax(0,1fr)] lg:px-6">
        <aside className="flex flex-col rounded-2xl border border-white/10 bg-[#0b1210]/80 p-5 lg:sticky lg:top-5 lg:h-[calc(100vh-2.5rem)]">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-300 text-sm font-bold tracking-tight text-emerald-950">
              FF
            </div>
            <div>
              <p className="font-serif text-lg italic leading-none text-stone-100">
                FoodFlow
              </p>
              <p className="mt-1 text-[10px] uppercase tracking-[0.22em] text-stone-500">
                Ops console
              </p>
            </div>
          </div>

          <nav className="mt-8 space-y-1">
            {tabs.map((entry) => {
              const active = entry.id === tab;
              return (
                <button
                  key={entry.id}
                  type="button"
                  onClick={() => setTab(entry.id)}
                  className={`group flex w-full items-start gap-3 rounded-xl border px-3 py-2.5 text-left transition ${
                    active
                      ? "border-emerald-400/25 bg-emerald-400/[0.07]"
                      : "border-transparent hover:bg-white/[0.03]"
                  }`}
                >
                  <span
                    className={`mt-0.5 font-mono text-[10px] ${
                      active ? "text-emerald-300" : "text-stone-600"
                    }`}
                  >
                    {entry.index}
                  </span>
                  <span className="min-w-0">
                    <span
                      className={`block text-sm ${
                        active ? "text-stone-100" : "text-stone-400"
                      }`}
                    >
                      {entry.label}
                    </span>
                    <span className="mt-0.5 block text-[11px] text-stone-600">
                      {entry.hint}
                    </span>
                  </span>
                </button>
              );
            })}
          </nav>

          <div className="mt-auto space-y-4 pt-8">
            <div>
              <p className="text-[10px] uppercase tracking-[0.18em] text-stone-600">
                Gateway
              </p>
              <div
                className={`mt-2 inline-flex items-center gap-2 rounded-full px-2.5 py-1 text-xs ring-1 ${apiStyles[apiState]}`}
              >
                <Dot
                  tone={
                    apiState === "online"
                      ? "mint"
                      : apiState === "offline"
                        ? "rose"
                        : "amber"
                  }
                />
                {apiLabels[apiState]}
              </div>
              <p className="mt-2 break-all font-mono text-[10px] text-stone-600">
                {API_URL}
              </p>
            </div>
            <div className="border-t border-white/5 pt-4">
              <p className="text-[10px] uppercase tracking-[0.18em] text-stone-600">
                Operator
              </p>
              <p className="mt-1 text-xs text-stone-300">{user.name}</p>
              <p className="text-[10px] text-stone-600">{user.email}</p>
              <button
                type="button"
                onClick={signOut}
                className="mt-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-stone-500 hover:text-rose-300"
              >
                Exit console
              </button>
            </div>
            <p className="border-t border-white/5 pt-4 text-[10px] leading-relaxed text-stone-600">
              ETA, assignment and recommendation outputs are generated from simulated city
              data.
            </p>
          </div>
        </aside>

        <section className="flex min-w-0 flex-col">
          <header className="flex flex-wrap items-start justify-between gap-4 pb-5">
            <div className="max-w-2xl">
              <p className="text-[10px] uppercase tracking-[0.24em] text-stone-500">
                FoodFlow operations
              </p>
              <h1 className="mt-2 font-serif text-3xl italic tracking-tight text-stone-50 sm:text-4xl">
                {current.title}
              </h1>
              <p className="mt-2 text-sm leading-relaxed text-stone-500">
                {current.description}
              </p>
            </div>
            <div className="flex flex-col items-end gap-2">
              <SimulatedBadge />
              <p className="font-mono text-sm text-stone-400">
                {now.toLocaleTimeString("en-GB", { timeZone: "UTC", hour12: false })}
                <span className="ml-1 text-[10px] uppercase tracking-[0.14em] text-stone-600">
                  UTC
                </span>
              </p>
              <Badge tone="neutral">{current.label}</Badge>
            </div>
          </header>

          <div className="flex-1">
            {tab === "live" ? <LiveBoard /> : null}
            {tab === "dispatch" ? <Dispatch /> : null}
            {tab === "monitor" ? <Monitor /> : null}
            {tab === "models" ? <Models /> : null}
            {tab === "recs" ? <Recommendations /> : null}
          </div>

          <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-white/5 pt-4 text-[10px] uppercase tracking-[0.16em] text-stone-600">
            <span>FoodFlow AI v0.1 · simulated environment</span>
            <span>Order events · ETA · dispatch · monitor · learning</span>
          </footer>
        </section>
      </div>
    </main>
  );
}
