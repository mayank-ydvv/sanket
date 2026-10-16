import { useEffect, useRef, useState } from "react";
import type { ServerMessage } from "../types";

export type SocketStatus = "connecting" | "open" | "closed";

const MAX_BACKOFF_MS = 10_000;

/** One WebSocket to /ws, reconnecting with capped exponential backoff. */
export function useSocket(onMessage: (message: ServerMessage) => void, onOpen: () => void): SocketStatus {
  const [status, setStatus] = useState<SocketStatus>("connecting");
  const handlers = useRef({ onMessage, onOpen });
  handlers.current = { onMessage, onOpen };

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
        handlers.current.onOpen();
      };
      socket.onmessage = (message) => handlers.current.onMessage(JSON.parse(message.data) as ServerMessage);
      socket.onclose = () => {
        setStatus("closed");
        if (stopped) return;
        retryTimer = window.setTimeout(connect, Math.min(MAX_BACKOFF_MS, 500 * 2 ** attempt++));
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
