import { useEffect, useRef, useState } from "react";
import type { ServerEvent } from "../types";

export type SocketStatus = "connecting" | "open" | "closed";

const MAX_BACKOFF_MS = 10_000;

/** Keeps one WebSocket to /ws open, reconnecting with capped exponential backoff. */
export function useSocket(onEvent: (event: ServerEvent) => void): SocketStatus {
  const [status, setStatus] = useState<SocketStatus>("connecting");
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retryTimer: number | undefined;
    let attempt = 0;
    let stopped = false;

    const connect = () => {
      const scheme = location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${scheme}://${location.host}/ws`);
      setStatus("connecting");
      socket.onopen = () => {
        attempt = 0;
        setStatus("open");
      };
      socket.onmessage = (message) => handler.current(JSON.parse(message.data) as ServerEvent);
      socket.onclose = () => {
        setStatus("closed");
        if (stopped) return;
        const delay = Math.min(MAX_BACKOFF_MS, 500 * 2 ** attempt++);
        retryTimer = window.setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      stopped = true;
      window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, []);

  return status;
}
