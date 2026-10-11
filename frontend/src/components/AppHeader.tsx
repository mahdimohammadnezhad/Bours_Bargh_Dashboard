"use client";

import { useI18n } from "@/lib/i18n";
import { NavBar } from "./NavBar";

export function AppHeader() {
  const { t, lang, setLang } = useI18n();

  return (
    <header className="sticky top-0 z-10 border-b border-border-hairline bg-surface-0/95 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <div>
          <div className="text-sm font-semibold tracking-tight text-text-primary">{t("app.title")}</div>
          <div className="text-xs text-text-muted">{t("app.subtitle")}</div>
        </div>
        <div className="flex items-center gap-3">
          <NavBar />
          <button
            type="button"
            onClick={() => setLang(lang === "fa" ? "en" : "fa")}
            className="rounded-md border border-border-hairline px-2.5 py-1.5 text-xs font-medium text-text-secondary transition-colors hover:text-text-primary"
          >
            {t("lang.toggle")}
          </button>
        </div>
      </div>
    </header>
  );
}
