import { useEffect, useState } from "react";

import {
  ApiError,
  createRescue,
  endRescue,
  getRescueForecast,
  logPrep,
  type ForecastRow,
  type RescueForecast,
} from "../../lib/api";
import { formatCurrency } from "../../lib/format";
import { Btn, Modal, Notice, Spinner } from "../../components/market";

export function RescueBoard() {
  const [forecast, setForecast] = useState<RescueForecast | null>(null);
  const [prepared, setPrepared] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<{
    row: ForecastRow;
    qty: string;
    start: string;
    floor: string;
    minutes: string;
  } | null>(null);

  const apply = (next: RescueForecast) => {
    setForecast(next);
    setPrepared((current) => {
      const copy = { ...current };
      for (const row of next.items) {
        if (copy[row.menu_item_id] === undefined && row.prepared !== null) {
          copy[row.menu_item_id] = String(row.prepared);
        }
      }
      return copy;
    });
  };

  const load = () =>
    getRescueForecast()
      .then(apply)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load."));

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  const run = async (key: string, task: () => Promise<void>) => {
    setBusy(key);
    setError(null);
    try {
      await task();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(null);
    }
  };

  const openDraft = (row: ForecastRow) => {
    const suggestion = row.suggestion;
    const price = Number(row.price);
    setDraft({
      row,
      qty: String(suggestion?.qty ?? 3),
      start: suggestion?.start_price ?? String(Math.round(price * 0.6)),
      floor: suggestion?.floor_price ?? String(Math.max(10, Math.round(price * 0.3))),
      minutes: String(suggestion?.duration_min ?? 90),
    });
  };

  if (!forecast) {
    return error ? <Notice>{error}</Notice> : <Spinner label="Reading today's orders" />;
  }

  const live = forecast.items.filter((row) => row.live_listing);
  const suggested = forecast.items.filter((row) => row.suggestion);

  return (
    <div className="space-y-5">
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500">
          Rescue a meal · forecasting {forecast.horizon_hours.toFixed(1)} h ahead ·{" "}
          {forecast.hours_to_close.toFixed(1)} h to closing
        </p>
        <h1 className="mt-1 font-serif text-[38px] italic leading-none">
          Sell tonight&apos;s surplus, don&apos;t bin it
        </h1>
        <p className="mt-2 max-w-2xl text-[12px] leading-relaxed text-stone-500">
          Log how many portions you cooked today. The forecast compares that with your real
          orders and the last two hours&apos; sales pace and tells you what will likely be left at
          closing. A rescue listing&apos;s price falls steadily to your floor price so it sells.
        </p>
      </div>

      {error ? <Notice>{error}</Notice> : null}

      <div className="grid gap-2.5 sm:grid-cols-3">
        {[
          [String(live.length), "live rescue listings"],
          [String(suggested.length), "dishes likely left over"],
          [
            String(
              forecast.items.reduce((sum, row) => sum + (row.projected_leftover ?? 0), 0),
            ),
            "portions projected unsold",
          ],
        ].map(([value, label]) => (
          <div key={label} className="rounded-2xl border border-stone-900/10 bg-white/40 px-3.5 py-3">
            <p className="font-serif text-[24px] leading-none">{value}</p>
            <p className="mt-1 text-[9px] uppercase tracking-[0.16em] text-stone-500">{label}</p>
          </div>
        ))}
      </div>

      <div className="overflow-x-auto rounded-[22px] border border-stone-900/10 bg-[#fffcf6]/80">
        <table className="w-full min-w-[720px] text-left text-[12px]">
          <thead className="text-[9px] uppercase tracking-[0.14em] text-stone-500">
            <tr className="border-b border-stone-900/10">
              <th className="px-3 py-2.5">Dish</th>
              <th className="px-3 py-2.5">Cooked today</th>
              <th className="px-3 py-2.5">Sold</th>
              <th className="px-3 py-2.5">Pace / h</th>
              <th className="px-3 py-2.5">Likely left</th>
              <th className="px-3 py-2.5">Rescue</th>
            </tr>
          </thead>
          <tbody>
            {forecast.items.map((row) => (
              <tr key={row.menu_item_id} className="border-b border-stone-900/6 align-top last:border-0">
                <td className="px-3 py-2.5">
                  <p className="font-semibold">{row.name}</p>
                  <p className="text-[10px] text-stone-500">{formatCurrency(row.price)}</p>
                </td>
                <td className="px-3 py-2.5">
                  <div className="flex items-center gap-1.5">
                    <input
                      type="number"
                      min={0}
                      value={prepared[row.menu_item_id] ?? ""}
                      onChange={(event) =>
                        setPrepared((current) => ({
                          ...current,
                          [row.menu_item_id]: event.target.value,
                        }))
                      }
                      placeholder="—"
                      className="w-16 rounded-lg border border-stone-900/15 bg-white px-2 py-1 text-[12px] outline-none"
                    />
                    <Btn
                      size="sm"
                      variant="ghost"
                      disabled={busy === `prep-${row.menu_item_id}` || !prepared[row.menu_item_id]}
                      onClick={() =>
                        void run(`prep-${row.menu_item_id}`, async () =>
                          apply(await logPrep(row.menu_item_id, Number(prepared[row.menu_item_id]))),
                        )
                      }
                    >
                      Save
                    </Btn>
                  </div>
                </td>
                <td className="px-3 py-2.5">{row.sold_today}</td>
                <td className="px-3 py-2.5">{row.pace_per_hour}</td>
                <td className="px-3 py-2.5">
                  {row.projected_leftover ?? <span className="text-stone-400">log prep</span>}
                  {row.suggestion ? (
                    <p className="mt-0.5 max-w-[220px] text-[10px] text-stone-500">
                      {row.suggestion.reason}
                    </p>
                  ) : null}
                </td>
                <td className="px-3 py-2.5">
                  {row.live_listing ? (
                    <div>
                      <p className="font-semibold text-[#1f5b46]">
                        {formatCurrency(row.live_listing.current_price)} now ·{" "}
                        {row.live_listing.qty_left}/{row.live_listing.qty_total} left
                      </p>
                      <p className="text-[10px] text-stone-500">
                        Floor {formatCurrency(row.live_listing.floor_price)} · ends{" "}
                        {new Date(row.live_listing.ends_at).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </p>
                      <Btn
                        size="sm"
                        variant="ghost"
                        disabled={busy === `end-${row.live_listing.id}`}
                        onClick={() =>
                          void run(`end-${row.live_listing?.id}`, async () =>
                            apply(await endRescue(row.live_listing!.id)),
                          )
                        }
                      >
                        End listing
                      </Btn>
                    </div>
                  ) : (
                    <Btn
                      size="sm"
                      variant={row.suggestion ? "primary" : "outline"}
                      onClick={() => openDraft(row)}
                    >
                      {row.suggestion ? `Rescue ${row.suggestion.qty}` : "Go live"}
                    </Btn>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] text-stone-400">{forecast.method}</p>

      {draft ? (
        <Modal title={`Rescue ${draft.row.name}`} onClose={() => setDraft(null)}>
          <div className="grid grid-cols-2 gap-3">
            {(
              [
                ["qty", "Portions"],
                ["minutes", "Window (min)"],
                ["start", "Start price ₹"],
                ["floor", "Floor price ₹"],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className="block">
                <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-[0.16em] text-stone-500">
                  {label}
                </span>
                <input
                  type="number"
                  value={draft[key]}
                  onChange={(event) => setDraft({ ...draft, [key]: event.target.value })}
                  className="w-full rounded-xl border border-stone-900/15 bg-white/70 px-3 py-2.5 text-sm outline-none"
                />
              </label>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-stone-500">
            Menu price {formatCurrency(draft.row.price)}. The price falls in a straight line from{" "}
            {formatCurrency(draft.start || 0)} to {formatCurrency(draft.floor || 0)} over{" "}
            {draft.minutes} minutes, then the listing ends.
          </p>
          {error ? <div className="mt-2"><Notice>{error}</Notice></div> : null}
          <Btn
            className="mt-3 w-full"
            disabled={busy === "create"}
            onClick={() =>
              void run("create", async () => {
                await createRescue({
                  menu_item_id: draft.row.menu_item_id,
                  qty: Number(draft.qty),
                  start_price: draft.start,
                  floor_price: draft.floor,
                  duration_min: Number(draft.minutes),
                });
                setDraft(null);
                await load();
              })
            }
          >
            {busy === "create" ? "Going live…" : "Go live"}
          </Btn>
        </Modal>
      ) : null}
    </div>
  );
}
