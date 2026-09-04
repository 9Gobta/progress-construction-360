import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Keep a share/production build separate from the local development build.
  // This lets localhost continue running while an HTTPS tunnel serves `next start`.
  ...(process.env.NEXT_DIST_DIR ? { distDir: process.env.NEXT_DIST_DIR } : {}),
};

export default nextConfig;
