import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Keep a share/production build separate from the local development build.
  // This lets localhost continue running while an HTTPS tunnel serves `next start`.
  ...(process.env.NEXT_DIST_DIR ? { distDir: process.env.NEXT_DIST_DIR } : {}),
  // Quick tunnels use a new subdomain whenever the local share service is
  // restarted. Allow their development assets and HMR requests so remote
  // browsers hydrate reliably instead of leaving forms stuck in a pending
  // state before the request ever reaches the API.
  allowedDevOrigins: [
    "lucia-shipment-describe-trust.trycloudflare.com",
    "*.trycloudflare.com",
  ],
};

export default nextConfig;
