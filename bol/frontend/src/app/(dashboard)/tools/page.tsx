"use client";

import Link from "next/link";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ApiError } from "@/lib/api";
import { useDeleteTool, useTools } from "@/lib/hooks";

export default function ToolsPage() {
  const { data: tools, isLoading } = useTools();
  const deleteTool = useDeleteTool();

  async function handleDelete(id: string, name: string) {
    if (!confirm(`Delete "${name}"? Agents referencing it will need to be updated.`)) return;
    try {
      await deleteTool.mutateAsync(id);
      toast.success("Tool deleted");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to delete tool");
    }
  }

  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Tools</h1>
          <p className="text-muted-foreground">
            Reusable webhook tools your agents can call mid-call — attach one to any agent from
            its Tools section.
          </p>
        </div>
        <Button render={<Link href="/tools/new" />} nativeButton={false}>+ New tool</Button>
      </div>

      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Method</TableHead>
              <TableHead>URL</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-muted-foreground">
                  Loading…
                </TableCell>
              </TableRow>
            )}
            {tools?.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-muted-foreground">
                  No tools yet.
                </TableCell>
              </TableRow>
            )}
            {tools?.map((tool) => (
              <TableRow key={tool.id}>
                <TableCell>
                  <Link href={`/tools/${tool.id}`} className="font-medium hover:underline">
                    {tool.name}
                  </Link>
                  <p className="text-xs text-muted-foreground">{tool.description}</p>
                </TableCell>
                <TableCell className="text-muted-foreground">{tool.method}</TableCell>
                <TableCell className="max-w-64 truncate text-muted-foreground">{tool.url}</TableCell>
                <TableCell>
                  <Badge variant={tool.is_active ? "default" : "secondary"}>
                    {tool.is_active ? "Active" : "Inactive"}
                  </Badge>
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-destructive hover:text-destructive"
                    onClick={() => handleDelete(tool.id, tool.name)}
                  >
                    Delete
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
