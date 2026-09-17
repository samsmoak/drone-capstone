"use client";

import dynamic from "next/dynamic";

// BlockNote must never render on the server — load it client-only.
export const BlockEditorClient = dynamic(() => import("./BlockEditor"), {
  ssr: false,
  loading: () => <div className="min-h-[300px] animate-pulse rounded-xl border border-[var(--border)] bg-[var(--surface-2)]" />,
});
