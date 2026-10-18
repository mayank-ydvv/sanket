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
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useTheme } from "@/lib/theme";

function Field({
  label,
  type = "text",
  value,
  onChange,
  autoComplete,
  hint,
}: {
  label: string;
  type?: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete: string;
  hint?: string;
}) {
  const [visible, setVisible] = useState(false);
  const isPassword = type === "password";
  const id = label.toLowerCase().replace(/\s+/g, "-");
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
            aria-label={visible ? "Hide password" : "Show password"}
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
      setError(exc instanceof ApiError ? exc.message : "Something went wrong. Is the API running?");
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
          <HyperText as="p" startOnView animateOnHover={false} className="font-display text-sm font-bold tracking-[0.4em] text-accent">
            SIGNAL IN THE NOISE
          </HyperText>
          <p className="mt-3 max-w-md font-display text-3xl font-bold leading-tight tracking-tight">
            Every call heard. Every incident ranked. Humans decide.
          </p>
        </div>
        <p className="relative text-sm text-mute">Synthetic demo data only. Never enter real caller details.</p>
      </aside>

      <main className="flex flex-col px-4 py-6 sm:px-8">
        <div className="flex items-center justify-between">
          <Logo className="lg:invisible" />
          <ThemeToggle />
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
                    {isSignup ? "Create your account" : "Welcome back"}
                  </h1>
                  <p className="mt-1.5 text-sm text-mute">
                    {isSignup ? "Dispatchers sign up to use the control room." : "Log in to the Sanket control room."}
                  </p>
                </div>
                {isSignup && <Field label="Full name" value={name} onChange={setName} autoComplete="name" />}
                <Field label="Email" type="email" value={email} onChange={setEmail} autoComplete="email" />
                <Field
                  label="Password"
                  type="password"
                  value={password}
                  onChange={setPassword}
                  autoComplete={isSignup ? "new-password" : "current-password"}
                  hint={isSignup ? "At least 8 characters." : undefined}
                />
                {error && (
                  <p role="alert" className="rounded-xl border border-danger/30 bg-danger/10 px-3.5 py-2.5 text-sm text-danger">
                    {error}
                  </p>
                )}
                <Button type="submit" size="lg" className="w-full" disabled={busy}>
                  {busy ? <LoaderCircle className="size-4 animate-spin" /> : <ArrowRight className="size-4" />}
                  {isSignup ? "Create account" : "Log in"}
                </Button>
                <p className="text-center text-sm text-mute">
                  {isSignup ? "Already have an account? " : "New here? "}
                  <Link to={isSignup ? "/login" : "/signup"} state={location.state} className="font-medium text-accent hover:underline">
                    {isSignup ? "Log in" : "Create an account"}
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
