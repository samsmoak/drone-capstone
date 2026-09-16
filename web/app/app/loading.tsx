import { LoadingState } from "@/components/ui/states";

/** The loading state for every operator page that does not define its own. */
export default function OperatorLoading() {
  return <LoadingState label="Loading" rows={5} />;
}
