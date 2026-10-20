import { mergeConfig } from "vite";
import base from "./vite.config";
import tailwindcss from "@tailwindcss/vite";

export default mergeConfig(base, {
  plugins: [tailwindcss()],
  server: { host: "127.0.0.1", proxy: { "/api": "http://127.0.0.1:8000" } },
});
