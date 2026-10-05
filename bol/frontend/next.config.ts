import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Produces a minimal .next/standalone server with only the traced
  // dependencies it actually needs — without this, a Docker image built
  // from this project would have to ship the entire node_modules tree.
  output: "standalone",
};

export default nextConfig;
