"use client";

import { useEffect, useRef, useState } from "react";
import { Room, RoomEvent, Track, RemoteTrack, RemoteParticipant } from "livekit-client";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import type { TestSessionResponse } from "@/lib/types";
import { toast } from "sonner";

type CallState = "idle" | "connecting" | "connected" | "ended";

export function TestCallDialog({
  agentId,
  open,
  onOpenChange,
}: {
  agentId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [state, setState] = useState<CallState>("idle");
  const [callId, setCallId] = useState<string | null>(null);
  const roomRef = useRef<Room | null>(null);
  const audioContainerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) {
      disconnect();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  async function startCall() {
    setState("connecting");
    try {
      const resp = await api.post<TestSessionResponse>(`/agents/${agentId}/test-session`);
      const { livekit_url, token, call_id } = resp.data;
      setCallId(call_id);

      const room = new Room();
      roomRef.current = room;

      room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack, _pub, _participant: RemoteParticipant) => {
        if (track.kind === Track.Kind.Audio) {
          const el = track.attach();
          audioContainerRef.current?.appendChild(el);
        }
      });

      room.on(RoomEvent.Disconnected, () => {
        setState("ended");
      });

      await room.connect(livekit_url, token);
      await room.localParticipant.setMicrophoneEnabled(true);
      setState("connected");
    } catch {
      toast.error("Could not start test call");
      setState("idle");
    }
  }

  function disconnect() {
    roomRef.current?.disconnect();
    roomRef.current = null;
    if (audioContainerRef.current) audioContainerRef.current.innerHTML = "";
    setState("idle");
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) disconnect();
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Test call</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col items-center gap-4 py-6">
          <div ref={audioContainerRef} />
          {state === "idle" && (
            <Button onClick={startCall} className="w-full">
              Start test call (uses your mic)
            </Button>
          )}
          {state === "connecting" && <p className="text-muted-foreground">Connecting...</p>}
          {state === "connected" && (
            <>
              <p className="text-sm text-muted-foreground">
                Connected. Speak into your mic to talk to the agent.
              </p>
              <Button variant="destructive" onClick={disconnect} className="w-full">
                End call
              </Button>
            </>
          )}
          {state === "ended" && (
            <div className="flex flex-col items-center gap-2">
              <p className="text-muted-foreground">Call ended.</p>
              {callId && (
                <a href={`/calls/${callId}`} className="text-sm underline">
                  View transcript
                </a>
              )}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
