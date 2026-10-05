"use client";

import { useParams } from "next/navigation";

import { ToolForm } from "@/components/tool-form";
import { useTool } from "@/lib/hooks";

export default function EditToolPage() {
  const { id } = useParams<{ id: string }>();
  const { data: tool, isLoading } = useTool(id);

  if (isLoading) return <p className="text-muted-foreground">Loading…</p>;
  if (!tool) return <p className="text-muted-foreground">Tool not found.</p>;

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{tool.name}</h1>
        <p className="text-muted-foreground">Edit tool configuration</p>
      </div>
      <ToolForm mode="edit" tool={tool} />
    </div>
  );
}
