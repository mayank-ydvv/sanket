import { useCallback, useRef, useState } from "react";
import { applyEvents, emptyState, type LiveState } from "../lib/store";
import type { Alert, Incident, LiveEvent, Report, ServerMessage } from "../types";
import { useSocket, type SocketStatus } from "./useSocket";

async function getJson<T>(url: string): Promise<T | null> {
  try {
    const response = await fetch(url);
    return response.ok ? ((await response.json()) as T) : null;
  } catch {
    return null;
  }
}

/** Board state: REST snapshot on (re)connect, then batched WebSocket diffs. */
export function useLiveState(): { state: LiveState; status: SocketStatus } {
  const ref = useRef<LiveState>(emptyState());
  const [, setVersion] = useState(0);

  const apply = useCallback((events: LiveEvent[]) => {
    const { state, missing } = applyEvents(ref.current, events);
    ref.current = state;
    setVersion((v) => v + 1);
    for (const id of missing) {
      void getJson<{ incident: Incident }>(`/api/incidents/${id}`).then((detail) => {
        if (detail) apply([{ type: "incident.created", data: detail.incident }]);
      });
    }
  }, []);

  const loadSnapshot = useCallback(async () => {
    const [incidents, reports, alerts] = await Promise.all([
      getJson<Incident[]>("/api/incidents?limit=300"),
      getJson<Report[]>("/api/reports?limit=300"),
      getJson<Alert[]>("/api/alerts?limit=300"),
    ]);
    apply([
      ...(incidents ?? []).map((data) => ({ type: "incident.created", data }) as LiveEvent),
      ...(reports ?? []).map((data) => ({ type: "report.created", data }) as LiveEvent),
      ...(alerts ?? []).map((data) => ({ type: "alert.sent", data }) as LiveEvent),
    ]);
  }, [apply]);

  const status = useSocket(
    useCallback((message: ServerMessage) => apply(message.data), [apply]),
    useCallback(() => void loadSnapshot(), [loadSnapshot]),
  );
  return { state: ref.current, status };
}
