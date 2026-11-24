import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description="Install the test APK and connect a USB Android phone to your local AfterCare server.")
    parser.add_argument("--serial", help="Device ID when several Android devices are connected")
    args = parser.parse_args()
    adb = ROOT / ".tools/android-sdk/platform-tools/adb.exe"
    apk = ROOT / "releases/AfterCare-2.1.0-test.apk"
    if not adb.is_file() or not apk.is_file():
        raise SystemExit("Build the APK first using scripts/build_android.py.")
    result = subprocess.run([str(adb), "devices"], capture_output=True, text=True, check=True)
    devices = [line.split()[0] for line in result.stdout.splitlines()[1:] if len(line.split()) == 2 and line.split()[1] == "device"]
    serial = args.serial or (devices[0] if len(devices) == 1 else None)
    if serial not in devices:
        raise SystemExit("Connect one Android phone by USB, enable USB debugging and approve this computer on the phone. Use --serial for multiple devices.")
    command = [str(adb), "-s", serial]
    subprocess.run(command + ["reverse", "tcp:8000", "tcp:8000"], check=True)
    subprocess.run(command + ["install", "-r", str(apk)], check=True)
    subprocess.run(command + ["shell", "am", "start", "-n", "com.aftercare.app/.MainActivity"], check=True)
    print("AfterCare is installed and connected over USB. Keep the local server running while importing or syncing. Downloaded plans and local reminders remain available offline.")


if __name__ == "__main__":
    main()
