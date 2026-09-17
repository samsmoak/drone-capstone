import Link from "next/link";
import { PageHeader } from "@/components/ui/page-header";
import { ManualControl } from "@/components/manual-control";
import { SETUP } from "@/lib/routes";

export const metadata = { title: "Manual control" };

export default function ManualPage() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Manual control"
        description={
          <>
            Fly the drone by keyboard. This only works on the computer the radio is plugged
            into, with CropWatcher running —{" "}
            <Link href={SETUP} className="underline underline-offset-4">
              set it up
            </Link>{" "}
            first. The desktop app has the same controls and works in every browser setup.
          </>
        }
      />
      <ManualControl />
    </div>
  );
}
