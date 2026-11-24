import argparse
import hashlib
import os
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".tools"
DOWNLOADS = TOOLS / "android-downloads"
SDK = TOOLS / "android-sdk"
SDK_SHA256 = "90ae805d20434428bffcb699c290860f19bb5f66a67e6b330067e3de801fb04a"


def download(url, path, checksum):
    valid = False
    if path.is_file():
        with path.open("rb") as source:
            valid = hashlib.file_digest(source, "sha256").hexdigest() == checksum
    if not valid:
        print(f"Downloading {path.name}...", flush=True)
        subprocess.run(["curl.exe", "--fail", "--location", "--retry", "2", "--max-time", "300", "--silent", "--show-error", url, "--output", str(path)], check=True)
    with path.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != checksum:
            raise SystemExit(f"Checksum mismatch: {path.name}")


def extract(archive, destination, strip_prefix=""):
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as source:
        for entry in source.infolist():
            name = entry.filename.removeprefix(strip_prefix)
            target = (destination / name).resolve()
            if not target.is_relative_to(destination):
                raise SystemExit("Archive contains an invalid path.")
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(entry) as incoming, target.open("wb") as output:
                    while chunk := incoming.read(1024 * 1024):
                        output.write(chunk)


def main():
    parser = argparse.ArgumentParser(description="Install Android build tools inside .tools on Windows.")
    parser.add_argument("--accept-sdk-license", action="store_true", help="Accept Google's Android SDK license: https://developer.android.com/studio#command-tools")
    args = parser.parse_args()
    if os.name != "nt" or not args.accept_sdk_license:
        raise SystemExit("This Windows setup requires explicit --accept-sdk-license authorization.")
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    manager = SDK / "cmdline-tools/latest/bin/sdkmanager.bat"
    if not manager.is_file():
        archive = DOWNLOADS / "command-line-tools.zip"
        download("https://dl.google.com/android/repository/commandlinetools-win-15859902_latest.zip", archive, SDK_SHA256)
        extract(archive, SDK / "cmdline-tools/latest", "cmdline-tools/")
    java = next((TOOLS / "android-jdk").glob("*/bin/java.exe"), None)
    if not java:
        url = "https://aka.ms/download-jdk/microsoft-jdk-21-windows-x64.zip"
        checksum = subprocess.run(["curl.exe", "--fail", "--location", "--silent", "--show-error", url + ".sha256sum.txt"],
                                  capture_output=True, text=True, check=True).stdout.split()[0]
        archive = DOWNLOADS / "jdk21.zip"
        download(url, archive, checksum)
        extract(archive, TOOLS / "android-jdk")
        java = next((TOOLS / "android-jdk").glob("*/bin/java.exe"))
    environment = dict(os.environ, JAVA_HOME=str(java.parent.parent), ANDROID_HOME=str(SDK), ANDROID_SDK_ROOT=str(SDK))
    gradle = TOOLS / "gradle-dist/gradle-8.14.3/bin/gradle.bat"
    if not gradle.is_file():
        url = "https://downloads.gradle.org/distributions/gradle-8.14.3-bin.zip"
        checksum = subprocess.run(["curl.exe", "--fail", "--location", "--silent", "--show-error", url + ".sha256"],
                                  capture_output=True, text=True, check=True).stdout.strip()
        archive = DOWNLOADS / "gradle-8.14.3-bin.zip"
        download(url, archive, checksum)
        extract(archive, TOOLS / "gradle-dist")
    command = [str(manager), f"--sdk_root={SDK}"]
    with (DOWNLOADS / "sdk-install.log").open("w", encoding="utf-8") as log:
        subprocess.run(command + ["platform-tools", "platforms;android-36", "build-tools;35.0.0", "build-tools;36.0.0"],
                       input="y\n" * 100, text=True, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=900)
    print("Android tools installed. Run scripts/build_android.py to build the APK.")


if __name__ == "__main__":
    main()
