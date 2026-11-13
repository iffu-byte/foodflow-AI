import { useCallback, useEffect, useRef, useState } from "react";

import { pingRiderLocation, type RiderProfile } from "./api";

export type RiderLocationMode =
  | "idle"
  | "locating"
  | "live"
  | "simulated"
  | "denied";

type Position = { lat: number; lng: number; accuracyM: number | null };
type LocationSource = "gps" | "simulated";

const SIMULATION_INTERVAL_MS = 9000;
const GPS_MAX_INTERVAL_MS = 12000;
const GPS_MOVED_INTERVAL_MS = 4000;
const GPS_MIN_MOVEMENT_M = 20;

function distanceMeters(
  a: { lat: number; lng: number },
  b: { lat: number; lng: number },
): number {
  const radius = 6371000;
  const toRad = (value: number) => (value * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);
  const value =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * radius * Math.asin(Math.sqrt(value));
}

function moveToward(
  base: { lat: number; lng: number },
  target: { lat: number; lng: number },
  fraction: number,
) {
  return {
    lat: base.lat + (target.lat - base.lat) * fraction,
    lng: base.lng + (target.lng - base.lng) * fraction,
  };
}

export interface RiderLocationControls {
  mode: RiderLocationMode;
  accuracyM: number | null;
  lastSentAt: string | null;
  error: string | null;
  sendNow: () => Promise<LocationSource | null>;
  retryGps: () => void;
}

