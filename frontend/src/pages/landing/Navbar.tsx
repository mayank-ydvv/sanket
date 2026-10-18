import { Link } from "react-router";
import { buttonClass } from "@/components/ui/Button";
import { Logo } from "@/components/ui/Logo";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { useAuth } from "@/lib/auth";

const LINKS = [
  { href: "#how", label: "How it works" },
  { href: "#features", label: "Features" },
  { href: "#results", label: "Results" },
];

export function Navbar() {
  const { user } = useAuth();
  return (
    <header className="sticky top-0 z-50 border-b border-line/60 bg-bg/75 backdrop-blur-xl">
      <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <Logo />
        <div className="hidden items-center gap-8 text-sm text-ink-2 md:flex">
          {LINKS.map((link) => (
            <a key={link.href} href={link.href} className="transition hover:text-ink">
              {link.label}
            </a>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          {user ? (
            <Link to="/app" className={buttonClass("primary", "sm")}>
              Open control room
            </Link>
          ) : (
            <>
              <Link to="/login" className={buttonClass("ghost", "sm", "hidden sm:inline-flex")}>
                Log in
              </Link>
              <Link to="/signup" className={buttonClass("primary", "sm")}>
                Get started
              </Link>
            </>
          )}
        </div>
      </nav>
    </header>
  );
}
