import path from "node:path";
import type { NextConfig } from "next";

const fastApiUrl = process.env.FASTAPI_URL?.trim().replace(/\/+$/, "");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Evita que a Vercel use um package-lock.json fora deste repositório.
  outputFileTracingRoot: path.join(__dirname),
  // Proxy same-origin para a API HTTP na AWS (evita mixed content no browser HTTPS).
  async rewrites() {
    if (!fastApiUrl) return [];
    return [
      {
        source: "/backend-api/:path*",
        destination: `${fastApiUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
