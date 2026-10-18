import { ArrowRight, Eye, EyeOff, LoaderCircle } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router";
import { BlurFade } from "@/components/magicui/blur-fade";
import { FlickeringGrid } from "@/components/magicui/flickering-grid";
import { HyperText } from "@/components/magicui/hyper-text";
import { MagicCard } from "@/components/magicui/magic-card";
import { Ripple } from "@/components/magicui/ripple";
import { Button } from "@/components/ui/Button";
import { Logo } from "@/components/ui/Logo";
import { LanguageToggle } from "@/components/ui/LanguageToggle";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { type Translate, useI18n } from "@/lib/i18n";
import type { MessageKey } from "@/lib/messages";
import { useTheme } from "@/lib/theme";

/** Server messages the UI knows how to say in the chosen language. */
const API_ERRORS: Record<string, MessageKey> = {
  "wrong email or password": "auth.err.wrong",
  "too many attempts, try again in a few minutes": "auth.err.throttled",
  "an account with this email already exists": "auth.err.exists",
};

function errorText(exc: unknown, t: Translate): string {
  if (!(exc instanceof ApiError)) return t("auth.error");
  const known = API_ERRORS[exc.message];
  return known ? t(known) : exc.message;
}

function Field({
  id,
  label,
  type = "text",
  value,
  onChange,
  autoComplete,
  hint,
}: {
  id: string;
  label: string;
  type?: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete: string;
  hint?: string;
}) {
  const { t } = useI18n();
  const [visible, setVisible] = useState(false);
  const isPassword = type === "password";
  return (
    <label htmlFor={id} className="block">
      <span className="text-sm font-medium text-ink-2">{label}</span>
      <span className="relative mt-1.5 block">
        <input
          id={id}
          type={isPassword && visible ? "text" : type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoComplete={autoComplete}
          required
          className="h-11 w-full rounded-xl border border-line bg-bg px-3.5 text-[15px] text-ink outline-none transition placeholder:text-mute focus:border-accent focus:ring-4 focus:ring-accent/15"
        />
        {isPassword && (
          <button
            type="button"
            onClick={() => setVisible((v) => !v)}
            aria-label={visible ? t("auth.hidePassword") : t("auth.showPassword")}
            className="absolute inset-y-0 right-0 grid w-11 place-items-center text-mute hover:text-ink"
          >
            {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          </button>
        )}
      </span>
      {hint && <span className="mt-1 block text-xs text-mute">{hint}</span>}
    </label>
  );
}

export default function AuthPage({ mode }: { mode: "login" | "signup" }) {
  const { t, lang } = useI18n();
  const { user, loading, login, signup } = useAuth();
  const { resolved } = useTheme();
  const navigate = useNavigate();
  const location = useLocation();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const next = (location.state as { from?: string } | null)?.from ?? "/app";

  if (!loading && user) return <Navigate to={next} replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "signup") await signup(name, email, password);
      else await login(email, password);
      navigate(next, { replace: true });
    } catch (exc) {
      setError(errorText(exc, t));
    } finally {
      setBusy(false);
    }
  };

  const isSignup = mode === "signup";
  return (
    <div className="grid min-h-full lg:grid-cols-2">
      <aside className="relative hidden overflow-hidden border-r border-line bg-surface lg:flex lg:flex-col lg:justify-between lg:p-12">
        <FlickeringGrid
          className="absolute inset-0 [mask-image:radial-gradient(ellipse_at_center,white_10%,transparent_75%)]"
          squareSize={4}
          gridGap={6}
          color="rgb(234,88,12)"
          maxOpacity={resolved === "dark" ? 0.2 : 0.14}
          flickerChance={0.1}
        />
        <Logo className="relative" />
        <div className="relative">
          <div className="relative mx-auto mb-10 grid size-56 place-items-center">
            <Ripple mainCircleSize={120} numCircles={5} className="-inset-24 mask-[radial-gradient(circle,white_35%,transparent_70%)]" />
            <span className="z-10 grid size-20 place-items-center rounded-2xl bg-accent text-white shadow-lg shadow-accent/30">
              <svg viewBox="0 0 24 24" className="size-9" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d="M3 13h4l2.5-6 4 11 2.5-5H21" />
              </svg>
            </span>
          </div>
          {lang === "en" ? (
            <HyperText as="p" startOnView animateOnHover={false} className="font-display text-sm font-bold tracking-[0.4em] text-accent">
              {t("auth.tagline")}
            </HyperText>
          ) : (
            <p className="py-2 font-display text-sm font-bold text-accent">{t("auth.tagline")}</p>
          )}
          <p className="mt-3 max-w-md font-display text-3xl font-bold leading-tight tracking-tight">{t("auth.pitch")}</p>
        </div>
        <p className="relative text-sm text-mute">{t("auth.synthetic")}</p>
      </aside>

      <main className="flex flex-col px-4 py-6 sm:px-8">
        <div className="flex items-center justify-between">
          <Logo className="lg:invisible" />
          <div className="flex items-center gap-2">
            <LanguageToggle />
            <ThemeToggle />
          </div>
        </div>
        <div className="flex flex-1 items-center justify-center py-10">
          <BlurFade className="w-full max-w-md">
            <MagicCard
              className="rounded-2xl"
              gradientColor={resolved === "dark" ? "#1c263f" : "#fff1e8"}
              gradientFrom="#ea580c"
              gradientTo="#0ea5e9"
            >
              <form onSubmit={submit} className="space-y-5 p-7 sm:p-8">
                <div>
                  <h1 className="font-display text-2xl font-bold tracking-tight">
                    {isSignup ? t("auth.signupTitle") : t("auth.loginTitle")}
                  </h1>
                  <p className="mt-1.5 text-sm text-mute">
                    {isSignup ? t("auth.signupSub") : t("auth.loginSub")}
                  </p>
                </div>
                {isSignup && <Field id="name" label={t("auth.name")} value={name} onChange={setName} autoComplete="name" />}
                <Field id="email" label={t("auth.email")} type="email" value={email} onChange={setEmail} autoComplete="email" />
                <Field
                  id="password"
                  label={t("auth.password")}
                  type="password"
                  value={password}
                  onChange={setPassword}
                  autoComplete={isSignup ? "new-password" : "current-password"}
                  hint={isSignup ? t("auth.passwordHint") : undefined}
                />
                {error && (
                  <p role="alert" className="rounded-xl border border-danger/30 bg-danger/10 px-3.5 py-2.5 text-sm text-danger">
                    {error}
                  </p>
                )}
                <Button type="submit" size="lg" className="w-full" disabled={busy}>
                  {busy ? <LoaderCircle className="size-4 animate-spin" /> : <ArrowRight className="size-4" />}
                  {isSignup ? t("auth.create") : t("auth.login")}
                </Button>
                <p className="text-center text-sm text-mute">
                  {isSignup ? t("auth.haveAccount") : t("auth.newHere")}
                  <Link to={isSignup ? "/login" : "/signup"} state={location.state} className="font-medium text-accent hover:underline">
                    {isSignup ? t("auth.login") : t("auth.createLink")}
                  </Link>
                </p>
              </form>
            </MagicCard>
          </BlurFade>
        </div>
      </main>
    </div>
  );
}
