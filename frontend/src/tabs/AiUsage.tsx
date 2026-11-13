import { useCallback, useEffect, useState } from "react";

import { Badge, Button, EmptyState, ErrorNote, Loading, Panel, SectionHeading, Stat } from "../components/ui";
import { getAiUsage, type AiUsage as Usage } from "../lib/api";

const purposeLabel: Record<string, string> = {
  portion_vision: "Portion photo cross-check",
  nutrition_estimate: "Nutrition for unknown dishes",
  reality_check: "Kitchen map check",
  text_search: "Google listing search",
  place_details: "Google listing details",
  photo: "Google location photos",
};

export default function AiUsage() {
  const [usage, setUsage] = useState<Usage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      setUsage(await getAiUsage());
      setError(null);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not load AI usage");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 20_000);
    return () => window.clearInterval(timer);
  }, [load]);

  if (loading) return <Loading label="Reading the AI meter" />;
  if (error) return <ErrorNote message={error} />;
  if (!usage) return null;

  const used = usage.budget_usd > 0 ? Math.min(1, usage.spent_usd / usage.budget_usd) : 0;
  return (
    <div className="space-y-5">
      <SectionHeading
        title="AI and maps cost meter"
        caption="Every paid call is logged with an estimated cost. Cached results are free, and paid calls stop when today's budget is spent; each feature then falls back to its local method."
        action={<Button onClick={() => void load()}>Refresh</Button>}
      />
      <div className="grid gap-3 sm:grid-cols-4">
        <Stat label="Spent today" value={`$${usage.spent_usd.toFixed(4)}`} hint={`of $${usage.budget_usd.toFixed(2)} budget`} tone={used > 0.8 ? "rose" : "mint"} />
        <Stat label="Calls" value={usage.calls} hint="AI, maps and cache lookups" tone="sky" />
        <Stat
          label="Cache hit rate"
          value={usage.cache_hit_rate === null ? "—" : `${Math.round(usage.cache_hit_rate * 100)}%`}
          hint="served without a paid call"
          tone="amber"
        />
        <Stat label="Remaining" value={`$${usage.remaining_usd.toFixed(4)}`} hint="resets at 00:00 UTC" tone="violet" />
      </div>
      <Panel className="p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={usage.gemini_enabled ? "mint" : "neutral"}>
            Gemini {usage.gemini_enabled ? "on" : "off (local fallbacks)"}
          </Badge>
          <Badge tone={usage.google_maps_enabled ? "mint" : "neutral"}>
            Google Maps {usage.google_maps_enabled ? "on" : "off (OpenStreetMap)"}
          </Badge>
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
          <div className="h-full rounded-full bg-emerald-400" style={{ width: `${used * 100}%` }} />
        </div>
      </Panel>
      {usage.lines.length === 0 ? (
        <EmptyState title="No AI or map calls yet today." />
      ) : (
        <Panel className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="text-[11px] uppercase tracking-[0.14em] text-stone-500">
              <tr className="border-b border-white/10">
                <th className="px-4 py-3">Provider</th>
                <th className="px-4 py-3">Purpose</th>
                <th className="px-4 py-3">Calls</th>
                <th className="px-4 py-3">Cache hits</th>
                <th className="px-4 py-3">Tokens in / out</th>
                <th className="px-4 py-3">Est. cost</th>
              </tr>
            </thead>
            <tbody>
              {usage.lines.map((line) => (
                <tr key={`${line.provider}-${line.purpose}`} className="border-b border-white/5 text-stone-300">
                  <td className="px-4 py-2.5">{line.provider}</td>
                  <td className="px-4 py-2.5">{purposeLabel[line.purpose] ?? line.purpose}</td>
                  <td className="px-4 py-2.5 font-mono">{line.calls}</td>
                  <td className="px-4 py-2.5 font-mono">{line.cache_hits}</td>
                  <td className="px-4 py-2.5 font-mono">
                    {line.input_tokens} / {line.output_tokens}
                  </td>
                  <td className="px-4 py-2.5 font-mono">${line.est_cost_usd.toFixed(5)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
    </div>
  );
}
