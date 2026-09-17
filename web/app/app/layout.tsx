import { OperatorShell } from "@/components/operator/OperatorShell";

export default function OperatorLayout({ children }: { children: React.ReactNode }) {
  return <OperatorShell>{children}</OperatorShell>;
}
