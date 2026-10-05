"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/lib/auth-context";

export default function Home() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    router.replace(user ? "/agents" : "/login");
  }, [loading, user, router]);

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center">
      <h1 className="text-3xl font-semibold tracking-tight">BOL بول</h1>
      <p className="text-muted-foreground">Open-source-first AI calling platform.</p>
    </div>
  );
}
