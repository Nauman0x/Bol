"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ApiError } from "@/lib/api";
import {
  useApiKeys,
  useCreateApiKey,
  useCreateWebhook,
  useDeleteWebhook,
  useInviteTeamMember,
  useOrganization,
  useRevokeApiKey,
  useTeam,
  useUpdateOrganization,
  useWebhooks,
} from "@/lib/hooks";

function OrgSection() {
  const { data: org } = useOrganization();
  const updateOrg = useUpdateOrganization();
  const [name, setName] = useState("");

  useEffect(() => {
    if (org) setName(org.name);
  }, [org]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    try {
      await updateOrg.mutateAsync({ name });
      toast.success("Organization renamed");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to rename");
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Organization</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSave} className="flex items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="org-name">Name</Label>
            <Input
              id="org-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-64"
              required
            />
          </div>
          <Button type="submit">Save</Button>
        </form>
      </CardContent>
    </Card>
  );
}

function TeamSection() {
  const { data: team } = useTeam();
  const invite = useInviteTeamMember();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [tempPassword, setTempPassword] = useState<string | null>(null);

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    try {
      const result = await invite.mutateAsync({ email, name, role: "member" });
      setTempPassword(result.temp_password);
      setEmail("");
      setName("");
      toast.success("Member invited");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to invite");
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Team</CardTitle>
        <CardDescription>
          Invites generate a temporary password shown once — share it with the new member directly.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <form onSubmit={handleInvite} className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="invite-name">Name</Label>
            <Input
              id="invite-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-40"
              required
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="invite-email">Email</Label>
            <Input
              id="invite-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-56"
              required
            />
          </div>
          <Button type="submit">Invite</Button>
        </form>

        {tempPassword && (
          <div className="flex items-center justify-between rounded-md border border-amber-500/40 bg-amber-500/10 p-3">
            <div className="text-sm">
              Temporary password (shown once):{" "}
              <code className="rounded bg-background px-1.5 py-0.5 font-mono">{tempPassword}</code>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setTempPassword(null)}>
              Dismiss
            </Button>
          </div>
        )}

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Role</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {team?.map((member) => (
              <TableRow key={member.id}>
                <TableCell>{member.name}</TableCell>
                <TableCell>{member.email}</TableCell>
                <TableCell>
                  <Badge variant="outline" className="capitalize">
                    {member.role}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function ApiKeysSection() {
  const { data: keys } = useApiKeys();
  const createKey = useCreateApiKey();
  const revokeKey = useRevokeApiKey();
  const [keyName, setKeyName] = useState("");
  const [newKey, setNewKey] = useState<string | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    try {
      const result = await createKey.mutateAsync({ name: keyName });
      setNewKey(result.key);
      setKeyName("");
      toast.success("API key created");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to create key");
    }
  }

  async function handleRevoke(id: string) {
    if (!confirm("Revoke this API key? Any integration using it will stop working.")) return;
    try {
      await revokeKey.mutateAsync(id);
      toast.success("Key revoked");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to revoke key");
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">API keys</CardTitle>
        <CardDescription>
          Only the hash is stored — a new key is shown once and cannot be retrieved later.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <form onSubmit={handleCreate} className="flex items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="key-name">Key name</Label>
            <Input
              id="key-name"
              value={keyName}
              onChange={(e) => setKeyName(e.target.value)}
              className="w-56"
              placeholder="CI pipeline"
              required
            />
          </div>
          <Button type="submit">Create key</Button>
        </form>

        {newKey && (
          <div className="flex items-center justify-between rounded-md border border-amber-500/40 bg-amber-500/10 p-3">
            <div className="min-w-0 text-sm">
              Copy this now — it won&apos;t be shown again:{" "}
              <code className="rounded bg-background px-1.5 py-0.5 font-mono break-all">
                {newKey}
              </code>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setNewKey(null)}>
              Dismiss
            </Button>
          </div>
        )}

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Prefix</TableHead>
              <TableHead>Created</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {keys?.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-muted-foreground">
                  No API keys yet.
                </TableCell>
              </TableRow>
            )}
            {keys?.map((key) => (
              <TableRow key={key.id}>
                <TableCell>{key.name}</TableCell>
                <TableCell className="font-mono text-muted-foreground">{key.prefix}…</TableCell>
                <TableCell className="text-muted-foreground">
                  {new Date(key.created_at).toLocaleDateString()}
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-destructive hover:text-destructive"
                    onClick={() => handleRevoke(key.id)}
                  >
                    Revoke
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function WebhooksSection() {
  const { data: webhooks } = useWebhooks();
  const createWebhook = useCreateWebhook();
  const deleteWebhook = useDeleteWebhook();
  const [url, setUrl] = useState("");
  const [newSecret, setNewSecret] = useState<string | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    try {
      const result = await createWebhook.mutateAsync({ url });
      setNewSecret(result.secret);
      setUrl("");
      toast.success("Webhook created");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to create webhook");
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this webhook?")) return;
    try {
      await deleteWebhook.mutateAsync(id);
      toast.success("Webhook deleted");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to delete webhook");
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Webhooks</CardTitle>
        <CardDescription>
          Get an HMAC-signed <code>call.completed</code> POST whenever a call finishes — must be
          https. The signing secret is shown once, at creation.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <form onSubmit={handleCreate} className="flex items-end gap-3">
          <div className="flex flex-1 flex-col gap-1.5">
            <Label htmlFor="webhook-url">Endpoint URL</Label>
            <Input
              id="webhook-url"
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com/BOL/webhook"
              required
            />
          </div>
          <Button type="submit">Add webhook</Button>
        </form>

        {newSecret && (
          <div className="flex items-center justify-between rounded-md border border-amber-500/40 bg-amber-500/10 p-3">
            <div className="min-w-0 text-sm">
              Signing secret — copy this now, it won&apos;t be shown again:{" "}
              <code className="rounded bg-background px-1.5 py-0.5 font-mono break-all">
                {newSecret}
              </code>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setNewSecret(null)}>
              Dismiss
            </Button>
          </div>
        )}

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>URL</TableHead>
              <TableHead>Events</TableHead>
              <TableHead>Created</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {webhooks?.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-muted-foreground">
                  No webhooks configured.
                </TableCell>
              </TableRow>
            )}
            {webhooks?.map((webhook) => (
              <TableRow key={webhook.id}>
                <TableCell className="max-w-xs truncate font-mono text-sm">
                  {webhook.url}
                </TableCell>
                <TableCell>
                  {webhook.events.map((event) => (
                    <Badge key={event} variant="outline">
                      {event}
                    </Badge>
                  ))}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {new Date(webhook.created_at).toLocaleDateString()}
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-destructive hover:text-destructive"
                    onClick={() => handleDelete(webhook.id)}
                  >
                    Delete
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

export default function SettingsPage() {
  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">Organization, team, and API access.</p>
      </div>
      <OrgSection />
      <TeamSection />
      <ApiKeysSection />
      <WebhooksSection />
    </div>
  );
}
