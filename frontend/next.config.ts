import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Trailing slash redirect'ini kapat — API proxy'de Auth header kaybını önler
  skipTrailingSlashRedirect: true,
  // API çağrıları Next.js üzerinden proxy'lenir (BFF pattern — KVKK / CORS)
  async rewrites() {
    return [
      {
        source: "/api/backend/:path*",
        destination: `${process.env.BACKEND_URL || "http://localhost:8000"}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
