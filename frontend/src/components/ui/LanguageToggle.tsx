import { Languages } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export function LanguageToggle({ className }: { className?: string }) {
  const { lang, toggle, t } = useI18n();
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={t("lang.switchLabel")}
      title={t("lang.switchLabel")}
      lang={lang === "en" ? "ta" : "en"}
      className={cn(
        "inline-flex h-9 items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 text-sm font-medium text-ink-2 transition hover:border-line-strong hover:text-ink",
        className,
      )}
    >
      <Languages className="size-4" />
      <span className="sm:hidden">{t("lang.short")}</span>
      <span className="hidden sm:inline">{t("lang.switch")}</span>
    </button>
  );
}
