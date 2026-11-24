import { Capacitor } from "@capacitor/core";

export const isPhone = Capacitor.isNativePlatform();

export function serverOrigin(
  value = import.meta.env.VITE_AFTERCARE_API_ORIGIN || "http://localhost:8000",
) {
  const url = new URL(value);
  if (
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.search ||
    url.hash ||
    (url.protocol !== "https:" &&
      !(
        url.protocol === "http:" &&
        ["localhost", "127.0.0.1"].includes(url.hostname)
      ))
  ) {
    throw new Error(
      "Use an HTTPS server address, or localhost for USB testing.",
    );
  }
  return url.origin;
}
