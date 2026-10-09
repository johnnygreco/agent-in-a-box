// Development scaffold (Milestone 0). Pages render development bundles produced
// under the test backend; nothing here is published (STATUS.md).
import { defineConfig } from "astro/config";
import mdx from "@astrojs/mdx";

export default defineConfig({
  integrations: [mdx()],
  build: { format: "directory" },
});
