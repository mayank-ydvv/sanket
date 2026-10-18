import { createContext, type ReactNode, useContext } from "react";
import { useLiveState } from "@/hooks/useLiveState";
import type { SocketStatus } from "@/hooks/useSocket";
import type { LiveState } from "./store";

const LiveContext = createContext<{ state: LiveState; status: SocketStatus } | null>(null);

/** One WebSocket + snapshot for every app section. */
export function LiveProvider({ children }: { children: ReactNode }) {
  const live = useLiveState();
  return <LiveContext.Provider value={live}>{children}</LiveContext.Provider>;
}

export function useLive(): { state: LiveState; status: SocketStatus } {
  const live = useContext(LiveContext);
  if (!live) throw new Error("useLive must be used inside LiveProvider");
  return live;
}
