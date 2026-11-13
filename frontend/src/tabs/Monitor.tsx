import { useCallback, useEffect, useState } from "react";

import {
  Badge,
  Button,
  EmptyState,
  ErrorNote,
  Loading,
  Panel,
  ScoreBar,
  SectionHeading,
  Stat,
} from "../components/ui";
import { getAtRisk, getMonitorSummary, getRestaurants, scanMonitor } from "../lib/api";
import type { MonitorSummary, Restaurant, RiskOrder, ScanResult } from "../lib/api";
import { formatMinutes, shortId, timeAgo } from "../lib/format";

const emptySummary: MonitorSummary = {
  active_orders: 0,
  at_risk: 0,
  late: 0,
  stalled: 0,
  avg_minutes_remaining: null,
};

export default function Monitor() {
  const [summary, setSummary] = useState<MonitorSummary>(emptySummary);
  const [risks, setRisks] = useState<RiskOrder[]>([]);
  const [restaurants, setRestaurants] = useState<Record<string, Restaurant>>({});
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [summaryRow, riskRows, restaurantRows] = await Promise.all([
        getMonitorSummary(),
        getAtRisk(60),
        getRestaurants(),
      ]);
      setSummary(summaryRow);
      setRisks(riskRows);
      setRestaurants(
        Object.fromEntries(restaurantRows.map((restaurant) => [restaurant.id, restaurant])),
      );
      setError(null);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not load monitor data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 15_000);
    return () => window.clearInterval(timer);
  }, [load]);

  const runScan = async () => {
    setScanning(true);
    setError(null);
    try {
      const result = await scanMonitor();
      setScan(result);
      await load();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Scan failed");
    } finally {
      setScanning(false);
    }
  };

  return (
    <div className="space-y-5">
      <SectionHeading
        title="Delay monitor"
        caption="Deadline pressure and kitchen stalls evaluated against promised ETAs."
        action={
          <Button onClick={() => void runScan()} disabled={scanning || loading}>
            {scanning ? "Scanning..." : "Scan active orders"}
          </Button>
        }
      />

      {error ? <ErrorNote message={error} /> : null}

      {scan ? (
        <div className="rounded-2xl border border-amber-400/20 bg-amber-400/[0.05] px-4 py-3 text-sm text-amber-200">
          Scanned {scan.scanned} orders, flagged {scan.flagged} and appended{" "}
          {scan.events_appended} delay events.
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Active orders"
          value={summary.active_orders}
          hint="orders still in motion"
        />
        <Stat
          label="At risk"
          value={summary.at_risk}
          hint="approaching their deadline"
          tone={summary.at_risk > 0 ? "amber" : "mint"}
        />
        <Stat
          label="Late"
          value={summary.late}
          hint="deadline already crossed"
          tone={summary.late > 0 ? "rose" : "mint"}
        />
        <Stat
          label="Stalled"
          value={summary.stalled}
          hint={`avg ${formatMinutes(summary.avg_minutes_remaining)} remaining`}
          tone={summary.stalled > 0 ? "rose" : "neutral"}
        />
      </div>

      {loading ? (
        <Loading label="Reading monitor state" />
      ) : risks.length === 0 ? (
        <EmptyState
          title="Nothing at risk"
          hint="The monitor scans active orders and raises flags only when deadlines tighten."
        />
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {risks.map((risk) => (
            <Panel key={risk.order.id} className="p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-stone-500">
                      #{shortId(risk.order.id)}
                    </p>
                    <Badge tone={risk.severity === "critical" ? "rose" : "amber"}>
                      {risk.severity}
                    </Badge>
                  </div>
                  <h3 className="mt-1 text-sm font-medium text-stone-100">
                    {restaurants[risk.order.restaurant_id]?.name ?? "Active order"}
                  </h3>
                </div>
                <div className="text-right">
                  <p className="font-mono text-2xl text-stone-100">{risk.risk_score}</p>
                  <p className="text-[10px] uppercase tracking-[0.14em] text-stone-500">
                    risk score
                  </p>
                </div>
              </div>

              <div className="mt-3">
                <ScoreBar
                  value={risk.risk_score / 100}
                  tone={risk.severity === "critical" ? "rose" : "amber"}
                />
              </div>

              <div className="mt-3 grid grid-cols-2 gap-2 font-mono text-[11px] text-stone-500">
                <span>remaining {formatMinutes(risk.minutes_remaining)}</span>
                <span>quiet for {risk.minutes_since_last_event.toFixed(1)} min</span>
                <span>rider {risk.rider ? risk.rider.name : "unassigned"}</span>
                <span>placed {timeAgo(risk.order.placed_at)}</span>
              </div>

              <div className="mt-3 flex flex-wrap gap-1.5">
                {risk.flags.map((flag) => (
                  <Badge key={flag} tone="rose">
                    {flag}
                  </Badge>
                ))}
                {risk.reasons.map((reason) => (
                  <Badge key={reason} tone="neutral">
                    {reason}
                  </Badge>
                ))}
              </div>
            </Panel>
          ))}
        </div>
      )}
    </div>
  );
}
