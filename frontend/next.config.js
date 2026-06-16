/** @type {import('next').NextConfig} */
const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";

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

module.exports = nextConfig;
