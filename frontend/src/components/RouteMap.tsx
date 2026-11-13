import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import type { Tracking, TrackingRoute } from "../lib/api";

type Point = { lat: number; lng: number };

const DEFAULT_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    openstreetmap: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [{ id: "openstreetmap", type: "raster", source: "openstreetmap" }],
};

function routePoints(tracking: Tracking, route: TrackingRoute | null): Point[] {
  if (route?.points.length) return route.points;
  if (tracking.points.length) return tracking.points;
  return [
    { lat: tracking.restaurant_lat, lng: tracking.restaurant_lng },
    { lat: tracking.drop_lat, lng: tracking.drop_lng },
  ];
}

function phaseLabel(route: TrackingRoute | null): string {
  if (route?.phase === "to_pickup") return "Rider to restaurant";
  if (route?.phase === "to_drop") return "Rider to you";
  return "Restaurant to you";
}

export function RouteMap({
  tracking,
  route,
}: {
  tracking: Tracking;
  route: TrackingRoute | null;
}) {
  const container = useRef<HTMLDivElement | null>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const markers = useRef<Record<string, maplibregl.Marker>>({});
  const [ready, setReady] = useState(false);
  const points = routePoints(tracking, route);

  useEffect(() => {
    if (!container.current || map.current) return;
    const next = new maplibregl.Map({
      container: container.current,
      style: import.meta.env.VITE_MAP_STYLE_URL?.trim() || DEFAULT_STYLE,
      center: [tracking.restaurant_lng, tracking.restaurant_lat],
      zoom: 13,
    });
    next.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    next.on("load", () => {
      next.addSource("delivery-route", {
        type: "geojson",
        data: {
          type: "Feature",
          properties: {},
          geometry: { type: "LineString", coordinates: [] },
        },
      });
      next.addLayer({
        id: "delivery-route-shadow",
        type: "line",
        source: "delivery-route",
        paint: { "line-color": "#fff8ee", "line-width": 7, "line-opacity": 0.9 },
      });
      next.addLayer({
        id: "delivery-route-line",
        type: "line",
        source: "delivery-route",
        paint: {
          "line-color": "#d94f2b",
          "line-width": 4,
          "line-opacity": 0.95,
          "line-dasharray": [1, 1.4],
        },
      });
      setReady(true);
    });
    map.current = next;
    return () => {
      map.current = null;
      markers.current = {};
      next.remove();
    };
  }, [tracking.restaurant_lat, tracking.restaurant_lng]);

  useEffect(() => {
    const activeMap = map.current;
    if (!activeMap || !ready) return;
    const coordinates = points.map((point) => [point.lng, point.lat]);
    const source = activeMap.getSource("delivery-route") as maplibregl.GeoJSONSource | undefined;
    source?.setData({
      type: "Feature",
      properties: {},
      geometry: { type: "LineString", coordinates },
    });

    const markerPoints: Record<string, { point: Point; color: string }> = {
      restaurant: {
        point: { lat: tracking.restaurant_lat, lng: tracking.restaurant_lng },
        color: "#1f5b46",
      },
      customer: {
        point: { lat: tracking.drop_lat, lng: tracking.drop_lng },
        color: "#d94f2b",
      },
    };
    if (tracking.rider) {
      markerPoints.rider = {
        point: { lat: tracking.rider.lat, lng: tracking.rider.lng },
        color: "#111827",
      };
    }

    for (const [key, marker] of Object.entries(markers.current)) {
      if (!markerPoints[key]) {
        marker.remove();
        delete markers.current[key];
      }
    }
    for (const [key, item] of Object.entries(markerPoints)) {
      const position: [number, number] = [item.point.lng, item.point.lat];
      const marker = markers.current[key];
      if (marker) marker.setLngLat(position);
      else {
        markers.current[key] = new maplibregl.Marker({ color: item.color })
          .setLngLat(position)
          .addTo(activeMap);
      }
    }

    const bounds = new maplibregl.LngLatBounds();
    for (const coordinate of coordinates) bounds.extend(coordinate as [number, number]);
    for (const { point } of Object.values(markerPoints)) bounds.extend([point.lng, point.lat]);
    if (!bounds.isEmpty()) {
      activeMap.fitBounds(bounds, { padding: 56, maxZoom: 15, duration: 450 });
    }
  }, [points, ready, tracking]);

  const routeLabel = route?.is_estimated ? "Estimated route" : "Road route";
  const locationLabel = tracking.simulated ? "Simulated rider" : "Live GPS";

  return (
    <div className="relative overflow-hidden rounded-[24px] border border-stone-900/10 bg-[#e8e2d4]">
      <div
        ref={container}
        className="h-[280px] w-full"
        role="img"
        aria-label="Live delivery map showing restaurant, customer, and rider positions"
      />
      <div className="absolute left-3 top-3 rounded-full border border-stone-900/10 bg-[#fffcf6]/95 px-2.5 py-1 text-[9px] font-bold uppercase tracking-[0.14em] text-stone-700 shadow-sm backdrop-blur">
        {phaseLabel(route)} · {routeLabel}
      </div>
      <div className="absolute left-3 top-10 rounded-full bg-stone-900/85 px-2.5 py-1 text-[9px] font-bold uppercase tracking-[0.14em] text-[#f8f3e9] shadow-sm backdrop-blur">
        {tracking.rider ? locationLabel : "Rider pending"}
      </div>
      <div className="flex items-center justify-between gap-3 border-t border-stone-900/10 bg-[#fffcf6]/90 px-4 py-3 text-[10px] font-semibold uppercase tracking-[0.1em] text-stone-500">
        <span>{route ? `${Math.round(route.distance_m)} m · ${Math.ceil(route.duration_s / 60)} min` : "Loading route"}</span>
        <span>{route?.routing_provider ?? "fallback"}</span>
        <span>{route?.is_estimated ? "Simulated estimate" : "Road geometry"}</span>
      </div>
    </div>
  );
}
