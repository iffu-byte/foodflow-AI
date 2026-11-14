import { useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  estimatePortion,
  fileToDataUrl,
  getPortionConfig,
  mediaUrl,
  publishPortion,
  type BrowseMenuItem,
  type PortionConfig,
  type PortionEstimate,
} from "../../lib/api";
import { formatCurrency } from "../../lib/format";
import { Btn, Field, Notice, Spinner } from "../../components/market";

type Method = "photo_reference" | "container" | "scale" | "pieces" | "declared";
type Point = { x: number; y: number };
type Step = "reference" | "food";

const methods: Array<{ id: Method; label: string; hint: string }> = [
  {
    id: "photo_reference",
    label: "Photo + reference",
    hint: "Photograph the plated dish with a ₹10 coin, card or your standard plate in the same plane.",
  },
  { id: "container", label: "Container", hint: "Packed in a container of known volume." },
  { id: "scale", label: "Kitchen scale", hint: "Weigh the food without packaging. Most accurate." },
  { id: "pieces", label: "Count pieces", hint: "Naan, idli, momos, kebabs and other counted items." },
  { id: "declared", label: "Just declare", hint: "State grams and servings without a measurement." },
];

const verifiedMethods = new Set(["photo_reference", "container", "scale", "pieces"]);

function statusOf(item: BrowseMenuItem): { label: string; tone: string } {
  if (verifiedMethods.has(item.portion_method ?? "")) {
    return { label: `✓ ${item.portion_grams} g measured`, tone: "text-[#1f5b46]" };
  }
  if (item.portion_grams || item.portion_serves) {
    return { label: `${item.portion_grams ?? "?"} g declared`, tone: "text-[#8a5b0a]" };
  }
  return { label: "No quantity shown", tone: "text-rose-700" };
}

