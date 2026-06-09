import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Evita que a Vercel use um package-lock.json fora deste repositório.
  outputFileTracingRoot: path.join(__dirname),
};

export default nextConfig;
