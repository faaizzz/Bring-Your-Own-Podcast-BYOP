// Placeholder build: copies public/ to dist/. Replaced by the Vite build in the web skeleton story.
import { cp, rm } from "node:fs/promises";

await rm("dist", { recursive: true, force: true });
await cp("public", "dist", { recursive: true });
