import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "com.aftercare.app",
  appName: "AfterCare",
  webDir: "dist/client",
  android: { backgroundColor: "#f1f5f3" },
  plugins: {
    CapacitorHttp: { enabled: true },
    SystemBars: { style: "LIGHT", insetsHandling: "native" },
  },
};

export default config;
