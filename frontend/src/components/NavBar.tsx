"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useI18n } from "@/lib/i18n";

export function NavBar() {
  const pathname = usePathname();
  const { t } = useI18n();

  const links = [
    { href: "/", label: t("nav.overview") },
    { href: "/free-power", label: t("nav.freePower") },
    { href: "/health", label: t("nav.health") },
    { href: "/analytics", label: t("nav.analytics") },
    { href: "/history", label: t("nav.history") },
  ];

  return (
    <nav className="flex items-center gap-1">
      {links.map((link) => {
        const active = pathname === link.href;
        return (
          <Link
            key={link.href}
            href={link.href}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              active ? "bg-surface-2 text-text-primary" : "text-text-secondary hover:text-text-primary"
            }`}
          >
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}
