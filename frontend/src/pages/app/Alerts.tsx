import { BellOff, BellRing, Check, CircleAlert, History } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";
import { Link } from "react-router";
import { BlurFade } from "@/components/magicui/blur-fade";
import { DepartmentBadge, NeutralPill } from "@/components/ui/badges";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { useNow } from "@/hooks/useNow";
import { ApiError, api } from "@/lib/api";
import { useLive } from "@/lib/live";
import { waitingLabel } from "@/lib/store";
import type { Alert } from "@/types";

function AlertRow({ alert, action }: { alert: Alert; action?: ReactNode }) {
  const { state } = useLive();
  const now = useNow();
  const incident = state.incidents.get(alert.incident_id);
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3.5">
      <div className="min-w-0 flex-1">
        <Link to={`/app/incidents?focus=${alert.incident_id}`} className="truncate text-sm font-semibold hover:text-accent">
          {incident?.title ?? alert.incident_id}
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-mute">
          <DepartmentBadge department={alert.department} />
          <NeutralPill>Level {alert.level}</NeutralPill>
          <span>→ {alert.contact}</span>
          <span>· {alert.triggered_by.replace("_", " ")}</span>
          {alert.channel.endsWith(":failed") && <span className="text-danger">· delivery failed</span>}
        </div>
      </div>
      <span className="font-mono text-xs text-mute">{waitingLabel(alert.sent_at, now)} ago</span>
      {action}
    </li>
  );
}

function Group({ title, subtitle, icon, alerts, empty, action }: {
  title: string;
  subtitle: string;
  icon: ReactNode;
  alerts: Alert[];
  empty: string;
  action?: (alert: Alert) => ReactNode;
}) {
  return (
    <Card>
      <CardHeader
        title={title}
        subtitle={subtitle}
        action={<span className="flex items-center gap-2 text-sm text-mute">{icon}{alerts.length}</span>}
      />
      {alerts.length === 0 ? (
        <p className="px-5 py-8 text-center text-sm text-mute">{empty}</p>
      ) : (
        <ul className="divide-y divide-line">
          {alerts.map((a) => (
            <AlertRow key={a.id} alert={a} action={action?.(a)} />
          ))}
        </ul>
      )}
    </Card>
  );
}

export default function Alerts() {
  const { state } = useLive();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const all = useMemo(() => [...state.alerts.values()].sort((a, b) => b.sent_at - a.sent_at), [state.alerts]);
  const waiting = all.filter((a) => !a.acknowledged_at && !a.escalated_to);
  const exhausted = all.filter((a) => a.escalated_to === "exhausted");
  const history = all.filter((a) => a.acknowledged_at || (a.escalated_to && a.escalated_to !== "exhausted"));

  const acknowledge = async (alert: Alert) => {
    setBusy(alert.id);
    setError(null);
    try {
      await api(`/incidents/${alert.incident_id}/ack`, { method: "POST" });
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6 lg:p-8">
      <BlurFade>
        <p className="max-w-2xl text-sm text-mute">
          Alerts go to the first contact on the department's ladder. If nobody acknowledges within 90 seconds, the next
          contact is alerted automatically.
        </p>
      </BlurFade>
      {error && <p className="rounded-xl bg-danger/10 px-4 py-2.5 text-sm text-danger">{error}</p>}
      <BlurFade delay={0.05}>
        <Group
          title="Waiting for acknowledgement"
          subtitle="Escalates to the next contact after 90 s."
          icon={<BellRing className="size-4 text-accent" />}
          alerts={waiting}
          empty="Nothing waiting. All alerts are acknowledged."
          action={(a) => (
            <Button size="sm" disabled={busy === a.id} onClick={() => acknowledge(a)}>
              <Check className="size-3.5" /> Acknowledge
            </Button>
          )}
        />
      </BlurFade>
      <BlurFade delay={0.1}>
        <Group
          title="Nobody acknowledged"
          subtitle="Every contact on the ladder was alerted. Call the unit directly."
          icon={<CircleAlert className="size-4 text-danger" />}
          alerts={exhausted}
          empty="No exhausted ladders."
        />
      </BlurFade>
      <BlurFade delay={0.15}>
        <Group
          title="History"
          subtitle="Acknowledged, escalated or rerouted alerts."
          icon={exhausted.length || history.length ? <History className="size-4" /> : <BellOff className="size-4" />}
          alerts={history.slice(0, 50)}
          empty="No alert history yet."
        />
      </BlurFade>
    </div>
  );
}
