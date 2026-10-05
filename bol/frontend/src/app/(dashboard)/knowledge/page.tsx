"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import {
  useCreateKnowledgeDocument,
  useDeleteKnowledgeDocument,
  useKnowledgeDocuments,
} from "@/lib/hooks";

export default function KnowledgePage() {
  const { data: documents, isLoading } = useKnowledgeDocuments();
  const createDocument = useCreateKnowledgeDocument();
  const deleteDocument = useDeleteKnowledgeDocument();

  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await createDocument.mutateAsync({ name, content });
      toast.success("Document added");
      setName("");
      setContent("");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to add document");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this document? Agents will no longer be able to reference it.")) return;
    try {
      await deleteDocument.mutateAsync(id);
      toast.success("Document deleted");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to delete document");
    }
  }

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Knowledge base</h1>
        <p className="text-muted-foreground">
          Shared across your organization&apos;s agents — enable &quot;Can search the knowledge
          base&quot; on an agent (in its Tools section) to let it reference these documents
          during calls. Plain text or markdown only.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Add a document</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleAdd} className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="doc-name">Name</Label>
              <Input
                id="doc-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Refund policy"
                required
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="doc-content">Content</Label>
              <Textarea
                id="doc-content"
                dir="auto"
                rows={8}
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder="Paste the document text here..."
                required
              />
            </div>
            <Button type="submit" disabled={saving} className="self-start">
              {saving ? "Adding…" : "Add document"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Chunks</TableHead>
              <TableHead>Added</TableHead>
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
            {documents?.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-muted-foreground">
                  No documents yet.
                </TableCell>
              </TableRow>
            )}
            {documents?.map((doc) => (
              <TableRow key={doc.id}>
                <TableCell>{doc.name}</TableCell>
                <TableCell className="text-muted-foreground">{doc.chunk_count}</TableCell>
                <TableCell className="text-muted-foreground">
                  {new Date(doc.created_at).toLocaleDateString()}
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-destructive hover:text-destructive"
                    onClick={() => handleDelete(doc.id)}
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
