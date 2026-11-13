import { useEffect, useState } from "react";

import {
  ApiError,
  fileToDataUrl,
  getMyTrust,
  linkMyListing,
  mediaUrl,
  patchMyTrust,
  searchMyListing,
  uploadKitchenPhoto,
  type ListingCandidate,
  type TrustProfile,
} from "../../lib/api";
import { Btn, Field, Notice, Spinner } from "../../components/market";

const kitchenTypes = [
  { id: "dine_in", label: "Dine-in restaurant", hint: "Customers can visit and eat here." },
  { id: "cloud_kitchen", label: "Cloud kitchen", hint: "Delivery only, no seating." },
  {
    id: "shared_kitchen",
    label: "Shared kitchen",
    hint: "Several brands cook in this same kitchen.",
  },
] as const;

export function TrustBoard() {
  const [profile, setProfile] = useState<TrustProfile | null>(null);
  const [licence, setLicence] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [candidates, setCandidates] = useState<{ provider: string; rows: ListingCandidate[] } | null>(
    null,
  );
  const [caption, setCaption] = useState("Prep counter, this morning");

  const apply = (next: TrustProfile) => {
    setProfile(next);
    setLicence(next.fssai.number ?? "");
    setValidUntil(next.fssai.valid_until ?? "");
  };

  useEffect(() => {
    getMyTrust()
      .then(apply)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load."));
  }, []);

  const run = async (key: string, task: () => Promise<void>) => {
    setBusy(key);
    setError(null);
    setNotice(null);
    try {
      await task();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Failed.");
    } finally {
      setBusy(null);
    }
  };

  if (!profile) {
    return error ? <Notice>{error}</Notice> : <Spinner label="Loading your trust profile" />;
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500">
            Trust profile · what customers see
          </p>
          <h1 className="mt-1 font-serif text-[38px] italic leading-none">
            Trust {profile.score}/100 · grade {profile.grade}
          </h1>
        </div>
        <Btn
          variant="outline"
          disabled={busy === "refresh"}
          onClick={() =>
            void run("refresh", async () => {
              apply(await getMyTrust(true));
              setNotice("Location re-checked against the map.");
            })
          }
        >
          {busy === "refresh" ? "Checking the map…" : "Re-check my location"}
        </Btn>
      </div>

      {error ? <Notice>{error}</Notice> : null}
      {notice ? <Notice tone="success">{notice}</Notice> : null}
      {profile.warnings.length ? (
        <Notice>Customers see: {profile.warnings.join(" · ")}</Notice>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-[24px] border border-stone-900/10 bg-[#fffcf6]/80 p-4">
          <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-stone-500">
            Score breakdown
          </p>
          <div className="mt-3 space-y-2.5">
            {profile.components.map((component) => (
              <div key={component.key}>
                <div className="flex justify-between text-[12px] font-semibold">
                  <span>{component.label}</span>
                  <span>
                    {component.points}/{component.max}
                  </span>
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-stone-900/10">
                  <div
                    className="h-full rounded-full bg-[#1f5b46]"
                    style={{ width: `${(component.points / component.max) * 100}%` }}
                  />
                </div>
                <p className="mt-0.5 text-[10px] text-stone-500">{component.detail}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="space-y-3 rounded-[24px] border border-stone-900/10 bg-[#fffcf6]/80 p-4">
          <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-stone-500">
            Licence and kitchen
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="FSSAI number (14 digits)" value={licence} onChange={setLicence} />
            <Field label="Valid until" value={validUntil} onChange={setValidUntil} type="date" />
          </div>
          <p className="text-[10px] text-stone-500">{profile.fssai.label}</p>
          <div className="grid gap-1.5">
            {kitchenTypes.map((type) => (
              <label
                key={type.id}
                className={`flex cursor-pointer items-start gap-2 rounded-xl border p-2.5 text-[11px] ${
                  profile.kitchen_type === type.id
                    ? "border-[#1f5b46] bg-[#1f5b46]/[0.05]"
                    : "border-stone-900/10"
                }`}
              >
                <input
                  type="radio"
                  name="kitchen_type"
                  checked={profile.kitchen_type === type.id}
                  onChange={() =>
                    void run("kitchen", async () => {
                      apply(await patchMyTrust({ kitchen_type: type.id }));
                      setNotice("Kitchen type updated.");
                    })
                  }
                  className="mt-0.5 accent-[#1f5b46]"
                />
                <span>
                  <span className="block font-semibold">{type.label}</span>
                  <span className="text-stone-500">{type.hint}</span>
                </span>
              </label>
            ))}
          </div>
          {profile.shared_kitchen.length ? (
            <p className="rounded-xl bg-[#d94f2b]/[0.07] p-2.5 text-[11px] text-stone-700">
              We found {profile.shared_kitchen.map((row) => row.name).join(", ")} at the same
              kitchen location. Declaring a shared or cloud kitchen keeps your full disclosure
              score.
            </p>
          ) : null}
          <label className="flex items-center gap-2 text-[11px]">
            <input
              type="checkbox"
              checked={profile.price_parity}
              onChange={(event) =>
                void run("parity", async () => {
                  apply(await patchMyTrust({ price_parity: event.target.checked }));
                })
              }
              className="accent-[#1f5b46]"
            />
            Menu prices here match my dine-in prices
          </label>
          <Btn
            size="sm"
            disabled={busy === "licence"}
            onClick={() =>
              void run("licence", async () => {
                apply(
                  await patchMyTrust({
                    fssai_license: licence,
                    fssai_valid_until: validUntil || undefined,
                  }),
                );
                setNotice("Licence saved.");
              })
            }
          >
            {busy === "licence" ? "Saving…" : "Save licence"}
          </Btn>
        </section>
      </div>

      <section className="rounded-[24px] border border-stone-900/10 bg-[#fffcf6]/80 p-4">
        <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-stone-500">
          Map listing · {profile.reality.provider === "google" ? "Google Maps" : "OpenStreetMap"} ·
          verdict: {profile.reality.verdict.replaceAll("_", " ")}
        </p>
        <p className="mt-1 text-[11px] text-stone-500">
          Customers see real photos and the address of your listing next to your menu. Link the
          listing that is really yours.
          {!profile.providers.google_maps
            ? " Google Maps photos need GOOGLE_MAPS_API_KEY on the server; until then OpenStreetMap is used."
            : ""}
        </p>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <Field
            label="Search the map"
            value={query}
            onChange={setQuery}
            placeholder={profile.restaurant_name}
            className="min-w-[240px] flex-1"
          />
          <Btn
            variant="outline"
            disabled={busy === "search"}
            onClick={() =>
              void run("search", async () => {
                const result = await searchMyListing(query || undefined);
                setCandidates({ provider: result.provider, rows: result.candidates });
              })
            }
          >
            {busy === "search" ? "Searching…" : "Search"}
          </Btn>
        </div>
        {candidates ? (
          <div className="mt-3 space-y-1.5">
            {candidates.rows.length === 0 ? (
              <p className="text-[11px] text-stone-500">No listings found near your pin.</p>
            ) : null}
            {candidates.rows.map((row) => (
              <div
                key={`${row.name}-${row.distance_m}`}
                className="flex items-center justify-between gap-2 rounded-xl border border-stone-900/10 bg-white/60 p-2.5 text-[11px]"
              >
                <span>
                  <strong>{row.name}</strong>
                  {row.address ? ` · ${row.address}` : ""}
                  {row.distance_m !== null ? ` · ${Math.round(row.distance_m)} m away` : ""}
                  {row.rating ? ` · ★ ${row.rating} (${row.rating_count})` : ""}
                </span>
                {row.place_id ? (
                  <Btn
                    size="sm"
                    disabled={busy === "link"}
                    onClick={() =>
                      void run("link", async () => {
                        apply(await linkMyListing(row.place_id as string));
                        setNotice(`Linked to ${row.name}.`);
                      })
                    }
                  >
                    This is us
                  </Btn>
                ) : (
                  <span className="text-[9px] uppercase tracking-[0.1em] text-stone-400">
                    OSM result
                  </span>
                )}
              </div>
            ))}
          </div>
        ) : null}
      </section>

      <section className="rounded-[24px] border border-stone-900/10 bg-[#fffcf6]/80 p-4">
        <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-stone-500">
          Kitchen photos · dated, taken in the app
        </p>
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <Field label="Caption" value={caption} onChange={setCaption} className="min-w-[240px]" />
          <label className="inline-flex cursor-pointer items-center justify-center rounded-full bg-stone-900 px-4 py-2.5 text-[13px] font-semibold text-[#f8f3e9] hover:bg-stone-800">
            {busy === "photo" ? "Uploading…" : "Take kitchen photo"}
            <input
              type="file"
              accept="image/*"
              capture="environment"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (!file) return;
                void run("photo", async () => {
                  await uploadKitchenPhoto(await fileToDataUrl(file), caption);
                  apply(await getMyTrust());
                  setNotice("Kitchen photo added. Customers see when it was taken.");
                });
              }}
            />
          </label>
        </div>
        <div className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-6">
          {profile.kitchen_photos.map((photo) => (
            <figure key={photo.id} className="overflow-hidden rounded-xl bg-stone-200">
              <img
                src={mediaUrl(photo.url) ?? undefined}
                alt={photo.caption}
                className="aspect-square w-full object-cover"
              />
              <figcaption className="px-1.5 py-1 text-[9px] text-stone-500">
                {new Date(photo.taken_at).toLocaleDateString()}
              </figcaption>
            </figure>
          ))}
        </div>
      </section>
    </div>
  );
}