export function useRiderLocation({
  online,
  initialPosition,
  target,
  onProfile,
}: {
  online: boolean;
  initialPosition: { lat: number; lng: number } | null;
  target: { lat: number; lng: number } | null;
  onProfile: (profile: RiderProfile) => void;
}): RiderLocationControls {
  const [mode, setMode] = useState<RiderLocationMode>("idle");
  const [accuracyM, setAccuracyM] = useState<number | null>(null);
  const [lastSentAt, setLastSentAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const mountedRef = useRef(true);
  const modeRef = useRef<RiderLocationMode>("idle");
  const positionRef = useRef<Position | null>(null);
  const initialRef = useRef(initialPosition);
  const targetRef = useRef(target);
  const onProfileRef = useRef(onProfile);
  const lastSentRef = useRef<{ lat: number; lng: number; at: number } | null>(
    null,
  );
  const inFlightRef = useRef(false);

  useEffect(() => {
    modeRef.current = mode;
  }, [mode]);

  useEffect(() => {
    initialRef.current = initialPosition;
  }, [initialPosition]);

  useEffect(() => {
    targetRef.current = target;
  }, [target]);

  useEffect(() => {
    onProfileRef.current = onProfile;
  }, [onProfile]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const sendPosition = useCallback(
    async (
      position: Position,
      source: LocationSource,
    ): Promise<LocationSource | null> => {
      if (inFlightRef.current) return null;
      inFlightRef.current = true;
      try {
        const next = await pingRiderLocation(position.lat, position.lng, {
          source,
          accuracy_m: source === "gps" ? position.accuracyM : null,
        });
        lastSentRef.current = {
          lat: position.lat,
          lng: position.lng,
          at: Date.now(),
        };
        if (!mountedRef.current) return source;
        setLastSentAt(new Date().toISOString());
        setError(null);
        onProfileRef.current(next);
        return source;
      } catch (failure) {
        if (mountedRef.current) {
          setError(
            failure instanceof Error
              ? failure.message
              : "Could not send a location update.",
          );
        }
        return null;
      } finally {
        inFlightRef.current = false;
      }
    },
    [],
  );

  const shouldSend = useCallback((position: Position) => {
    const last = lastSentRef.current;
    if (last === null) return true;
    const elapsed = Date.now() - last.at;
    if (elapsed >= GPS_MAX_INTERVAL_MS) return true;
    return (
      elapsed >= GPS_MOVED_INTERVAL_MS &&
      distanceMeters(last, position) >= GPS_MIN_MOVEMENT_M
    );
  }, []);

  const sendGps = useCallback(
    (position: Position) => {
      if (shouldSend(position)) {
        void sendPosition(position, "gps");
      }
    },
    [sendPosition, shouldSend],
  );

  useEffect(() => {
    setError(null);
    if (!online) {
      setMode("idle");
      setAccuracyM(null);
      return;
    }
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setMode("simulated");
      setError("GPS is unavailable. Simulated updates keep dispatch fresh.");
      return;
    }

    let stopped = false;
    let firstFix = true;
    let watchId: number | null = null;
    let fallbackTimer: number | undefined;
    setMode("locating");
    fallbackTimer = window.setTimeout(() => {
      if (!stopped && positionRef.current === null) {
        setMode("simulated");
        setError("No GPS fix yet. Simulated updates keep dispatch fresh.");
      }
    }, 9000);

    const success = (position: GeolocationPosition) => {
      if (stopped) return;
      if (fallbackTimer !== undefined) {
        window.clearTimeout(fallbackTimer);
        fallbackTimer = undefined;
      }
      const next: Position = {
        lat: position.coords.latitude,
        lng: position.coords.longitude,
        accuracyM: Number.isFinite(position.coords.accuracy)
          ? position.coords.accuracy
          : null,
      };
      positionRef.current = next;
      setMode("live");
      setAccuracyM(next.accuracyM);
      setError(null);
      if (firstFix) {
        firstFix = false;
        void sendPosition(next, "gps");
      } else {
        sendGps(next);
      }
    };

    const failure = (failure: GeolocationPositionError) => {
      if (stopped) return;
      if (failure.code === 1) {
        setMode("denied");
        setError(
          "Location permission is blocked. Simulated updates keep dispatch fresh.",
        );
      } else {
        setMode("simulated");
        setError(
          "GPS is unavailable. Simulated updates keep dispatch fresh.",
        );
      }
    };

    try {
      watchId = navigator.geolocation.watchPosition(success, failure, {
        enableHighAccuracy: true,
        maximumAge: 10000,
        timeout: 15000,
      });
    } catch {
      setMode("simulated");
      setError("GPS is unavailable. Simulated updates keep dispatch fresh.");
    }

    return () => {
      stopped = true;
      if (fallbackTimer !== undefined) window.clearTimeout(fallbackTimer);
      if (watchId !== null) navigator.geolocation.clearWatch(watchId);
    };
  }, [attempt, online, sendGps, sendPosition]);

  const simulate = useCallback(async () => {
    const base = positionRef.current ?? initialRef.current;
    if (!base) return null;
    const goal = targetRef.current;
    const next = goal
      ? moveToward(base, goal, 0.22)
      : {
          lat: base.lat + (Math.random() - 0.5) * 0.0016,
          lng: base.lng + (Math.random() - 0.5) * 0.0016,
        };
    const position: Position = { ...next, accuracyM: null };
    positionRef.current = position;
    setAccuracyM(null);
    return sendPosition(position, "simulated");
  }, [sendPosition]);

  useEffect(() => {
    if (!online || mode === "idle" || mode === "locating" || mode === "live") {
      return;
    }
    let cancelled = false;
    const tick = () => {
      if (!cancelled) void simulate();
    };
    const prime = window.setTimeout(tick, 1200);
    const timer = window.setInterval(tick, SIMULATION_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(prime);
      window.clearInterval(timer);
    };
  }, [mode, online, simulate]);

  const sendNow = useCallback(async (): Promise<LocationSource | null> => {
    const current = positionRef.current;
    if (modeRef.current === "live" && current) {
      return sendPosition(current, "gps");
    }
    const base = current ?? initialRef.current;
    if (!base) return null;
    const goal = targetRef.current;
    const next = goal
      ? moveToward(base, goal, 0.28)
      : {
          lat: base.lat + (Math.random() - 0.5) * 0.002,
          lng: base.lng + (Math.random() - 0.5) * 0.002,
        };
    const position: Position = { ...next, accuracyM: null };
    positionRef.current = position;
    setAccuracyM(null);
    return sendPosition(position, "simulated");
  }, [sendPosition]);

  const retryGps = useCallback(() => {
    setAttempt((current) => current + 1);
  }, []);

  return {
    mode,
    accuracyM,
    lastSentAt,
    error,
    sendNow,
    retryGps,
  };
}
