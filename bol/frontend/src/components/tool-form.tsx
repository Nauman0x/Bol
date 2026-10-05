"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import { useCreateTool, useTestTool, useUpdateTool } from "@/lib/hooks";
import {
  DYNAMIC_VARS,
  type PreToolSpeech,
  type ResponseExtract,
  type Tool,
  type ToolHeader,
  type ToolInput,
  type ToolParam,
  type ToolTestResult,
} from "@/lib/types";

interface ToolFormProps {
  mode: "create" | "edit";
  tool?: Tool;
}

const DEFAULT_PARAM: ToolParam = {
  name: "",
  location: "query",
  type: "string",
  description: "",
  required: false,
  source: "llm",
  value: "",
};

const DEFAULT_HEADER: ToolHeader = {
  name: "",
  value_type: "literal",
  value: "",
  secret_ref: null,
};

const DEFAULT_EXTRACT: ResponseExtract = { name: "", path: "", description: "" };

function newSecretRef(): string {
  return `secret_${Math.random().toString(36).slice(2, 10)}`;
}

function ParamRow({
  param,
  onChange,
  onRemove,
}: {
  param: ToolParam;
  onChange: (patch: Partial<ToolParam>) => void;
  onRemove: () => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-2 rounded-md border p-2 sm:grid-cols-6 sm:items-center">
      <Input
        placeholder="name"
        value={param.name}
        onChange={(e) => onChange({ name: e.target.value })}
      />
      <Select value={param.location} onValueChange={(v) => onChange({ location: v as ToolParam["location"] })}>
        <SelectTrigger>
          <SelectValue>{(v) => String(v ?? "query")}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="query">query</SelectItem>
          <SelectItem value="path">path</SelectItem>
          <SelectItem value="body">body</SelectItem>
          <SelectItem value="header">header</SelectItem>
        </SelectContent>
      </Select>
      <Select value={param.type} onValueChange={(v) => onChange({ type: v as ToolParam["type"] })}>
        <SelectTrigger>
          <SelectValue>{(v) => String(v ?? "string")}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="string">string</SelectItem>
          <SelectItem value="number">number</SelectItem>
          <SelectItem value="integer">integer</SelectItem>
          <SelectItem value="boolean">boolean</SelectItem>
          <SelectItem value="object">object</SelectItem>
          <SelectItem value="array">array</SelectItem>
        </SelectContent>
      </Select>
      <Select
        value={param.source}
        onValueChange={(v) =>
          onChange({ source: v as ToolParam["source"], value: v === "llm" ? "" : param.value })
        }
      >
        <SelectTrigger>
          <SelectValue>{(v) => String(v ?? "llm")}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="llm">from caller / LLM</SelectItem>
          <SelectItem value="constant">constant</SelectItem>
          <SelectItem value="dynamic">dynamic</SelectItem>
        </SelectContent>
      </Select>
      {param.source === "constant" && (
        <Input
          placeholder="value"
          value={param.value}
          onChange={(e) => onChange({ value: e.target.value })}
        />
      )}
      {param.source === "dynamic" && (
        <Select value={param.value} onValueChange={(v) => onChange({ value: v ?? "" })}>
          <SelectTrigger>
            <SelectValue>{(v) => String(v || "choose…")}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            {DYNAMIC_VARS.map((v) => (
              <SelectItem key={v} value={v}>
                {v}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
      {param.source === "llm" && (
        <Input
          placeholder="description for the LLM"
          value={param.description}
          onChange={(e) => onChange({ description: e.target.value })}
        />
      )}
      <div className="flex items-center justify-between gap-2 sm:col-span-1">
        {param.source === "llm" && (
          <div className="flex items-center gap-1.5">
            <Switch
              checked={param.required}
              onCheckedChange={(v) => onChange({ required: v })}
            />
            <Label className="text-xs text-muted-foreground">required</Label>
          </div>
        )}
        <Button type="button" variant="ghost" size="sm" className="text-destructive" onClick={onRemove}>
          Remove
        </Button>
      </div>
    </div>
  );
}

function HeaderRow({
  header,
  onChange,
  onRemove,
}: {
  header: ToolHeader;
  onChange: (patch: Partial<ToolHeader>) => void;
  onRemove: () => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-2 rounded-md border p-2 sm:grid-cols-4 sm:items-center">
      <Input
        placeholder="header name (e.g. Authorization)"
        value={header.name}
        onChange={(e) => onChange({ name: e.target.value })}
      />
      <Select
        value={header.value_type}
        onValueChange={(v) =>
          onChange({
            value_type: v as "literal" | "secret",
            secret_ref: v === "secret" ? header.secret_ref ?? newSecretRef() : null,
          })
        }
      >
        <SelectTrigger>
          <SelectValue>{(v) => String(v ?? "literal")}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="literal">literal</SelectItem>
          <SelectItem value="secret">secret</SelectItem>
        </SelectContent>
      </Select>
      {header.value_type === "literal" ? (
        <Input
          placeholder="value"
          className="sm:col-span-1"
          value={header.value}
          onChange={(e) => onChange({ value: e.target.value })}
        />
      ) : (
        <Input
          placeholder="new secret value — leave blank to keep the stored one"
          className="sm:col-span-1"
          type="password"
          value={header.value}
          onChange={(e) => onChange({ value: e.target.value })}
        />
      )}
      <Button type="button" variant="ghost" size="sm" className="text-destructive justify-self-start" onClick={onRemove}>
        Remove
      </Button>
    </div>
  );
}

function ExtractRow({
  rule,
  onChange,
  onRemove,
}: {
  rule: ResponseExtract;
  onChange: (patch: Partial<ResponseExtract>) => void;
  onRemove: () => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-2 rounded-md border p-2 sm:grid-cols-4 sm:items-center">
      <Input placeholder="name" value={rule.name} onChange={(e) => onChange({ name: e.target.value })} />
      <Input
        placeholder="path (e.g. data.booking.id)"
        value={rule.path}
        onChange={(e) => onChange({ path: e.target.value })}
      />
      <Input
        placeholder="description (optional)"
        value={rule.description}
        onChange={(e) => onChange({ description: e.target.value })}
      />
      <Button type="button" variant="ghost" size="sm" className="text-destructive justify-self-start" onClick={onRemove}>
        Remove
      </Button>
    </div>
  );
}

export function ToolForm({ mode, tool }: ToolFormProps) {
  const router = useRouter();
  const createTool = useCreateTool();
  const updateTool = useUpdateTool(tool?.id ?? "");
  const testTool = useTestTool(tool?.id ?? "");

  const [name, setName] = useState(tool?.name ?? "");
  const [description, setDescription] = useState(tool?.description ?? "");
  const [isActive, setIsActive] = useState(tool?.is_active ?? true);
  const [url, setUrl] = useState(tool?.url ?? "");
  const [method, setMethod] = useState<Tool["method"]>(tool?.method ?? "POST");
  const [params, setParams] = useState<ToolParam[]>(tool?.params ?? []);
  const [headers, setHeaders] = useState<ToolHeader[]>(tool?.headers ?? []);
  const [timeoutSec, setTimeoutSec] = useState(tool?.timeout_sec ?? 10);
  const [retryOnFailure, setRetryOnFailure] = useState(tool?.retry_on_failure ?? true);
  const [blocking, setBlocking] = useState(tool?.blocking ?? true);
  const [preToolSpeech, setPreToolSpeech] = useState<PreToolSpeech>(
    tool?.pre_tool_speech ?? { mode: "none", phrase: "" },
  );
  const [responseExtract, setResponseExtract] = useState<ResponseExtract[]>(
    tool?.response_extract ?? [],
  );
  const [saving, setSaving] = useState(false);

  const [testArgs, setTestArgs] = useState<Record<string, string>>({});
  const [testResult, setTestResult] = useState<ToolTestResult | null>(null);
  const [testing, setTesting] = useState(false);

  const llmParams = params.filter((p) => p.source === "llm" && p.name);

  function updateParam(index: number, patch: Partial<ToolParam>) {
    setParams((p) => p.map((param, i) => (i === index ? { ...param, ...patch } : param)));
  }
  function removeParam(index: number) {
    setParams((p) => p.filter((_, i) => i !== index));
  }

  function updateHeader(index: number, patch: Partial<ToolHeader>) {
    setHeaders((h) => h.map((header, i) => (i === index ? { ...header, ...patch } : header)));
  }
  function removeHeader(index: number) {
    setHeaders((h) => h.filter((_, i) => i !== index));
  }

  function updateExtract(index: number, patch: Partial<ResponseExtract>) {
    setResponseExtract((r) => r.map((rule, i) => (i === index ? { ...rule, ...patch } : rule)));
  }
  function removeExtract(index: number) {
    setResponseExtract((r) => r.filter((_, i) => i !== index));
  }

  function buildInput(): ToolInput {
    // Only headers whose secret value was actually typed produce a
    // `secrets` entry — leaving it blank on an edit keeps the previously
    // stored value (see ToolUpdate.secrets in app/schemas/tool.py).
    const secrets = headers
      .filter((h) => h.value_type === "secret" && h.secret_ref && h.value)
      .map((h) => ({ secret_ref: h.secret_ref as string, value: h.value }));
    return {
      name,
      description,
      is_active: isActive,
      url,
      method,
      params,
      headers: headers.map((h) => ({ ...h, value: h.value_type === "secret" ? "" : h.value })),
      secrets,
      timeout_sec: timeoutSec,
      retry_on_failure: retryOnFailure,
      blocking,
      pre_tool_speech: preToolSpeech,
      response_extract: responseExtract,
    };
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const input = buildInput();
      if (mode === "create") {
        const created = await createTool.mutateAsync(input);
        toast.success("Tool created");
        router.push(`/tools/${created.id}`);
      } else {
        await updateTool.mutateAsync(input);
        toast.success("Tool saved");
      }
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to save tool");
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testTool.mutateAsync(testArgs);
      setTestResult(result);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Test run failed");
    } finally {
      setTesting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-6">
      <div className="flex flex-col gap-4 rounded-lg border p-4">
        <div className="flex items-center justify-between">
          <h3 className="font-medium">Basics</h3>
          <div className="flex items-center gap-2">
            <Switch id="is_active" checked={isActive} onCheckedChange={setIsActive} />
            <Label htmlFor="is_active">Active</Label>
          </div>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="tool-name">Name (the LLM-visible function name)</Label>
            <Input
              id="tool-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="check_availability"
              pattern="^[a-zA-Z_][a-zA-Z0-9_]*$"
              required
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="tool-url">URL</Label>
            <Input
              id="tool-url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com/bookings/{booking_id}"
              required
            />
          </div>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="tool-description">Description (tells the LLM when to call this)</Label>
          <Textarea
            id="tool-description"
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            required
          />
        </div>
        <div className="flex flex-col gap-1.5 sm:w-40">
          <Label>HTTP method</Label>
          <Select value={method} onValueChange={(v) => setMethod(v as Tool["method"])}>
            <SelectTrigger>
              <SelectValue>{(v) => String(v ?? "POST")}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="GET">GET</SelectItem>
              <SelectItem value="POST">POST</SelectItem>
              <SelectItem value="PUT">PUT</SelectItem>
              <SelectItem value="PATCH">PATCH</SelectItem>
              <SelectItem value="DELETE">DELETE</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="flex flex-col gap-3 rounded-lg border p-4">
        <h3 className="font-medium">Parameters</h3>
        <p className="text-sm text-muted-foreground">
          A URL segment like <code>{"{booking_id}"}</code> is filled from a param with location
          &quot;path&quot;. &quot;from caller / LLM&quot; params are the only ones the model can
          fill in — constant and dynamic values are never invented by it.
        </p>
        {params.map((param, i) => (
          <ParamRow
            key={i}
            param={param}
            onChange={(patch) => updateParam(i, patch)}
            onRemove={() => removeParam(i)}
          />
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="self-start"
          onClick={() => setParams((p) => [...p, { ...DEFAULT_PARAM }])}
        >
          + Add parameter
        </Button>
      </div>

      <div className="flex flex-col gap-3 rounded-lg border p-4">
        <h3 className="font-medium">Headers</h3>
        {headers.map((header, i) => (
          <HeaderRow
            key={i}
            header={header}
            onChange={(patch) => updateHeader(i, patch)}
            onRemove={() => removeHeader(i)}
          />
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="self-start"
          onClick={() => setHeaders((h) => [...h, { ...DEFAULT_HEADER }])}
        >
          + Add header
        </Button>
      </div>

      <div className="flex flex-col gap-4 rounded-lg border p-4">
        <h3 className="font-medium">Call behavior</h3>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="timeout">Timeout (seconds)</Label>
            <Input
              id="timeout"
              type="number"
              min={1}
              max={30}
              step={0.5}
              value={timeoutSec}
              onChange={(e) => setTimeoutSec(Number(e.target.value))}
            />
          </div>
          <div className="flex items-center gap-2 pt-6">
            <Switch checked={retryOnFailure} onCheckedChange={setRetryOnFailure} />
            <Label>Retry once on timeout/5xx</Label>
          </div>
          <div className="flex items-center gap-2 pt-6">
            <Switch checked={blocking} onCheckedChange={setBlocking} />
            <Label>Wait for the response (turn off to fire-and-forget)</Label>
          </div>
        </div>
        {!blocking && (
          <p className="text-xs text-muted-foreground">
            The caller&apos;s turn continues immediately — use this for side effects (logging to
            a CRM, etc.) where the result doesn&apos;t matter to the conversation.
          </p>
        )}
        <div className="flex flex-col gap-2">
          <Label>What the agent says while this tool runs</Label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Select
              value={preToolSpeech.mode}
              onValueChange={(v) =>
                setPreToolSpeech((s) => ({ ...s, mode: v as PreToolSpeech["mode"] }))
              }
            >
              <SelectTrigger className="sm:w-48">
                <SelectValue>{(v) => String(v ?? "none")}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Nothing</SelectItem>
                <SelectItem value="fixed">A fixed phrase</SelectItem>
                <SelectItem value="auto">Agent&apos;s usual filler phrase</SelectItem>
              </SelectContent>
            </Select>
            {preToolSpeech.mode === "fixed" && (
              <Input
                placeholder="Let me check on that…"
                value={preToolSpeech.phrase}
                onChange={(e) => setPreToolSpeech((s) => ({ ...s, phrase: e.target.value }))}
              />
            )}
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-3 rounded-lg border p-4">
        <h3 className="font-medium">Response extraction</h3>
        <p className="text-sm text-muted-foreground">
          Optional — pull specific fields out of the JSON response instead of handing the model
          the whole thing. Leave empty to pass back the raw (truncated) response text.
        </p>
        {responseExtract.map((rule, i) => (
          <ExtractRow
            key={i}
            rule={rule}
            onChange={(patch) => updateExtract(i, patch)}
            onRemove={() => removeExtract(i)}
          />
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="self-start"
          onClick={() => setResponseExtract((r) => [...r, { ...DEFAULT_EXTRACT }])}
        >
          + Add extracted field
        </Button>
      </div>

      {mode === "edit" && tool && (
        <div className="flex flex-col gap-3 rounded-lg border p-4">
          <h3 className="font-medium">Test this tool</h3>
          {llmParams.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No LLM-filled parameters — add one above, or just run the test as-is.
            </p>
          ) : (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {llmParams.map((p) => (
                <div key={p.name} className="flex flex-col gap-1">
                  <Label className="text-xs text-muted-foreground">{p.name}</Label>
                  <Input
                    value={testArgs[p.name] ?? ""}
                    onChange={(e) => setTestArgs((a) => ({ ...a, [p.name]: e.target.value }))}
                  />
                </div>
              ))}
            </div>
          )}
          <Button type="button" variant="outline" size="sm" className="self-start" onClick={handleTest} disabled={testing}>
            {testing ? "Running…" : "Run test"}
          </Button>
          {testResult && (
            <div className="flex flex-col gap-2 rounded-md border p-3 text-sm">
              <div className="flex items-center gap-2">
                <Badge variant={testResult.ok ? "default" : "destructive"}>
                  {testResult.ok ? "OK" : "Failed"}
                </Badge>
                {testResult.status_code !== null && <span>HTTP {testResult.status_code}</span>}
                <span className="text-muted-foreground">{testResult.duration_ms}ms</span>
              </div>
              <p className="break-all text-xs text-muted-foreground">{testResult.request_url}</p>
              {testResult.error && <p className="text-destructive">{testResult.error}</p>}
              {testResult.extracted && (
                <div>
                  <Label className="text-xs text-muted-foreground">Extracted</Label>
                  <pre className="overflow-x-auto rounded bg-muted p-2 text-xs">
                    {JSON.stringify(testResult.extracted, null, 2)}
                  </pre>
                </div>
              )}
              {testResult.response_body && (
                <div>
                  <Label className="text-xs text-muted-foreground">Raw response</Label>
                  <pre className="max-h-40 overflow-auto rounded bg-muted p-2 text-xs">
                    {testResult.response_body}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <Button type="submit" disabled={saving} className="self-start">
        {saving ? "Saving…" : mode === "create" ? "Create tool" : "Save changes"}
      </Button>
    </form>
  );
}