export function PortionStudio({
  menu,
  onItemUpdated,
  onlyItemId,
}: {
  menu: BrowseMenuItem[];
  onItemUpdated: (item: BrowseMenuItem) => void;
  /** Opened from one dish on the Menu page: no dish list or page header. */
  onlyItemId?: string;
}) {
  const [config, setConfig] = useState<PortionConfig | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [method, setMethod] = useState<Method>("photo_reference");
  const [reference, setReference] = useState("coin_10");
  const [customCm, setCustomCm] = useState("");
  const [profile, setProfile] = useState("");
  const [image, setImage] = useState<string | null>(null);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const [step, setStep] = useState<Step>("reference");
  const [refLine, setRefLine] = useState<[Point, Point] | null>(null);
  const [foodBox, setFoodBox] = useState<[Point, Point] | null>(null);
  const [drag, setDrag] = useState<Point | null>(null);
  const [capacity, setCapacity] = useState("750");
  const [fill, setFill] = useState(0.85);
  const [grams, setGrams] = useState("");
  const [pieces, setPieces] = useState("");
  const [pieceGrams, setPieceGrams] = useState("");
  const [estimate, setEstimate] = useState<PortionEstimate | null>(null);
  const [publishGrams, setPublishGrams] = useState("");
  const [publishServes, setPublishServes] = useState("");
  const [publishPieces, setPublishPieces] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);

  useEffect(() => {
    void getPortionConfig().then(setConfig).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (onlyItemId) {
      setSelectedId(onlyItemId);
      return;
    }
    if (!selectedId && menu.length) {
      const first = menu.find((item) => !verifiedMethods.has(item.portion_method ?? "")) ?? menu[0];
      setSelectedId(first.id);
    }
  }, [menu, selectedId, onlyItemId]);

  const item = useMemo(() => menu.find((row) => row.id === selectedId) ?? null, [menu, selectedId]);

  const resetMeasure = () => {
    setEstimate(null);
    setError(null);
    setDone(null);
  };

  useEffect(() => {
    resetMeasure();
    setImage(null);
    setRefLine(null);
    setFoodBox(null);
    setStep("reference");
    setPublishGrams(item?.portion_grams ? String(item.portion_grams) : "");
    setPublishServes(item?.portion_serves ? String(item.portion_serves) : "");
    setPublishPieces(item?.portion_pieces ? String(item.portion_pieces) : "");
  }, [item?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Convert a pointer event to natural image pixels (what the server measures in).
  const toImagePoint = (event: React.PointerEvent): Point | null => {
    const img = imgRef.current;
    if (!img || !natural) return null;
    const rect = img.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * natural.w;
    const y = ((event.clientY - rect.top) / rect.height) * natural.h;
    return { x: Math.max(0, Math.min(natural.w, x)), y: Math.max(0, Math.min(natural.h, y)) };
  };

  const onPointerDown = (event: React.PointerEvent) => {
    const point = toImagePoint(event);
    if (!point) return;
    (event.target as Element).setPointerCapture?.(event.pointerId);
    setDrag(point);
    if (step === "reference") setRefLine([point, point]);
    else setFoodBox([point, point]);
  };
  const onPointerMove = (event: React.PointerEvent) => {
    if (!drag) return;
    const point = toImagePoint(event);
    if (!point) return;
    if (step === "reference") setRefLine([drag, point]);
    else setFoodBox([drag, point]);
  };
  const onPointerUp = () => {
    if (!drag) return;
    setDrag(null);
    if (step === "reference" && refLine) setStep("food");
    resetMeasure();
  };

  const referencePx = refLine
    ? Math.hypot(refLine[1].x - refLine[0].x, refLine[1].y - refLine[0].y)
    : 0;
  const foodRx = foodBox ? Math.abs(foodBox[1].x - foodBox[0].x) / 2 : 0;
  const foodRy = foodBox ? Math.abs(foodBox[1].y - foodBox[0].y) / 2 : 0;

  const pickPhoto = async (file: File | undefined) => {
    if (!file) return;
    setBusy("photo");
    setError(null);
    try {
      const dataUrl = await fileToDataUrl(file);
      setImage(dataUrl);
      setRefLine(null);
      setFoodBox(null);
      setStep("reference");
      resetMeasure();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not read that photo.");
    } finally {
      setBusy(null);
    }
  };

  const runEstimate = async () => {
    if (!item) return;
    setBusy("estimate");
    setError(null);
    setDone(null);
    const payload: Record<string, unknown> = { method, profile: profile || undefined };
    if (method === "photo_reference") {
      Object.assign(payload, {
        reference,
        custom_reference_cm: reference === "custom" ? Number(customCm) || undefined : undefined,
        reference_px: Math.round(referencePx),
        food_rx_px: Math.round(foodRx),
        food_ry_px: Math.round(foodRy),
        image,
      });
    } else if (method === "container") {
      Object.assign(payload, { capacity_ml: Number(capacity), fill_fraction: fill });
    } else if (method === "scale") {
      Object.assign(payload, { grams: Number(grams) });
    } else if (method === "pieces") {
      Object.assign(payload, {
        pieces: Number(pieces),
        piece_grams: pieceGrams ? Number(pieceGrams) : undefined,
      });
    }
    try {
      const result = await estimatePortion(item.id, payload);
      setEstimate(result);
      setPublishGrams(String(result.grams));
      setPublishServes(String(result.serves));
      if (method === "pieces") setPublishPieces(pieces);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not estimate this portion.");
    } finally {
      setBusy(null);
    }
  };

  const publish = async () => {
    if (!item) return;
    setBusy("publish");
    setError(null);
    try {
      const next = await publishPortion(item.id, {
        method,
        grams: publishGrams ? Number(publishGrams) : null,
        serves: publishServes ? Number(publishServes) : null,
        pieces: publishPieces ? Number(publishPieces) : null,
        confidence: method === "declared" ? null : (estimate?.confidence ?? null),
        image: method === "photo_reference" ? image : null,
      });
      onItemUpdated(next);
      setDone(
        `${next.name} now shows ${next.portion_grams ?? "?"} g` +
          (next.nutrition ? ` · ${next.nutrition.kcal} kcal` : "") +
          " to every customer.",
      );
      setEstimate(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not publish this portion.");
    } finally {
      setBusy(null);
    }
  };

  const canEstimate =
    method === "photo_reference"
      ? Boolean(image && referencePx >= 8 && foodRx > 0 && foodRy > 0)
      : method === "container"
        ? Number(capacity) > 0
        : method === "scale"
          ? Number(grams) > 0
          : method === "pieces"
            ? Number(pieces) > 0
            : false;

  const measured = menu.filter((row) => verifiedMethods.has(row.portion_method ?? "")).length;

  return (
    <div className="space-y-5">
      <div className={onlyItemId ? "hidden" : ""}>
        <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500">
          Portion Studio
        </p>
        <h1 className="mt-1 font-serif text-[38px] italic leading-none">
          Show customers what they really get
        </h1>
        <p className="mt-2 max-w-2xl text-[12px] leading-relaxed text-stone-500">
          A single photo can't tell size on its own, so every photo here needs a reference of
          known size beside the food. Measured portions earn the{" "}
          <strong>Portion verified</strong> badge and raise your public trust score.{" "}
          {measured}/{menu.length} dishes measured.
        </p>
      </div>

      {error ? <Notice>{error}</Notice> : null}
      {done ? <Notice tone="success">{done}</Notice> : null}

      <div className={onlyItemId ? "" : "grid gap-4 lg:grid-cols-[280px_1fr] lg:items-start"}>
        <aside
          className={`overflow-hidden rounded-[22px] border border-stone-900/10 bg-[#fffcf6]/70 ${
            onlyItemId ? "hidden" : ""
          }`}
        >
          {menu.map((row) => {
            const status = statusOf(row);
            return (
              <button
                key={row.id}
                type="button"
                onClick={() => setSelectedId(row.id)}
                className={`block w-full border-b border-stone-900/8 px-3.5 py-2.5 text-left transition last:border-0 ${
                  row.id === selectedId ? "bg-stone-900 text-[#f8f3e9]" : "hover:bg-white"
                }`}
              >
                <p className="truncate text-[12px] font-semibold">{row.name}</p>
                <p
                  className={`mt-0.5 text-[10px] ${
                    row.id === selectedId ? "text-stone-400" : status.tone
                  }`}
                >
                  {status.label} · {formatCurrency(row.price)}
                </p>
              </button>
            );
          })}
        </aside>

        {item ? (
          <section className="space-y-4 rounded-[26px] border border-stone-900/10 bg-[#fffcf6]/80 p-4 sm:p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="font-serif text-[26px] italic leading-none">{item.name}</h2>
                <p className="mt-1 text-[11px] text-stone-500">
                  Now showing: {statusOf(item).label}
                  {item.nutrition ? ` · ${item.nutrition.kcal} kcal` : ""}
                </p>
              </div>
              {item.portion_photo_url ? (
                <img
                  src={mediaUrl(item.portion_photo_url) ?? undefined}
                  alt="Current portion photo"
                  className="h-16 w-16 rounded-xl object-cover"
                />
              ) : null}
            </div>

            <div className="flex flex-wrap gap-1.5">
              {methods.map((entry) => (
                <button
                  key={entry.id}
                  type="button"
                  onClick={() => {
                    setMethod(entry.id);
                    resetMeasure();
                  }}
                  className={`rounded-full border px-3 py-1.5 text-[11px] font-semibold transition ${
                    method === entry.id
                      ? "border-[#1f5b46] bg-[#1f5b46] text-white"
                      : "border-stone-900/15 bg-white/50 text-stone-600 hover:bg-white"
                  }`}
                >
                  {entry.label}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-stone-500">
              {methods.find((entry) => entry.id === method)?.hint}
            </p>

            {method !== "declared" && config ? (
              <label className="block max-w-xs">
                <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-[0.16em] text-stone-500">
                  Dish shape
                </span>
                <select
                  value={profile}
                  onChange={(event) => {
                    setProfile(event.target.value);
                    resetMeasure();
                  }}
                  className="w-full rounded-xl border border-stone-900/15 bg-white/70 px-3 py-2.5 text-sm outline-none"
                >
                  <option value="">Auto-detect from dish name</option>
                  {config.profiles.map((entry) => (
                    <option key={entry.key} value={entry.key}>
                      {entry.label}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}

            {method === "photo_reference" ? (
              <div className="space-y-3">
                <div className="flex flex-wrap items-end gap-3">
                  <label className="block">
                    <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-[0.16em] text-stone-500">
                      Reference in the photo
                    </span>
                    <select
                      value={reference}
                      onChange={(event) => {
                        setReference(event.target.value);
                        resetMeasure();
                      }}
                      className="rounded-xl border border-stone-900/15 bg-white/70 px-3 py-2.5 text-sm outline-none"
                    >
                      {(config?.references ?? []).map((entry) => (
                        <option key={entry.key} value={entry.key}>
                          {entry.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  {reference === "custom" ? (
                    <Field
                      label="Its size (cm)"
                      value={customCm}
                      onChange={setCustomCm}
                      type="number"
                      step={0.1}
                    />
                  ) : null}
                  <label className="inline-flex cursor-pointer items-center justify-center rounded-full bg-stone-900 px-4 py-2.5 text-[13px] font-semibold text-[#f8f3e9] hover:bg-stone-800">
                    {busy === "photo" ? "Reading…" : image ? "Retake photo" : "Take / upload photo"}
                    <input
                      type="file"
                      accept="image/*"
                      capture="environment"
                      className="hidden"
                      onChange={(event) => void pickPhoto(event.target.files?.[0])}
                    />
                  </label>
                </div>

                {image ? (
                  <div>
                    <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px]">
                      <button
                        type="button"
                        onClick={() => setStep("reference")}
                        className={`rounded-full px-2.5 py-1 font-semibold ${
                          step === "reference"
                            ? "bg-[#f4b942] text-stone-900"
                            : "bg-stone-900/[0.06] text-stone-600"
                        }`}
                      >
                        1 · Drag across the reference {referencePx ? `(${Math.round(referencePx)} px)` : ""}
                      </button>
                      <button
                        type="button"
                        onClick={() => setStep("food")}
                        className={`rounded-full px-2.5 py-1 font-semibold ${
                          step === "food"
                            ? "bg-[#d94f2b] text-white"
                            : "bg-stone-900/[0.06] text-stone-600"
                        }`}
                      >
                        2 · Drag a box around the food {foodRx ? "✓" : ""}
                      </button>
                    </div>
                    <div
                      className="relative inline-block max-w-full touch-none select-none overflow-hidden rounded-2xl border border-stone-900/10"
                      onPointerDown={onPointerDown}
                      onPointerMove={onPointerMove}
                      onPointerUp={onPointerUp}
                    >
                      <img
                        ref={imgRef}
                        src={image}
                        alt="Portion to measure"
                        draggable={false}
                        onLoad={(event) =>
                          setNatural({
                            w: event.currentTarget.naturalWidth,
                            h: event.currentTarget.naturalHeight,
                          })
                        }
                        className="block max-h-[420px] max-w-full cursor-crosshair"
                      />
                      {natural ? (
                        <svg
                          viewBox={`0 0 ${natural.w} ${natural.h}`}
                          className="pointer-events-none absolute inset-0 h-full w-full"
                        >
                          {refLine ? (
                            <line
                              x1={refLine[0].x}
                              y1={refLine[0].y}
                              x2={refLine[1].x}
                              y2={refLine[1].y}
                              stroke="#f4b942"
                              strokeWidth={Math.max(3, natural.w / 250)}
                              strokeLinecap="round"
                            />
                          ) : null}
                          {foodBox ? (
                            <ellipse
                              cx={(foodBox[0].x + foodBox[1].x) / 2}
                              cy={(foodBox[0].y + foodBox[1].y) / 2}
                              rx={foodRx}
                              ry={foodRy}
                              fill="rgba(217,79,43,0.18)"
                              stroke="#d94f2b"
                              strokeWidth={Math.max(3, natural.w / 300)}
                            />
                          ) : null}
                        </svg>
                      ) : null}
                    </div>
                    <p className="mt-1 text-[10px] text-stone-400">
                      Keep the reference flat on the same table as the plate. Photograph from
                      straight above for the best result.
                    </p>
                  </div>
                ) : null}
              </div>
            ) : null}

            {method === "container" ? (
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block">
                  <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-[0.16em] text-stone-500">
                    Container
                  </span>
                  <select
                    value={capacity}
                    onChange={(event) => {
                      setCapacity(event.target.value);
                      resetMeasure();
                    }}
                    className="w-full rounded-xl border border-stone-900/15 bg-white/70 px-3 py-2.5 text-sm outline-none"
                  >
                    {[250, 300, 500, 650, 750, 1000, 1500].map((ml) => (
                      <option key={ml} value={ml}>
                        {ml} ml box
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-[0.16em] text-stone-500">
                    Filled to {Math.round(fill * 100)}%
                  </span>
                  <input
                    type="range"
                    min={0.3}
                    max={1}
                    step={0.05}
                    value={fill}
                    onChange={(event) => {
                      setFill(Number(event.target.value));
                      resetMeasure();
                    }}
                    className="mt-3 w-full accent-[#1f5b46]"
                  />
                </label>
              </div>
            ) : null}

            {method === "scale" ? (
              <div className="max-w-[220px]">
                <Field label="Weight on the scale (g)" value={grams} onChange={setGrams} type="number" />
              </div>
            ) : null}

            {method === "pieces" ? (
              <div className="grid max-w-md gap-3 sm:grid-cols-2">
                <Field label="Pieces per portion" value={pieces} onChange={setPieces} type="number" />
                <Field
                  label="Grams per piece (optional)"
                  value={pieceGrams}
                  onChange={setPieceGrams}
                  type="number"
                />
              </div>
            ) : null}

            {method !== "declared" ? (
              <Btn
                disabled={!canEstimate || busy === "estimate"}
                onClick={() => void runEstimate()}
              >
                {busy === "estimate"
                  ? config?.ai_available && method === "photo_reference"
                    ? "Measuring + AI cross-check…"
                    : "Measuring…"
                  : "Estimate portion"}
              </Btn>
            ) : null}

            {busy === "estimate" ? <Spinner label="Working out the grams" /> : null}

            {estimate ? (
              <div className="rounded-2xl border border-[#1f5b46]/20 bg-[#1f5b46]/[0.05] p-4">
                <div className="flex flex-wrap items-end justify-between gap-3">
                  <div>
                    <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-[#1f5b46]">
                      Estimate
                    </p>
                    <p className="font-serif text-[34px] leading-none">≈ {estimate.grams} g</p>
                    <p className="mt-1 text-[11px] text-stone-600">
                      Range {estimate.low_grams}-{estimate.high_grams} g · serves about{" "}
                      {estimate.serves}
                    </p>
                  </div>
                  <div className="w-40">
                    <p className="text-[9px] uppercase tracking-[0.14em] text-stone-500">
                      Confidence {Math.round(estimate.confidence * 100)}%
                    </p>
                    <div className="mt-1 h-2 overflow-hidden rounded-full bg-stone-900/10">
                      <div
                        className="h-full rounded-full bg-[#1f5b46]"
                        style={{ width: `${estimate.confidence * 100}%` }}
                      />
                    </div>
                  </div>
                </div>
                <ul className="mt-3 space-y-0.5 text-[11px] text-stone-600">
                  {estimate.explanation.map((line) => (
                    <li key={line}>· {line}</li>
                  ))}
                </ul>
                {estimate.ai_check ? (
                  <div className="mt-3 rounded-xl bg-white/70 p-3 text-[11px] text-stone-600">
                    <p className="text-[9px] font-bold uppercase tracking-[0.16em] text-stone-500">
                      AI vision cross-check (Gemini)
                    </p>
                    <p className="mt-1">
                      Sees: {estimate.ai_check.dish_detected ?? "?"}
                      {estimate.ai_check.matches_menu_item === false ? " (does not match the menu item!)" : ""}
                      {estimate.ai_check.estimated_grams ? ` · about ${Math.round(estimate.ai_check.estimated_grams)} g` : ""}
                      {estimate.ai_check.reference_visible === false ? " · reference not visible" : ""}
                      {estimate.ai_check.looks_real_photo === false ? " · may not be a real photo" : ""}
                    </p>
                    {estimate.ai_check.agreement ? <p className="mt-0.5">{estimate.ai_check.agreement}</p> : null}
                    <p className="mt-0.5 text-[9px] text-stone-400">
                      Cost of this check: ${estimate.ai_check.cost_usd.toFixed(5)}
                    </p>
                  </div>
                ) : method === "photo_reference" && !estimate.ai_available ? (
                  <p className="mt-2 text-[10px] text-stone-400">
                    Add GEMINI_API_KEY to enable an AI vision cross-check of this photo.
                  </p>
                ) : null}
              </div>
            ) : null}

            {method === "declared" || estimate ? (
              <div className="rounded-2xl border border-stone-900/10 bg-white/60 p-4">
                <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-stone-500">
                  Publish to the menu
                </p>
                <div className="mt-2 grid gap-3 sm:grid-cols-3">
                  <Field label="Grams" value={publishGrams} onChange={setPublishGrams} type="number" />
                  <Field label="Serves" value={publishServes} onChange={setPublishServes} type="number" />
                  <Field label="Pieces" value={publishPieces} onChange={setPublishPieces} type="number" />
                </div>
                <Btn
                  className="mt-3"
                  disabled={busy === "publish" || (!publishGrams && !publishServes)}
                  onClick={() => void publish()}
                >
                  {busy === "publish" ? "Publishing…" : "Publish portion"}
                </Btn>
                <p className="mt-2 text-[10px] text-stone-400">
                  Customers rate quantity after delivery. Portions that come out short lower your
                  trust score, so publish what you really serve.
                </p>
              </div>
            ) : null}
          </section>
        ) : (
          <Spinner label="Loading the menu" />
        )}
      </div>
    </div>
  );
}
