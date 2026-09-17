import type { NextConfig } from "next";

// Portfolio images are served from this project's Supabase storage bucket.
const supabaseHost = (() => {
  try {
    return new URL(process.env.NEXT_PUBLIC_SUPABASE_URL ?? "").hostname;
  } catch {
    return "fuwojlqpavvfgmqardfo.supabase.co";
  }
})();

const nextConfig: NextConfig = {
  // BlockNote's server renderer pulls in a DOM implementation that must not be
  // bundled (copied from ../doctor-portfolio).
  serverExternalPackages: ["@blocknote/server-util"],
  images: {
    remotePatterns: [
      { protocol: "https", hostname: supabaseHost, pathname: "/storage/v1/object/public/**" },
    ],
  },
};

export default nextConfig;
