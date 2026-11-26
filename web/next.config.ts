import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The dev badge isn't part of Glint; compile and runtime errors still surface.
  devIndicators: false,
};

export default nextConfig;
