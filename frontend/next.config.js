/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  distDir: 'build',
  reactStrictMode: true,
  images: { unoptimized: true },
  webpack: (config) => {
    config.module.rules.push({
      test: /\.txt$/i,
      type: 'asset/source',
    });
    return config;
  },
};

module.exports = nextConfig;
