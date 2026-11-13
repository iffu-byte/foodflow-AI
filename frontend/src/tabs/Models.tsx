import { useCallback, useEffect, useState } from "react";

import {
  Badge,
  Button,
  EmptyState,
  ErrorNote,
  Loading,
  Panel,
  SectionHeading,
  Stat,
} from "../components/ui";
import { getModels, retrainModel } from "../lib/api";
import type { ModelVersion, RetrainResult } from "../lib/api";
import { formatDateTime, formatPercent } from "../lib/format";

export default function Models() {
  const [models, setModels] = useState<ModelVersion[]>([]);
  const [result, setResult] = useState<RetrainResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [training, setTraining] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const rows = await getModels();
      setModels(rows);
      setError(null);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not load models");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const runRetrain = async (force: boolean) => {
    setTraining(true);
    setError(null);
    try {
      const outcome = await retrainModel(force);
      setResult(outcome);
      await load();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Retraining failed");
    } finally {
      setTraining(false);
    }
  };

  const active = models.find((model) => model.is_active);
  const activeMetrics = active?.metrics ?? {};

  return (
    <div className="space-y-5">
      <SectionHeading
        title="Learning loop"
        caption="Retrain the ETA model, compare validation error, promote only improvements."
        action={
          <div className="flex gap-2">
            <Button
              variant="outline"
              onClick={() => void runRetrain(true)}
              disabled={training}
            >
              {training ? "Training..." : "Force promote"}
            </Button>
            <Button onClick={() => void runRetrain(false)} disabled={training}>
              {training ? "Training..." : "Retrain model"}
            </Button>
          </div>
        }
      />

      {error ? <ErrorNote message={error} /> : null}

      {result ? (
        <div
          className={`rounded-2xl border px-4 py-3 text-sm ${
            result.promoted
              ? "border-emerald-400/20 bg-emerald-400/[0.06] text-emerald-200"
              : "border-amber-400/20 bg-amber-400/[0.05] text-amber-200"
          }`}
        >
          <span className="font-medium">{result.version}</span>{" "}
          {result.promoted
            ? "was promoted to production."
            : "was kept as a candidate because it did not beat the active model."}{" "}
          Validation MAE {result.metrics.total_mae.toFixed(2)} min across{" "}
          {result.metrics.n_val} held-out rows. Active version:{" "}
          <span className="font-mono">{result.active_version ?? "none"}</span>.
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Active version"
          value={
            <span className="text-base">
              {active ? active.version : "none"}
            </span>
          }
          hint={active ? `trained ${formatDateTime(active.created_at)}` : "no promoted model"}
        />
        <Stat
          label="Total MAE"
          value={
            activeMetrics.total_mae !== undefined
              ? `${activeMetrics.total_mae.toFixed(2)}m`
              : "--"
          }
          hint="validation error on held-out rows"
        />
        <Stat
          label="P10-P90 coverage"
          value={formatPercent(activeMetrics.p10_p90_coverage)}
          hint="target interval coverage"
          tone="sky"
        />
        <Stat
          label="Training rows"
          value={activeMetrics.n_train ?? active?.row_count ?? 0}
          hint={`${activeMetrics.n_val ?? 0} validation rows`}
          tone="violet"
        />
      </div>

      <Panel className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-white/5 px-4 py-3">
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-stone-500">
            Model registry
          </p>
          <span className="font-mono text-[11px] text-stone-600">
            {models.length} versions
          </span>
        </div>

        {loading ? (
          <div className="px-4">
            <Loading label="Loading registry" />
          </div>
        ) : models.length === 0 ? (
          <div className="p-4">
            <EmptyState
              title="No model versions yet"
              hint="Run a retrain to train from simulator rows and create the first registry entry."
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-white/5 font-mono text-[10px] uppercase tracking-[0.16em] text-stone-500">
                  <th className="px-4 py-2.5 font-medium">Version</th>
                  <th className="px-4 py-2.5 font-medium">Rows</th>
                  <th className="px-4 py-2.5 font-medium">Total MAE</th>
                  <th className="px-4 py-2.5 font-medium">Prep / drive</th>
                  <th className="px-4 py-2.5 font-medium">Coverage</th>
                  <th className="px-4 py-2.5 font-medium">Created</th>
                  <th className="px-4 py-2.5 font-medium">State</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {models.map((model) => (
                  <tr key={model.id} className={model.is_active ? "bg-emerald-400/[0.04]" : ""}>
                    <td className="px-4 py-3 font-mono text-xs text-stone-300">
                      {model.version}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-stone-500">
                      {model.metrics.n_train ?? model.row_count}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-stone-300">
                      {model.metrics.total_mae !== undefined
                        ? `${model.metrics.total_mae.toFixed(2)}m`
                        : "--"}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-stone-500">
                      {model.metrics.prep_mae !== undefined && model.metrics.drive_mae !== undefined
                        ? `${model.metrics.prep_mae.toFixed(1)} / ${model.metrics.drive_mae.toFixed(1)}`
                        : "--"}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-stone-500">
                      {formatPercent(model.metrics.p10_p90_coverage)}
                    </td>
                    <td className="px-4 py-3 text-xs text-stone-500">
                      {formatDateTime(model.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      <Badge tone={model.is_active ? "mint" : "neutral"}>
                        {model.is_active ? "active" : "candidate"}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <p className="max-w-3xl text-xs leading-relaxed text-stone-500">
        Promotion compares validation MAE against the active bundle. Rejected runs stay in
        the registry and their artifact is written alongside production. Every number here
        is trained on simulated city data.
      </p>
    </div>
  );
}
