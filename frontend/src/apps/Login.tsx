import { useState } from "react";

import {
  ApiError,
  login,
  registerCustomer,
  storeSession,
  type Role,
} from "../lib/api";
import { Btn, Field, Notice, SimBadge } from "../components/market";

const DEMO_ACCOUNTS: Array<{
  role: Role;
  label: string;
  email: string;
  blurb: string;
  accent: string;
}> = [
  {
    role: "customer",
    label: "Customer",
    email: "customer@foodflow.demo",
    blurb: "Asha Rao · order food and track it",
    accent: "bg-[#d94f2b]",
  },
  {
    role: "rider",
    label: "FoodFlow Captain",
    email: "rider@foodflow.demo",
    blurb: "Arjun · pick up and deliver orders",
    accent: "bg-[#1f5b46]",
  },
  {
    role: "restaurant",
    label: "Restaurant Owner",
    email: "restaurant@foodflow.demo",
    blurb: "Spice Route · orders, menu, kitchen",
    accent: "bg-[#b47816]",
  },
];

// The operations console stays available for judges and admins, but it is not
// one of the three everyday roles.
const OPS_ACCOUNT = {
  role: "admin" as Role,
  label: "Operations console",
  email: "admin@foodflow.demo",
  blurb: "AI cost meter, dispatch, models",
  accent: "bg-stone-900",
};

export function roleHome(role: Role): string {
  if (role === "rider") return "/rider";
  if (role === "restaurant") return "/restaurant";
  if (role === "admin") return "/ops";
  return "/customer";
}

