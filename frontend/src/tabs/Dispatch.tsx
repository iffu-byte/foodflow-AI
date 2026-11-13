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
import { assignOrder, getCandidates, getOrders } from "../lib/api";
import type { Assignment, Candidate, Order } from "../lib/api";
import { formatCurrency, formatMinutes, shortId, timeAgo } from "../lib/format";

export default function Dispatch() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [assignment, setAssignment] = useState<Assignment | null>(null);
  const [loading, setLoading] = useState(true);
  const [candidatesLoading, setCandidatesLoading] = useState(false);
  const [busyRider, setBusyRider] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadOrders = useCallback(async () => {
    try {
      const rows = await getOrders("READY", 100);
      const dispatchable = rows.filter((order) => !order.rider_id);
      setOrders(dispatchable);
      setSelectedId((current) =>
        current && dispatchable.some((order) => order.id === current)
          ? current
          : dispatchable[0]?.id ?? null,
      );
      setError(null);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not load orders");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadOrders();
    const timer = window.setInterval(() => void loadOrders(), 12_000);
    return () => window.clearInterval(timer);
  }, [loadOrders]);

  useEffect(() => {
    if (!selectedId) {
      setCandidates([]);
      return;
    }
    let cancelled = false;
    setCandidatesLoading(true);
    getCandidates(selectedId)
      .then((rows) => {
        if (!cancelled) setCandidates(rows);
      })
      .catch((failure) => {
        if (!cancelled) {
          setError(failure instanceof Error ? failure.message : "Could not load candidates");
        }
      })
      .finally(() => {
        if (!cancelled) setCandidatesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const runAssignment = async (riderId?: string) => {
    if (!selectedId) return;
    setBusyRider(riderId ?? "auto");
    setError(null);
    try {
      const result = await assignOrder(selectedId, riderId);
      setAssignment(result);
      await loadOrders();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Assignment failed");
    } finally {
      setBusyRider(null);
    }
  };

  const selected = orders.find((order) => order.id === selectedId) ?? null;
  const best = candidates[0];

  return (
    <div className="space-y-5">
      <SectionHeading
        title="Dispatch desk"
        caption="Rank riders by ETA, load and vehicle fit before committing."
        action={
          <Button
            variant="outline"
            onClick={() => void loadOrders()}
            disabled={loading}
          >
            Refresh queue
          </Button>
        }
      />

      {error ? <ErrorNote message={error} /> : null}

      {assignment ? (
        <div className="rounded-2xl border border-emerald-400/20 bg-emerald-400/[0.06] px-4 py-3 text-sm text-emerald-200">
          Assigned <span className="font-medium">{assignment.rider.name}</span> to order{" "}
          <span className="font-mono">#{shortId(assignment.order.id)}</span> with a score of{" "}
          <span className="font-mono">{assignment.score.toFixed(3)}</span>.
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Ready queue" value={orders.length} hint="unassigned orders" />
        <Stat
          label="Candidates"
          value={candidates.length}
          hint="riders evaluated for selection"
          tone="sky"
        />
        <Stat
          label="Top score"
          value={best ? best.score.toFixed(3) : "--"}
          hint={best ? `pickup in ${formatMinutes(best.pickup_eta_min)}` : "no rider data"}
          tone="amber"
        />
      </div>

      {loading ? (
        <Loading label="Loading dispatch queue" />
      ) : orders.length === 0 ? (
        <EmptyState
          title="No orders waiting for a rider"
          hint="Orders appear here when the restaurant marks them ready and no rider is assigned."
        />
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,0.75fr)_minmax(0,1.25fr)]">
          <Panel className="overflow-hidden">
            <div className="border-b border-white/5 px-4 py-3">
              <p className="text-xs font-medium uppercase tracking-[0.18em] text-stone-500">
                Ready to assign
              </p>
            </div>
            <ul className="max-h-[560px] divide-y divide-white/5 overflow-y-auto">
              {orders.map((order) => (
                <li key={order.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(order.id)}
                    className={`w-full px-4 py-3 text-left transition ${
                      order.id === selectedId
                        ? "bg-emerald-400/[0.07]"
                        : "hover:bg-white/[0.03]"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-xs text-stone-400">
                        #{shortId(order.id)}
                      </span>
                      <span className="font-mono text-xs text-stone-500">
                        {formatCurrency(order.total_price)}
                      </span>
                    </div>
                    <p className="mt-1 font-mono text-[11px] text-stone-500">
                      {order.items.length} lines, placed {timeAgo(order.placed_at)}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel className="p-5">
            {selected ? (
              <>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-stone-500">
                      order #{shortId(selected.id)}
                    </p>
                    <h3 className="mt-1 font-serif text-xl italic text-stone-100">
                      {candidates.length} riders in range
                    </h3>
                  </div>
                  <Button
                    onClick={() => void runAssignment()}
                    disabled={busyRider !== null || candidates.length === 0}
                  >
                    {busyRider === "auto" ? "Assigning..." : "Auto-assign best"}
                  </Button>
                </div>

                {candidatesLoading ? (
                  <Loading label="Scoring riders" />
                ) : candidates.length === 0 ? (
                  <div className="mt-5">
                    <EmptyState
                      title="No riders available"
                      hint="Every rider is at capacity or offline. Retry once the fleet frees up."
                    />
                  </div>
                ) : (
                  <ul className="mt-5 space-y-3">
                    {candidates.map((candidate, index) => (
                      <li
                        key={candidate.rider.id}
                        className="rounded-xl border border-white/10 bg-white/[0.02] p-4"
                      >
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="font-mono text-[11px] text-stone-500">
                                {String(index + 1).padStart(2, "0")}
                              </span>
                              <p className="text-sm font-medium text-stone-100">
                                {candidate.rider.name}
                              </p>
                              <Badge tone={candidate.rider.status === "IDLE" ? "mint" : "amber"}>
                                {candidate.rider.status}
                              </Badge>
                            </div>
                            <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[11px] text-stone-500">
                              <span>{candidate.rider.vehicle}</span>
                              <span>{formatMinutes(candidate.pickup_eta_min)} pickup</span>
                              <span>{candidate.pickup_distance_km.toFixed(2)} km</span>
                              <span>load {candidate.active_load}/{candidate.rider.capacity}</span>
                            </div>
                          </div>
                          <Button
                            variant="outline"
                            onClick={() => void runAssignment(candidate.rider.id)}
                            disabled={busyRider !== null}
                          >
                            {busyRider === candidate.rider.id ? "Assigning..." : "Assign"}
                          </Button>
                        </div>
                        <div className="mt-3">
                          <div className="flex items-center justify-between text-[11px] text-stone-500">
                            <span>match score</span>
                            <span className="font-mono">{candidate.score.toFixed(3)}</span>
                          </div>
                          <div className="mt-1.5">
                            <ScoreBar
                              value={candidate.score}
                              tone={index === 0 ? "mint" : "sky"}
                            />
                          </div>
                        </div>
                        <div className="mt-2.5 flex flex-wrap gap-1.5">
                          {candidate.reasons.map((reason) => (
                            <Badge key={reason} tone="neutral">
                              {reason}
                            </Badge>
                          ))}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            ) : (
              <EmptyState title="Pick an order" hint="Candidate ranking appears here." />
            )}
          </Panel>
        </div>
      )}
    </div>
  );
}
