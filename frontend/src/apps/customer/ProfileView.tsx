import { useEffect, useState } from "react";

import {
  ApiError,
  deleteAddress,
  getAddresses,
  getNutritionToday,
  getProfile,
  updateProfile,
  type Address,
  type AuthUser,
  type NutritionToday,
  type Profile,
} from "../../lib/api";
import { signOut } from "../../lib/session";
import { AddressModal } from "../../components/AddressModal";
import {
  Btn,
  Empty,
  Field,
  Notice,
  SimBadge,
  Spinner,
} from "../../components/market";

export function ProfileView({ user }: { user: AuthUser }) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [addresses, setAddresses] = useState<Address[]>([]);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [homeLat, setHomeLat] = useState("");
  const [homeLng, setHomeLng] = useState("");
  const [budget, setBudget] = useState("");
  const [diet, setDiet] = useState("");
  const [kcalGoal, setKcalGoal] = useState("");
  const [intake, setIntake] = useState<NutritionToday | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [showAddress, setShowAddress] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getProfile(), getAddresses()])
      .then(([me, rows]) => {
        if (cancelled) return;
        setProfile(me);
        setAddresses(rows);
        setName(me.name);
        setPhone(me.phone ?? "");
        setHomeLat(String(me.home_lat));
        setHomeLng(String(me.home_lng));
        setBudget(me.budget_pref ?? "");
        setDiet(me.diet_pref ?? "");
        setKcalGoal(me.daily_kcal_goal ? String(me.daily_kcal_goal) : "");
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Could not load your profile.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    void getNutritionToday()
      .then((today) => {
        if (!cancelled) setIntake(today);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const next = await updateProfile({
        name,
        phone: phone || null,
        budget_pref: budget || null,
        diet_pref: diet || null,
        home_lat: Number(homeLat),
        home_lng: Number(homeLng),
        daily_kcal_goal: kcalGoal ? Number(kcalGoal) : null,
      });
      void getNutritionToday().then(setIntake).catch(() => undefined);
      setProfile(next);
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2500);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save your profile.");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: string) => {
    setDeleting(id);
    try {
      await deleteAddress(id);
      setAddresses((rows) => rows.filter((row) => row.id !== id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not remove that address.");
    } finally {
      setDeleting(null);
    }
  };

  if (loading) return <Spinner label="Loading your account" />;

  return (
    <div className="space-y-5">
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500">
          Account
        </p>
        <h1 className="mt-1 font-serif text-[38px] italic leading-none">
          The person behind the order.
        </h1>
      </div>

      {error ? <Notice>{error}</Notice> : null}
      {saved ? <Notice tone="success">Profile saved. Preferences will shape future picks.</Notice> : null}

      <div className="grid gap-5 lg:grid-cols-[1fr_340px] lg:items-start">
        <form onSubmit={save} className="space-y-4">
          <section className="rounded-[26px] border border-stone-900/10 bg-[#fffcf6]/70 p-4 sm:p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-stone-500">
                  Basics
                </p>
                <h2 className="mt-1 font-serif text-[23px] italic">Who we are feeding</h2>
              </div>
              <SimBadge />
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <Field label="Name" value={name} onChange={setName} required />
              <Field label="Phone" value={phone} onChange={setPhone} placeholder="+91…" />
              <Field label="Home latitude" value={homeLat} onChange={setHomeLat} type="number" step={0.001} />
              <Field label="Home longitude" value={homeLng} onChange={setHomeLng} type="number" step={0.001} />
            </div>
            <p className="mt-2 text-[10px] leading-relaxed text-stone-400">
              Your home pin is used for distance and delivery estimates. You can use device
              GPS once when saving a delivery address; this profile is not live-tracked.
            </p>
          </section>

          <section className="rounded-[26px] border border-[#f4b942]/40 bg-[#f4b942]/10 p-4 sm:p-5">
            <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-[#8a5b0a]">
              Nutrition today · estimated from what you ordered
            </p>
            {intake ? (
              <>
                <div className="mt-2 flex items-end justify-between gap-3">
                  <p className="font-serif text-[30px] leading-none">
                    {Math.round(intake.totals.kcal)}
                    <span className="text-[14px] text-stone-500"> / {intake.goal_kcal} kcal</span>
                  </p>
                  <p className="text-[11px] text-stone-600">
                    {intake.totals.protein_g} g protein · {intake.totals.carbs_g} g carbs ·{" "}
                    {intake.totals.fat_g} g fat
                  </p>
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-stone-900/10">
                  <div
                    className={`h-full rounded-full ${
                      intake.totals.kcal > intake.goal_kcal ? "bg-[#d94f2b]" : "bg-[#1f5b46]"
                    }`}
                    style={{
                      width: `${Math.min(100, (intake.totals.kcal / intake.goal_kcal) * 100)}%`,
                    }}
                  />
                </div>
                {intake.lines.length ? (
                  <ul className="mt-2 space-y-0.5 text-[11px] text-stone-600">
                    {intake.lines.map((line) => (
                      <li key={`${line.order_id}-${line.name}`}>
                        {line.name} ×{line.qty} · {Math.round(line.kcal)} kcal
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-2 text-[11px] text-stone-500">Nothing ordered yet today.</p>
                )}
              </>
            ) : null}
            <div className="mt-3 max-w-[220px]">
              <Field
                label="Daily calorie goal"
                value={kcalGoal}
                onChange={setKcalGoal}
                type="number"
                min={800}
                max={6000}
                step={50}
                placeholder="2000"
              />
            </div>
          </section>

          <section className="rounded-[26px] border border-stone-900/10 bg-[#fffcf6]/70 p-4 sm:p-5">
            <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-stone-500">
              Taste memory
            </p>
            <h2 className="mt-1 font-serif text-[23px] italic">What sounds like you</h2>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <div>
                <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-stone-500">
                  Budget
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {["Value", "Balanced", "Premium", "No limit"].map((option) => (
                    <button
                      key={option}
                      type="button"
                      onClick={() => setBudget(option)}
                      className={`rounded-full border px-3 py-1.5 text-[11px] font-medium transition ${
                        budget === option
                          ? "border-[#d94f2b] bg-[#d94f2b] text-white"
                          : "border-stone-900/15 bg-white/40 text-stone-600"
                      }`}
                    >
                      {option}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-stone-500">
                  Diet
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {["Everything", "Vegetarian", "Vegan", "High protein"].map((option) => (
                    <button
                      key={option}
                      type="button"
                      onClick={() => setDiet(option)}
                      className={`rounded-full border px-3 py-1.5 text-[11px] font-medium transition ${
                        diet === option
                          ? "border-[#1f5b46] bg-[#1f5b46] text-white"
                          : "border-stone-900/15 bg-white/40 text-stone-600"
                      }`}
                    >
                      {option}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <Btn type="submit" className="mt-5" disabled={saving}>
              {saving ? "Saving…" : "Save preferences"}
            </Btn>
          </section>
        </form>

        <aside className="space-y-3">
          <section className="rounded-[24px] border border-stone-900/10 bg-[#fffcf6]/70 p-4">
            <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-stone-500">
              Account
            </p>
            <p className="mt-2 text-[14px] font-semibold">{profile?.name ?? user.name}</p>
            <p className="mt-0.5 text-[11px] text-stone-500">{profile?.email ?? user.email}</p>
            <p className="mt-2 inline-flex rounded-full bg-stone-900/[0.06] px-2 py-1 text-[9px] font-bold uppercase tracking-[0.12em] text-stone-500">
              {user.role}
            </p>
            <button
              type="button"
              onClick={signOut}
              className="mt-4 w-full rounded-full border border-stone-900/15 px-3 py-2 text-[11px] font-semibold text-stone-500 transition hover:border-rose-700/30 hover:text-rose-700"
            >
              Sign out
            </button>
          </section>

          <section className="rounded-[24px] border border-stone-900/10 bg-[#fffcf6]/70 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-stone-500">
                  Doorsteps
                </p>
                <h2 className="mt-1 font-serif text-[21px] italic">Saved addresses</h2>
              </div>
              <Btn size="sm" variant="outline" onClick={() => setShowAddress(true)}>
                + Add
              </Btn>
            </div>
            {addresses.length === 0 ? (
              <div className="mt-3">
                <Empty
                  title="No addresses saved."
                  hint="Add one to make checkout a two-click affair."
                />
              </div>
            ) : (
              <div className="mt-3 space-y-2">
                {addresses.map((address) => (
                  <div
                    key={address.id}
                    className="rounded-xl border border-stone-900/10 bg-white/40 p-3"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-[10px] font-bold uppercase tracking-[0.12em]">
                          {address.label}
                          {address.is_default ? (
                            <span className="ml-2 rounded-full bg-[#f4b942]/25 px-1.5 py-0.5 text-[8px] text-[#7d5309]">
                              Default
                            </span>
                          ) : null}
                        </p>
                        <p className="mt-1 text-[11px] leading-snug text-stone-600">
                          {address.line1}
                          {address.line2 ? `, ${address.line2}` : ""}
                        </p>
                        <p className="mt-0.5 text-[9px] uppercase tracking-[0.1em] text-stone-400">
                          {address.city}
                        </p>
                      </div>
                      <button
                        type="button"
                        disabled={deleting === address.id}
                        onClick={() => void remove(address.id)}
                        className="text-[10px] font-semibold text-stone-400 hover:text-rose-700"
                      >
                        {deleting === address.id ? "…" : "Remove"}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </aside>
      </div>

      {showAddress ? (
        <AddressModal
          onClose={() => setShowAddress(false)}
          onSaved={(address) => setAddresses((rows) => [...rows, address])}
        />
      ) : null}
    </div>
  );
}
