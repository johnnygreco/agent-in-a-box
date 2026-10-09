// The course website. CI builds it from publishable data only (PLAN.md,
// Publishing rules; decisions/0011) and deploys it to GitHub Pages at
// https://johnnygreco.dev/agent-in-a-box/.
import { copyFileSync, mkdirSync } from "node:fs";
import { defineConfig } from "astro/config";
import mdx from "@astrojs/mdx";

// The README banner is the site's banner too: copied at build time, never by hand.
mkdirSync(new URL("./public/", import.meta.url), { recursive: true });
copyFileSync(new URL("../assets/banner.svg", import.meta.url),
             new URL("./public/banner.svg", import.meta.url));

export default defineConfig({
  site: process.env.SITE_URL ?? "https://johnnygreco.dev",
  base: process.env.SITE_BASE ?? "/agent-in-a-box",
  trailingSlash: "always",
  integrations: [mdx()],
  build: { format: "directory" },
});
