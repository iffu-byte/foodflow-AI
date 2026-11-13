import { useEffect, useState } from "react";

import type { Order, OrderEvent, Rider } from "./api";
import { orderSocketUrl } from "./api";

export type StreamStatus = "idle" | "connecting" | "live" | "reconnecting";

export interface OrderStreamState {
  status: StreamStatus;
  orderId: string | null;
  order: Partial<Order> | null;
  events: OrderEvent[];
  rider: Rider | null;
  lastMessageAt: string | null;
}

type StreamMessage =
  | {
      type: "order_snapshot";
      order_id: string;
      sent_at: string;
      order: Order;
      rider: Rider | null;
      events: OrderEvent[];
    }
  | {
      type: "order_event";
      order_id: string;
      sent_at: string;
      order: Partial<Order>;
      event: OrderEvent;
    }
  | { type: "rider_location"; order_id: string; sent_at: string; rider: Rider }
  | { type: "heartbeat"; order_id: string; sent_at: string };

const initialState: OrderStreamState = {
  status: "idle",
  orderId: null,
  order: null,
  events: [],
  rider: null,
  lastMessageAt: null,
};

export function useOrderStream(orderId: string | null): OrderStreamState {
  const [state, setState] = useState<OrderStreamState>(initialState);

  useEffect(() => {
    setState({ ...initialState, orderId, status: orderId ? "connecting" : "idle" });
    if (!orderId) return;

    let cancelled = false;
    let socket: WebSocket | null = null;
    let retryTimer: number | undefined;
    let attempt = 0;

    const update = (patch: Partial<OrderStreamState>) => {
      if (cancelled) return;
      setState((previous) =>
        previous.orderId === orderId ? { ...previous, ...patch } : previous,
      );
    };

    const connect = () => {
      if (cancelled) return;
      socket = new WebSocket(orderSocketUrl(orderId));

      socket.onopen = () => {
        attempt = 0;
        update({ status: "live" });
      };

      socket.onmessage = (raw) => {
        let message: StreamMessage;
        try {
          message = JSON.parse(raw.data as string) as StreamMessage;
        } catch {
          return;
        }

        if (message.type === "order_snapshot") {
          update({
            status: "live",
            order: message.order,
            events: message.events,
            rider: message.rider,
            lastMessageAt: message.sent_at,
          });
          return;
        }

        if (message.type === "order_event") {
          setState((previous) => {
            if (previous.orderId !== orderId) return previous;
            const exists = previous.events.some(
              (event) => event.id === message.event.id,
            );
            return {
              ...previous,
              order: { ...(previous.order ?? {}), ...message.order },
              events: exists ? previous.events : [...previous.events, message.event],
              lastMessageAt: message.sent_at,
            };
          });
          return;
        }

        if (message.type === "rider_location") {
          update({ rider: message.rider, lastMessageAt: message.sent_at });
          return;
        }

        update({ lastMessageAt: message.sent_at });
      };

      socket.onclose = () => {
        if (cancelled) return;
        update({ status: "reconnecting" });
        attempt += 1;
        retryTimer = window.setTimeout(connect, Math.min(1000 * 2 ** attempt, 8000));
      };

      socket.onerror = () => {
        socket?.close();
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, [orderId]);

  return state;
}
