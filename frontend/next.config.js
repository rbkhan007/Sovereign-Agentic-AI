/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  distDir: 'build',
  reactStrictMode: true,
  images: { unoptimized: true },
};

module.exports = nextConfig;
