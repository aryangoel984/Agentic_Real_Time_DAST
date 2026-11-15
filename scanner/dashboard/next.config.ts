import type { NextConfig } from "next";

// The dashboard talks only to the SCANNER's API (port 9000), never to the target.
// Requests to /scanner-api/* are forwarded there, so no CORS settings are needed.
const SCANNER_API_URL = process.env.SCANNER_API_URL ?? "http://localhost:9000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/scanner-api/:path*", destination: `${SCANNER_API_URL}/:path*` }];
  },
};

export default nextConfig;
