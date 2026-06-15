/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    remotePatterns: [
      // Local dev
      { protocol: "http", hostname: "localhost", port: "8000", pathname: "/static/**" },
      // Docker — Next.js server fetches images via internal DNS when optimizing
      { protocol: "http", hostname: "backend", port: "8000", pathname: "/static/**" },
    ],
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/:path*",
      },
    ];
  },
};

module.exports = nextConfig;
