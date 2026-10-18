import { BellOff, BellRing, Check, CircleAlert, History } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";
import { Link } from "react-router";
import { BlurFade } from "@/components/magicui/blur-fade";
import { DepartmentBadge, NeutralPill } from "@/components/ui/badges";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { useNow } from "@/hooks/useNow";
import { ApiError, api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useLive } from "@/lib/live";
import { incidentTitle, waitingLabel } from "@/lib/store";
import type { Alert } from "@/types";

function AlertRow({ alert, action }: { alert: Alert; action?: ReactNode }) {
  const { t } = useI18n();
  const { state } = useLive();
  const now = useNow();
  const incident = state.incidents.get(alert.incident_id);
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3.5">
      <div className="min-w-0 flex-1">
        <Link to={`/app/incidents?focus=${alert.incident_id}`} className="truncate text-sm font-semibold hover:text-accent">
          {incident ? incidentTitle(incident, t) : alert.incident_id}
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-mute">
          <DepartmentBadge department={alert.department} />
          <NeutralPill>{t("alerts.level", { n: alert.level })}</NeutralPill>
          <span>→ {alert.contact}</span>
          <span>· {alert.triggered_by.replace("_", " ")}</span>
          {alert.channel.endsWith(":failed") && <span className="text-danger">· {t("alerts.failed")}</span>}
        </div>
      </div>
      <span className="font-mono text-xs text-mute">{t("alerts.ago", { t: waitingLabel(alert.sent_at, now) })}</span>
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
  const { t } = useI18n();
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
        <p className="max-w-2xl text-sm text-mute">{t("alerts.intro")}</p>
      </BlurFade>
      {error && <p className="rounded-xl bg-danger/10 px-4 py-2.5 text-sm text-danger">{error}</p>}
      <BlurFade delay={0.05}>
        <Group
          title={t("alerts.waiting")}
          subtitle={t("alerts.waitingSub")}
          icon={<BellRing className="size-4 text-accent" />}
          alerts={waiting}
          empty={t("alerts.waitingEmpty")}
          action={(a) => (
            <Button size="sm" disabled={busy === a.id} onClick={() => acknowledge(a)}>
              <Check className="size-3.5" /> {t("detail.ack")}
            </Button>
          )}
        />
      </BlurFade>
      <BlurFade delay={0.1}>
        <Group
          title={t("alerts.exhausted")}
          subtitle={t("alerts.exhaustedSub")}
          icon={<CircleAlert className="size-4 text-danger" />}
          alerts={exhausted}
          empty={t("alerts.exhaustedEmpty")}
        />
      </BlurFade>
      <BlurFade delay={0.15}>
        <Group
          title={t("alerts.history")}
          subtitle={t("alerts.historySub")}
          icon={exhausted.length || history.length ? <History className="size-4" /> : <BellOff className="size-4" />}
          alerts={history.slice(0, 50)}
          empty={t("alerts.historyEmpty")}
        />
      </BlurFade>
    </div>
  );
}
