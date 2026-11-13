import type { ReactNode } from "react";

const tones = {
  neutral: "bg-white/5 text-stone-300 ring-white/10",
  mint: "bg-emerald-400/10 text-emerald-300 ring-emerald-400/30",
  amber: "bg-amber-400/10 text-amber-300 ring-amber-400/30",
  rose: "bg-rose-400/10 text-rose-300 ring-rose-400/30",
  sky: "bg-sky-400/10 text-sky-300 ring-sky-400/30",
  violet: "bg-violet-400/10 text-violet-300 ring-violet-400/30",
} as const;

export type Tone = keyof typeof tones;

export function Panel({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-2xl border border-white/10 bg-[#0b1210]/90 shadow-[0_1px_0_rgba(255,255,255,0.04)_inset] ${className}`}
    >
      {children}
    </section>
  );
}

export function Badge({
  children,
  tone = "neutral",
  className = "",
}: {
  children: ReactNode;
  tone?: Tone;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ${tones[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

export function Dot({ tone = "mint" }: { tone?: Tone }) {
  const colors: Record<Tone, string> = {
    neutral: "bg-stone-400",
    mint: "bg-emerald-400",
    amber: "bg-amber-400",
    rose: "bg-rose-400",
    sky: "bg-sky-400",
    violet: "bg-violet-400",
  };
  return <span className={`inline-block h-1.5 w-1.5 rounded-full ${colors[tone]}`} />;
}

export function orderTone(status: string): Tone {
  switch (status) {
    case "PLACED":
      return "sky";
    case "ACCEPTED":
      return "violet";
    case "PREPARING":
      return "amber";
    case "READY":
      return "mint";
    case "PICKED_UP":
      return "sky";
    case "DELIVERED":
      return "mint";
    case "CANCELLED":
    case "FAILED":
      return "rose";
    default:
      return "neutral";
  }
}

export function Stat({
  label,
  value,
  hint,
  tone = "mint",
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: Tone;
}) {
  return (
    <Panel className="p-4">
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-stone-500">
          {label}
        </p>
        <Dot tone={tone} />
      </div>
      <p className="mt-3 font-mono text-2xl tracking-tight text-stone-100">{value}</p>
      {hint ? <p className="mt-1 text-xs text-stone-500">{hint}</p> : null}
    </Panel>
  );
}

export function ScoreBar({ value, tone = "mint" }: { value: number; tone?: Tone }) {
  const colors: Record<Tone, string> = {
    neutral: "bg-stone-400",
    mint: "bg-emerald-400",
    amber: "bg-amber-400",
    rose: "bg-rose-400",
    sky: "bg-sky-400",
    violet: "bg-violet-400",
  };
  const percent = Math.max(0, Math.min(100, value * 100));
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/5">
      <div
        className={`h-full rounded-full ${colors[tone]}`}
        style={{ width: `${percent}%` }}
      />
    </div>
  );
}

export function EmptyState({
  title,
  hint,
}: {
  title: string;
  hint?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-white/10 px-6 py-14 text-center">
      <p className="font-serif text-xl italic text-stone-300">{title}</p>
      {hint ? <p className="mt-2 max-w-md text-sm text-stone-500">{hint}</p> : null}
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 px-1 py-10 text-sm text-stone-500">
      <span className="h-3 w-3 animate-spin rounded-full border border-stone-600 border-t-emerald-300" />
      {label}
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-rose-400/25 bg-rose-400/5 px-4 py-3 text-sm text-rose-200">
      {message}
    </div>
  );
}

export function SimulatedBadge() {
  return (
    <Badge tone="amber" className="uppercase tracking-[0.12em]">
      Simulated data
    </Badge>
  );
}

export function SectionHeading({
  title,
  caption,
  action,
}: {
  title: string;
  caption?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 className="font-serif text-2xl italic tracking-tight text-stone-100">
          {title}
        </h2>
        {caption ? <p className="mt-1 text-sm text-stone-500">{caption}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function Button({
  children,
  onClick,
  disabled = false,
  variant = "solid",
  className = "",
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "solid" | "ghost" | "outline";
  className?: string;
  type?: "button" | "submit";
}) {
  const styles = {
    solid:
      "bg-emerald-300 text-emerald-950 hover:bg-emerald-200 disabled:bg-emerald-300/40 disabled:text-emerald-950/50",
    outline:
      "border border-white/10 bg-white/5 text-stone-200 hover:border-white/20 hover:bg-white/10 disabled:text-stone-600",
    ghost: "text-stone-400 hover:text-stone-100",
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center justify-center gap-2 rounded-xl px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed ${styles[variant]} ${className}`}
    >
      {children}
    </button>
  );
}