export default function Login({ returnTo }: { returnTo?: string }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("customer@foodflow.demo");
  const [password, setPassword] = useState("demo1234");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result =
        mode === "login"
          ? await login(email, password)
          : await registerCustomer({ name, email, password, phone: phone || undefined });
      storeSession(result.access_token, result.user);
      const home = roleHome(result.user.role);
      const target =
        returnTo && (returnTo === home || returnTo.startsWith(`${home}/`))
          ? returnTo
          : home;
      window.location.hash = target;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  const useDemo = async (account: (typeof DEMO_ACCOUNTS)[number]) => {
    setMode("login");
    setEmail(account.email);
    setPassword("demo1234");
    setBusy(true);
    setError(null);
    try {
      const result = await login(account.email, "demo1234");
      storeSession(result.access_token, result.user);
      const home = roleHome(result.user.role);
      const target =
        returnTo && (returnTo === home || returnTo.startsWith(`${home}/`))
          ? returnTo
          : home;
      window.location.hash = target;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not sign in.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#f3eee4] text-stone-900 antialiased">
      <div className="grid min-h-screen lg:grid-cols-[1.08fr_0.92fr]">
        <section className="relative flex flex-col justify-between overflow-hidden bg-[#171512] px-6 py-8 text-[#f8f3e9] sm:px-10 lg:px-14">
          <div className="pointer-events-none absolute -right-32 top-1/4 h-[520px] w-[520px] rounded-full bg-[radial-gradient(circle,rgba(217,79,43,0.5),transparent_62%)]" />
          <div className="pointer-events-none absolute -left-24 bottom-0 h-80 w-80 rounded-full bg-[radial-gradient(circle,rgba(31,91,70,0.65),transparent_65%)]" />
          <div className="relative flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#d94f2b] text-[12px] font-black text-[#fff8ee]">
                FF
              </span>
              <div>
                <p className="font-serif text-[20px] italic leading-none">FoodFlow</p>
                <p className="mt-1 text-[9px] uppercase tracking-[0.28em] text-stone-500">
                  Hyderabad · simulated city
                </p>
              </div>
            </div>
            <SimBadge />
          </div>

          <div className="relative mt-16 max-w-xl">
            <p className="text-[10px] uppercase tracking-[0.26em] text-[#e8a27d]">
              One city. Three sides of dinner.
            </p>
            <h1 className="mt-5 font-serif text-[52px] italic leading-[0.94] tracking-[-0.02em] sm:text-[72px]">
              Dinner is
              <br />
              a feeling.
            </h1>
            <p className="mt-5 max-w-md text-[15px] leading-relaxed text-stone-400">
              Order food as a customer, run your kitchen as a restaurant owner, or deliver
              as a FoodFlow Captain. Same live orders, three simple apps.
            </p>
            <div className="mt-10 flex flex-wrap gap-x-8 gap-y-4 border-t border-white/10 pt-6">
              {[
                ["30", "restaurants"],
                ["113", "dishes"],
                ["20", "riders"],
                ["1", "live promise engine"],
              ].map(([value, label]) => (
                <div key={label}>
                  <p className="font-serif text-[28px] leading-none text-[#f4b942]">
                    {value}
                  </p>
                  <p className="mt-1 text-[9px] uppercase tracking-[0.2em] text-stone-500">
                    {label}
                  </p>
                </div>
              ))}
            </div>
          </div>

          <p className="relative mt-12 max-w-md text-[11px] leading-relaxed text-stone-500">
            Demo credentials are seeded with password <span className="text-stone-300">demo1234</span>.
            All ETAs, recommendations and rider movement are simulated.
          </p>
        </section>

        <section className="flex items-center justify-center bg-[#f3eee4] px-5 py-10 sm:px-10">
          <div className="w-full max-w-[470px]">
            <div className="flex items-end justify-between gap-4">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-stone-500">
                  {mode === "login" ? "Welcome back" : "New around here"}
                </p>
                <h2 className="mt-2 font-serif text-[36px] italic leading-none">
                  {mode === "login" ? "Pick up where you left off." : "Make your first order."}
                </h2>
              </div>
            </div>

            <form onSubmit={submit} className="mt-7 space-y-3.5">
              {mode === "register" ? (
                <>
                  <Field
                    label="Full name"
                    value={name}
                    onChange={setName}
                    placeholder="Asha Rao"
                    required
                  />
                  <Field
                    label="Phone"
                    value={phone}
                    onChange={setPhone}
                    placeholder="+91 90000 00000"
                  />
                </>
              ) : null}
              <Field
                label="Email"
                value={email}
                onChange={setEmail}
                type="email"
                placeholder="you@foodflow.demo"
                required
              />
              <Field
                label="Password"
                value={password}
                onChange={setPassword}
                type="password"
                placeholder="demo1234"
                required
              />
              {error ? <Notice>{error}</Notice> : null}
              <Btn type="submit" disabled={busy} className="w-full" size="lg">
                {busy ? "One moment…" : mode === "login" ? "Sign in" : "Create account"}
              </Btn>
            </form>

            <button
              type="button"
              onClick={() => {
                setMode(mode === "login" ? "register" : "login");
                setError(null);
              }}
              className="mt-3 w-full text-center text-[12px] font-medium text-stone-500 underline-offset-4 hover:text-stone-900 hover:underline"
            >
              {mode === "login"
                ? "New customer? Create an account"
                : "Already have an account? Sign in"}
            </button>

            <div className="mt-8">
              <div className="flex items-center gap-3">
                <span className="h-px flex-1 bg-stone-900/10" />
                <span className="text-[9px] font-semibold uppercase tracking-[0.2em] text-stone-400">
                  Or step into a demo role
                </span>
                <span className="h-px flex-1 bg-stone-900/10" />
              </div>
              <div className="mt-3 grid gap-2.5 sm:grid-cols-3">
                {DEMO_ACCOUNTS.map((account) => (
                  <button
                    key={account.role}
                    type="button"
                    disabled={busy}
                    onClick={() => void useDemo(account)}
                    className="group flex items-start gap-2.5 rounded-2xl border border-stone-900/10 bg-[#fffcf6]/70 p-3 text-left transition hover:-translate-y-0.5 hover:border-stone-900/20 hover:bg-white disabled:opacity-50"
                  >
                    <span
                      className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-[10px] font-bold text-white ${account.accent}`}
                    >
                      {account.label[0]}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-[12px] font-semibold">
                        {account.label}
                      </span>
                      <span className="mt-0.5 block truncate text-[10px] text-stone-500">
                        {account.blurb}
                      </span>
                    </span>
                  </button>
                ))}
              </div>
              <button
                type="button"
                disabled={busy}
                onClick={() => void useDemo(OPS_ACCOUNT)}
                className="mt-3 w-full text-center text-[10px] font-semibold uppercase tracking-[0.14em] text-stone-400 hover:text-stone-700"
              >
                Operations console (admin) →
              </button>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
