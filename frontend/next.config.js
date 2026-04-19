/** @type {import('next').NextConfig} */
const nextConfig = {
  // Proxy /api/* requests to the FastAPI backend.
  //
  // IMPORTANT: Next.js evaluates rewrites() at BUILD TIME and stores the result in
  // the routes-manifest. Therefore API_BASE_URL must be set *before* running
  // `npm run build` (e.g. via .env.local or an explicit env var on the build command).
  //
  // Default is http://localhost:8001, which matches the docker-compose backend port
  // (PORT_PREFIX=80 → external port 8001).
  // In Docker, set API_BASE_URL=http://backend:8000 (internal service address).
  async rewrites() {
    const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:8001";
    return [
      {
        source: "/api/:path*",
        destination: `${apiBaseUrl}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
