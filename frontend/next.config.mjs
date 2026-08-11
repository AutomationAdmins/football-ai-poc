/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  async rewrites() {
    const backendUrl = process.env.BACKEND_API_URL ?? 'http://localhost:8000';
    return [
      {
        source: '/api/insights/stream',
        destination: `${backendUrl}/api/insights/stream`,
      },
    ];
  },
};

export default nextConfig;
