import { fileURLToPath } from "url";
import path from "path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Explicitly set the monorepo root so Turbopack does not infer it
  // from ambient lockfiles outside the repository.
  turbopack: {
    root: path.resolve(__dirname, "../.."),
  },
};

export default nextConfig;
