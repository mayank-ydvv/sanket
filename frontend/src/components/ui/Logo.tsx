import { Link } from "react-router";
import { cn } from "@/lib/utils";

/** Signal-wave mark + wordmark. */
export function Logo({ className, to = "/" }: { className?: string; to?: string }) {
  return (
    <Link to={to} className={cn("flex items-center gap-2.5 font-display text-lg font-bold tracking-tight", className)}>
      <span className="grid size-8 place-items-center rounded-lg bg-accent text-white shadow-sm shadow-accent/30">
        <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M3 13h4l2.5-6 4 11 2.5-5H21" />
        </svg>
      </span>
      <span>
        Sanket<span className="text-accent">.</span>
      </span>
    </Link>
  );
}
