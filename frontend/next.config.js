/** @type {import('next').NextConfig} */
const nextConfig = {
  // NOTE: do NOT set output: 'standalone' here. The web UI is served by
  // FastAPI (web_ui.create_web_app) which reads prerendered static HTML from
  // build/server/app/<route>.html. The 'standalone' preset drops those static
  // HTML files, which would break page serving and the UI smoke tests.
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
