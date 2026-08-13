import { defineConfig } from "vite";
import { tanstackStart } from "@tanstack/react-start/plugin/vite";
import viteReact from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { nitro } from "nitro/vite";

// Previously this delegated to @lovable.dev/vite-tanstack-config, which bundled
// these plugins plus editor-only tooling. The plugins are declared explicitly so
// the build has no dependency on the environment it was authored in.
//
// Order matters: Tailwind before Start, Start before Nitro, React last.
export default defineConfig({
  resolve: {
    // The `@/*` alias lives in tsconfig.json. Vite 8 reads it natively, so the
    // vite-tsconfig-paths plugin is not needed.
    tsconfigPaths: true,
  },
  plugins: [
    tailwindcss(),
    tanstackStart({
      // Route the SSR entry through src/server.ts, which converts a swallowed
      // h3 500 back into a readable error page.
      server: { entry: "server" },
    }),
    nitro(),
    viteReact(),
  ],
});
