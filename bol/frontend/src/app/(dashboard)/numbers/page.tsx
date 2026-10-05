"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ApiError } from "@/lib/api";
import {
  useAgents,
  useCreatePhoneNumber,
  useDeletePhoneNumber,
  usePhoneNumbers,
  useUpdatePhoneNumber,
} from "@/lib/hooks";
import type { PhoneNumberProvider } from "@/lib/types";

const NO_AGENT = "__none__";

const PROVIDER_LABELS: Record<PhoneNumberProvider, string> = {
  telnyx: "Telnyx",
  twilio: "Twilio",
};

export default function NumbersPage() {
  const { data: numbers, isLoading } = usePhoneNumbers();
  const { data: agents } = useAgents();
  const createNumber = useCreatePhoneNumber();
  const updateNumber = useUpdatePhoneNumber();
  const deleteNumber = useDeletePhoneNumber();

  const [e164, setE164] = useState("");
  const [provider, setProvider] = useState<PhoneNumberProvider>("telnyx");
  const [livekitTrunkId, setLivekitTrunkId] = useState("");
  const [adding, setAdding] = useState(false);

  const agentName = (id: string | null) =>
    id ? (agents?.find((a) => a.id === id)?.name ?? id.slice(0, 8)) : "— unassigned —";

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setAdding(true);
    try {
      await createNumber.mutateAsync({
        e164,
        provider,
        // A number can share the platform-wide default trunk (leave
        // blank) — only needed to route this specific number through its
        // own carrier, e.g. a Twilio number alongside Telnyx ones.
        livekit_trunk_id: livekitTrunkId || null,
      });
      toast.success("Number added");
      setE164("");
      setLivekitTrunkId("");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to add number");
    } finally {
      setAdding(false);
    }
  }

  async function handleAssign(id: string, agentId: string) {
    try {
      await updateNumber.mutateAsync({ id, inbound_agent_id: agentId === NO_AGENT ? null : agentId });
      toast.success("Updated");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to update");
    }
  }

  async function handleDelete(id: string, numberProvider: string) {
    const label = PROVIDER_LABELS[numberProvider as PhoneNumberProvider] ?? numberProvider;
    if (!confirm(`Remove this number from BOL? (This does not release it from ${label}.)`)) return;
    try {
      await deleteNumber.mutateAsync(id);
      toast.success("Number removed");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to remove number");
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Phone numbers</h1>
        <p className="text-muted-foreground">
          Only needed for real phone calls over the PSTN. Testing an agent from your browser
          mic (on the agent&apos;s page) works without any number. To take real calls: buy a
          number in your carrier&apos;s dashboard first (see docs/TELEPHONY_SETUP.md), then
          register it here and assign an agent to answer inbound calls.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Add a number</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleAdd} className="flex flex-wrap items-end gap-3">
            <Input
              placeholder="+15551234567"
              value={e164}
              onChange={(e) => setE164(e.target.value)}
              className="w-56"
              required
            />
            <Select
              value={provider}
              onValueChange={(v) => setProvider((v as PhoneNumberProvider | null) ?? "telnyx")}
            >
              <SelectTrigger className="w-32">
                <SelectValue>
                  {(value) => PROVIDER_LABELS[(value as PhoneNumberProvider) ?? "telnyx"]}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(PROVIDER_LABELS) as PhoneNumberProvider[]).map((p) => (
                  <SelectItem key={p} value={p}>
                    {PROVIDER_LABELS[p]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              placeholder="LiveKit trunk ID (optional)"
              value={livekitTrunkId}
              onChange={(e) => setLivekitTrunkId(e.target.value)}
              className="w-56"
            />
            <Button type="submit" disabled={adding}>
              {adding ? "Adding…" : "Add number"}
            </Button>
          </form>
          <p className="mt-2 text-sm text-muted-foreground">
            Leave the trunk ID blank to use the platform-wide default (
            <code>LIVEKIT_SIP_OUTBOUND_TRUNK_ID</code>). Set one to route this specific number
            through its own carrier trunk — e.g. a Twilio number alongside Telnyx ones.
          </p>
        </CardContent>
      </Card>

      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Number</TableHead>
              <TableHead>Provider</TableHead>
              <TableHead>Inbound agent</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-muted-foreground">
                  Loading…
                </TableCell>
              </TableRow>
            )}
            {numbers?.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-muted-foreground">
                  No numbers yet.
                </TableCell>
              </TableRow>
            )}
            {numbers?.map((number) => (
              <TableRow key={number.id}>
                <TableCell className="font-mono">{number.e164}</TableCell>
                <TableCell className="capitalize">{number.provider}</TableCell>
                <TableCell>
                  <Select
                    value={number.inbound_agent_id ?? NO_AGENT}
                    onValueChange={(v) => handleAssign(number.id, v ?? NO_AGENT)}
                  >
                    <SelectTrigger className="w-48">
                      <SelectValue>
                        {(value) =>
                          agentName(value === NO_AGENT ? null : (value as string | null))
                        }
                      </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NO_AGENT}>— unassigned —</SelectItem>
                      {agents?.map((a) => (
                        <SelectItem key={a.id} value={a.id}>
                          {a.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-destructive hover:text-destructive"
                    onClick={() => handleDelete(number.id, number.provider)}
                  >
                    Remove
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}
