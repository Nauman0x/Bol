"use client";

import { ToolForm } from "@/components/tool-form";

export default function NewToolPage() {
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">New tool</h1>
        <p className="text-muted-foreground">
          Once created, attach it to any agent from the agent&apos;s Tools section.
        </p>
      </div>
      <ToolForm mode="create" />
    </div>
  );
}
