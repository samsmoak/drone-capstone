/**
 * PLAYBACK — its own page, in the sidebar (2026-10-11, Samuel: "make it have
 * its own page … put it at the sidebar … click there, see all the flights,
 * select one and play it back").
 *
 * The list is every flight that can be played back — this laptop's and
 * everyone's in Supabase, each once (AllFlights, GET /history/flights);
 * choosing one opens the player (FlightPlaybackView) on this page, and Back
 * returns to the list. A session's own flights also open the same player from
 * Sessions — one player, two ways in.
 */

import { useState } from "react";
import type { FlightListItem, Mode } from "@/lib/agent";
import { PageHeader } from "@/components/ui";
import { AllFlights, flightTitle } from "@/pages/sessions/AllFlights";
import { FlightPlaybackView } from "@/pages/sessions/Playback";

export function PlaybackPage({ refreshKey, mode }: { refreshKey: unknown; mode: Mode }) {
  const [playing, setPlaying] = useState<FlightListItem | null>(null);

  if (playing) {
    return <FlightPlaybackView flightId={playing.id} title={flightTitle(playing)}
                               backLabel="← All flights" onBack={() => setPlaying(null)} />;
  }

  return (
    <div className="grid gap-4">
      <PageHeader eyebrow="Operate" title="Playback">
        Every flight you can watch again: this computer's, and everyone's in Supabase. Choose one to
        play it back on the room map — where the drone was at every moment, against the plan it flew.
      </PageHeader>
      <AllFlights refreshKey={refreshKey} mode={mode} onPlay={setPlaying} />
    </div>
  );
}
