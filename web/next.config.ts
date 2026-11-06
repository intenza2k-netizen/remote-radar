import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Lets a second dev server or build run next to the default one without sharing `.next` (set NEXT_DIST_DIR).
  distDir: process.env.NEXT_DIST_DIR || ".next",
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
