/** @type {import('next').NextConfig} */
const nextConfig = {
  // Three.js uses browser globals (window, document), so we must never
  // SSR any component that imports it.  Next.js handles this automatically
  // when components carry 'use client', but we also disable server-side
  // static export for the whole app since the dashboard is always dynamic.
  output: 'standalone',
  // Required so Next.js transpiles three/examples/jsm/* (ESM-only addons)
  // through webpack instead of leaving bare ESM imports that break Node SSR.
  transpilePackages: ['three'],
};

export default nextConfig;
