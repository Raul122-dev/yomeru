import { defineConfig } from "vitest/config";

// Unit tests for the UI's pure logic (src/**/*.test.ts). jsdom provides
// DOMParser/File for the archive reader.
export default defineConfig({
  test: { environment: "jsdom", include: ["src/**/*.test.ts"] },
});
