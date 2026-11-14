import type { NextConfig } from "next";

// The portal and the API share one address (localhost:3000).
// Any request to /api/* is forwarded to the FastAPI backend on port 8000,
// so the backend needs no cross-origin (CORS) settings.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }];
  },
};

export default nextConfig;
