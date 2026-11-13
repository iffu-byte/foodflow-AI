import { useState } from "react";

import { ApiError, addAddress, type Address } from "../lib/api";
import { Btn, Field, Modal, Notice } from "./market";

export function AddressModal({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: (address: Address) => void;
}) {
  const [label, setLabel] = useState("Home");
  const [line1, setLine1] = useState("");
  const [line2, setLine2] = useState("");
  const [city, setCity] = useState("Hyderabad");
  const [lat, setLat] = useState("17.443");
  const [lng, setLng] = useState("78.377");
  const [phone, setPhone] = useState("");
  const [isDefault, setIsDefault] = useState(false);
  const [busy, setBusy] = useState(false);
  const [locating, setLocating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const useCurrentLocation = () => {
    if (!navigator.geolocation) {
      setError("GPS is unavailable in this browser. Enter a map pin instead.");
      return;
    }
    setLocating(true);
    setError(null);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setLat(position.coords.latitude.toFixed(6));
        setLng(position.coords.longitude.toFixed(6));
        setLocating(false);
      },
      () => {
        setError("Location permission was not granted. Enter your delivery pin manually.");
        setLocating(false);
      },
      { enableHighAccuracy: true, maximumAge: 60000, timeout: 12000 },
    );
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const saved = await addAddress({
        label,
        line1,
        line2: line2 || null,
        city,
        lat: Number(lat),
        lng: Number(lng),
        phone: phone || null,
        is_default: isDefault,
      });
      onSaved(saved);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save this address.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="Add a delivery address" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Label" value={label} onChange={setLabel} required />
          <Field
            label="Phone"
            value={phone}
            onChange={setPhone}
            placeholder="+91…"
          />
        </div>
        <Field
          label="Address line"
          value={line1}
          onChange={setLine1}
          placeholder="Flat 4B, Jasmine Residency"
          required
        />
        <Field
          label="Landmark / area"
          value={line2}
          onChange={setLine2}
          placeholder="Indiranagar, near the park"
        />
        <div className="grid grid-cols-[1fr_100px_100px] gap-3">
          <Field label="City" value={city} onChange={setCity} required />
          <Field label="Lat" value={lat} onChange={setLat} type="number" step={0.001} required />
          <Field label="Lng" value={lng} onChange={setLng} type="number" step={0.001} required />
        </div>
        <Btn type="button" size="sm" variant="outline" onClick={useCurrentLocation} disabled={locating}>
          {locating ? "Locating…" : "Use my current GPS"}
        </Btn>
        <button
          type="button"
          onClick={() => setIsDefault((value) => !value)}
          className="flex items-center gap-2 text-[12px] font-medium text-stone-600"
        >
          <span
            className={`flex h-4 w-4 items-center justify-center rounded border text-[9px] ${
              isDefault
                ? "border-[#d94f2b] bg-[#d94f2b] text-white"
                : "border-stone-400 bg-white"
            }`}
          >
            {isDefault ? "✓" : ""}
          </span>
          Make this my default address
        </button>
        <p className="text-[10px] leading-relaxed text-stone-400">
          GPS is requested once to save this doorstep pin. It is never live-tracked after
          checkout; riders share delivery location separately.
        </p>
        {error ? <Notice>{error}</Notice> : null}
        <Btn type="submit" disabled={busy} className="w-full">
          {busy ? "Saving…" : "Save address"}
        </Btn>
      </form>
    </Modal>
  );
}
