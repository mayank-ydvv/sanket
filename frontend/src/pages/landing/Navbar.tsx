import { Link } from "react-router";
import { buttonClass } from "@/components/ui/Button";
import { Logo } from "@/components/ui/Logo";
import { LanguageToggle } from "@/components/ui/LanguageToggle";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import type { MessageKey } from "@/lib/messages";

const LINKS: { href: string; label: MessageKey }[] = [
  { href: "#how", label: "land.how" },
  { href: "#features", label: "land.features" },
  { href: "#results", label: "land.results" },
];

export function Navbar() {
  const { t } = useI18n();
  const { user } = useAuth();
  return (
    <header className="sticky top-0 z-50 border-b border-line/60 bg-bg/75 backdrop-blur-xl">
      <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <Logo />
        <div className="hidden items-center gap-8 text-sm text-ink-2 md:flex">
          {LINKS.map((link) => (
            <a key={link.href} href={link.href} className="transition hover:text-ink">
              {t(link.label)}
            </a>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <LanguageToggle className="hidden sm:inline-flex" />
          <ThemeToggle />
          {user ? (
            <Link to="/app" className={buttonClass("primary", "sm")}>
              {t("land.openRoom")}
            </Link>
          ) : (
            <>
              <Link to="/login" className={buttonClass("ghost", "sm", "hidden sm:inline-flex")}>
                {t("land.login")}
              </Link>
              <Link to="/signup" className={buttonClass("primary", "sm")}>
                {t("land.getStarted")}
              </Link>
            </>
          )}
        </div>
      </nav>
    </header>
  );
}
