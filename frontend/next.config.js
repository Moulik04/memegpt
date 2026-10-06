const { PHASE_PRODUCTION_BUILD } = require("next/constants");

const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";

// Without the Google client id the app still builds and runs, just with no
// way to sign in, so a production deploy missing it would look healthy.
// Fail that build instead. VERCEL_ENV, not NODE_ENV: every `next build` is
// NODE_ENV=production, including local, Docker and Vercel preview builds,
// and those are allowed to go without sign-in.
function assertProductionEnv() {
  if (process.env.VERCEL_ENV !== "production") return;
  if (!(process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "").trim()) {
    throw new Error(
      "NEXT_PUBLIC_GOOGLE_CLIENT_ID is not set for this production build. " +
        "Sign-in would be missing from the deployed site. Set it in Vercel " +
        "(Production environment) and redeploy.",
    );
  }
}

/** @type {import('next').NextConfig} */

const nextConfig = {
  images: {
    remotePatterns: [
      // Local dev
      { protocol: "http",  hostname: "localhost",    port: "8000", pathname: "/static/**" },
      // Docker internal
      { protocol: "http",  hostname: "backend",      port: "8000", pathname: "/static/**" },
      // Render.com production
      { protocol: "https", hostname: "*.onrender.com",             pathname: "/static/**" },
    ],
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/:path*`,
      },
    ];
  },
};

module.exports = (phase) => {
  if (phase === PHASE_PRODUCTION_BUILD) assertProductionEnv();
  return nextConfig;
};
