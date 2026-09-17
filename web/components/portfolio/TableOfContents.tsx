"use client";

import { useCallback, useEffect, useState } from "react";

type Section = { id: string; title: string; level?: number };

/** Scroll-spy contents for a project write-up. Copied from ../doctor-portfolio. */
export function TableOfContents({ sections }: { sections: Section[] }) {
  const [activeId, setActiveId] = useState(sections[0]?.id || "");

  const updateActiveSection = useCallback(() => {
    const triggerLine = 140;
    let current = sections[0]?.id || "";
    for (const { id } of sections) {
      const el = document.getElementById(id);
      if (el && el.getBoundingClientRect().top <= triggerLine) current = id;
    }
    setActiveId(current);
  }, [sections]);

  useEffect(() => {
    let ticking = false;
    const onScroll = () => {
      if (!ticking) {
        requestAnimationFrame(() => {
          updateActiveSection();
          ticking = false;
        });
        ticking = true;
      }
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    // eslint-disable-next-line react-hooks/set-state-in-effect
    updateActiveSection();
    return () => window.removeEventListener("scroll", onScroll);
  }, [updateActiveSection]);

  const scrollToSection = (id: string) => {
    const element = document.getElementById(id);
    if (element) {
      const top = element.getBoundingClientRect().top + window.scrollY - 100;
      window.scrollTo({ top, behavior: "smooth" });
    }
  };

  if (sections.length === 0) return null;

  return (
    <nav
      aria-label="On this page"
      className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5 lg:sticky lg:top-24"
    >
      <h2 className="eyebrow mb-4">On this page</h2>
      <ul className="space-y-0.5 text-sm">
        {sections.map((section) => {
          const active = activeId === section.id;
          return (
            <li key={section.id}>
              <button
                type="button"
                onClick={() => scrollToSection(section.id)}
                style={{ paddingLeft: section.level === 3 ? "1.5rem" : undefined }}
                aria-current={active ? "location" : undefined}
                className={`relative block w-full rounded-lg px-3.5 py-2 text-left transition-colors ${
                  active
                    ? "bg-[var(--surface-2)] font-semibold text-[var(--heading)]"
                    : "text-[var(--muted)] hover:bg-[var(--surface-2)] hover:text-[var(--foreground)]"
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`absolute left-0 top-1/2 w-0.5 -translate-y-1/2 rounded-full bg-[var(--primary)] transition-all ${
                    active ? "h-5 opacity-100" : "h-0 opacity-0"
                  }`}
                />
                {section.title}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
