import { useState } from "react";

import { mediaUrl, type PhotoCredit } from "../lib/api";

export function creditText(credit: PhotoCredit | null | undefined): string {
  if (!credit) return "";
  if (credit.source === "restaurant") return "Photo by the restaurant";
  return `Photo: ${credit.author ?? "unknown"} · ${credit.licence ?? ""} · ${credit.source}`;
}

/**
 * A real photo with its credit. Stock photos come from Wikimedia Commons under
 * free licences that require attribution, so every image carries a small
 * credit link; a restaurant's own photo is marked as such. When there is no
 * photo (or it fails to load), the fallback is rendered instead.
 */
export function Photo({
  src,
  credit,
  alt,
  className = "",
  fallback,
  showCredit = true,
  creditTop = false,
}: {
  src: string | null | undefined;
  credit?: PhotoCredit | null;
  alt: string;
  className?: string;
  fallback?: React.ReactNode;
  showCredit?: boolean;
  /** Put the credit at the top when a button overlaps the bottom edge. */
  creditTop?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  const url = mediaUrl(src);
  if (!url || failed) return <>{fallback ?? <div className={`bg-stone-200 ${className}`} />}</>;
  return (
    <div className={`relative overflow-hidden bg-stone-200 ${className}`}>
      <img
        src={url}
        alt={alt}
        loading="lazy"
        onError={() => setFailed(true)}
        className="absolute inset-0 h-full w-full object-cover"
      />
      {showCredit && credit ? (
        <a
          href={credit.page_url ?? undefined}
          target="_blank"
          rel="noreferrer"
          onClick={(event) => event.stopPropagation()}
          title={creditText(credit)}
          className={`absolute ${creditTop ? "top-1" : "bottom-1"} right-1 rounded-full bg-black/45 px-1.5 py-0.5 text-[8px] font-semibold leading-none text-white/90 backdrop-blur hover:bg-black/70`}
        >
          {credit.source === "restaurant" ? "Restaurant photo" : `© ${(credit.author ?? "").slice(0, 18)}`}
        </a>
      ) : null}
    </div>
  );
}
