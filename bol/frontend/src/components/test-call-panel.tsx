"use client";

import { Room, RoomEvent, Track } from "livekit-client";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError } from "@/lib/api";
import { useCreateTestSession, useHealthConfig } from "@/lib/hooks";
import type { TtsProviderId } from "@/lib/types";

type CallState = "idle" | "connecting" | "connected" | "waiting_for_agent" | "ended";

// How long to wait after the browser joins the room before assuming the
// agent worker isn't going to show up. The API only creates the room +
// dispatch (routers/agents.py) — a separate worker process has to actually
// join and run the pipeline, and nothing in the join flow itself proves
// that happened.
const AGENT_JOIN_TIMEOUT_MS = 8000;

// agent.config.tts_provider is nullable ("use the platform-wide default" —
// see backend/app/schemas/agent.py) and there's no endpoint exposing that
// platform default today, so a null falls back to "groq" (config.py's
// TTS_PROVIDER default) here. Good enough to flag the common case (an
// agent explicitly set to chatterbox with no server configured); a platform
// default of something other than groq is a rarer misconfiguration this
// won't catch.
export function TestCallPanel({
  agentId,
  ttsProvider,
}: {
  agentId: string;
  ttsProvider?: TtsProviderId | null;
}) {
  const [state, setState] = useState<CallState>("idle");
  const roomRef = useRef<Room | null>(null);
  const audioContainerRef = useRef<HTMLDivElement>(null);
  const joinTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const createSession = useCreateTestSession();
  const { data: healthConfig } = useHealthConfig();

  function clearJoinTimeout() {
    if (joinTimeoutRef.current !== null) {
      clearTimeout(joinTimeoutRef.current);
      joinTimeoutRef.current = null;
    }
  }

  async function startCall() {
    setState("connecting");
    try {
      const session = await createSession.mutateAsync(agentId);
      const room = new Room();
      roomRef.current = room;

      room.on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind === Track.Kind.Audio) {
          const el = track.attach();
          audioContainerRef.current?.appendChild(el);
        }
      });
      room.on(RoomEvent.Disconnected, () => {
        clearJoinTimeout();
        setState("ended");
      });
      // A remote participant here is the agent worker joining — until this
      // fires, "connected" would just mean the browser talked to LiveKit,
      // not that anyone is on the other end to hear or respond.
      room.on(RoomEvent.ParticipantConnected, () => {
        clearJoinTimeout();
        setState("connected");
      });
      // Browsers can block autoplay even for a connect triggered by a click
      // (most reliably on tracks that arrive slightly later); this recovers
      // from that instead of leaving the call silently unplayable.
      room.on(RoomEvent.AudioPlaybackStatusChanged, () => {
        if (!room.canPlaybackAudio) {
          room.startAudio().catch(() => {
            toast.error("Browser blocked audio playback — click anywhere on the page and try again.");
          });
        }
      });

      await room.connect(session.livekit_url, session.token);
      await room.localParticipant.setMicrophoneEnabled(true);

      if (room.remoteParticipants.size > 0) {
        setState("connected");
      } else {
        setState("waiting_for_agent");
        joinTimeoutRef.current = setTimeout(() => {
          // Still no agent participant — most likely the worker process
          // (`make worker`) isn't running, crashed on this job, or is
          // pointed at a different LiveKit project than the API.
          if (roomRef.current === room && room.remoteParticipants.size === 0) {
            toast.error("No agent joined the call — is the worker (`make worker`) running?");
          }
        }, AGENT_JOIN_TIMEOUT_MS);
      }
    } catch (err) {
      // The backend returns a specific "X is not configured" message for
      // known misconfiguration (missing LiveKit creds) — surface it as-is
      // instead of a generic failure toast.
      toast.error(err instanceof ApiError ? err.message : "Could not start test call");
      setState("idle");
    }
  }

  async function endCall() {
    clearJoinTimeout();
    await roomRef.current?.disconnect();
    roomRef.current = null;
    setState("ended");
  }

  useEffect(() => {
    return () => {
      clearJoinTimeout();
      roomRef.current?.disconnect();
    };
  }, []);

  const missingConfig: string[] = [];
  if (healthConfig && !healthConfig.livekit) missingConfig.push("LiveKit (LIVEKIT_URL / API key / secret)");
  if (healthConfig && !healthConfig.groq) missingConfig.push("Groq (GROQ_API_KEY)");
  if (healthConfig && ttsProvider === "chatterbox" && !healthConfig.chatterbox) {
    missingConfig.push("Chatterbox (CHATTERBOX_BASE_URL)");
  }
  if (healthConfig && ttsProvider === "fish" && !healthConfig.fish) {
    missingConfig.push("Fish Audio (FISH_API_KEY)");
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Test call</CardTitle>
        <CardDescription>
          Talk to this agent from your browser mic — free, no phone number and no carrier needed.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div ref={audioContainerRef} className="hidden" />

        {missingConfig.length > 0 && (
          <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm">
            <p className="font-medium text-destructive">Not configured yet:</p>
            <ul className="mt-1 list-inside list-disc text-muted-foreground">
              {missingConfig.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            <p className="mt-1 text-muted-foreground">Add these to the backend&apos;s <code>.env</code>.</p>
          </div>
        )}

        {healthConfig && healthConfig.livekit && healthConfig.groq && (
          <p className="text-xs text-muted-foreground">
            Also make sure the agent worker is running (<code>make worker</code>) — the API only
            creates the room; the worker is what actually joins and talks.
          </p>
        )}

        {state === "idle" || state === "ended" ? (
          <Button type="button" onClick={startCall}>
            {state === "ended" ? "Call again" : "Start test call"}
          </Button>
        ) : state === "connecting" ? (
          <Button type="button" disabled>
            Connecting…
          </Button>
        ) : state === "waiting_for_agent" ? (
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-2 text-sm text-amber-600">
              <span className="size-2 animate-pulse rounded-full bg-amber-500" />
              Waiting for the agent to join…
            </span>
            <Button type="button" variant="destructive" size="sm" onClick={endCall}>
              End call
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-2 text-sm text-emerald-600">
              <span className="size-2 animate-pulse rounded-full bg-emerald-500" />
              Connected — speak into your mic
            </span>
            <Button type="button" variant="destructive" size="sm" onClick={endCall}>
              End call
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
