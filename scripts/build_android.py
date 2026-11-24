import argparse
import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def main():
    parser = argparse.ArgumentParser(description="Build AfterCare's Android test APK.")
    parser.add_argument("--server", default="http://localhost:8000", help="HTTPS API origin, or localhost for USB testing")
    parser.add_argument("--skip-web-build", action="store_true")
    args = parser.parse_args()
    url = urlsplit(args.server)
    if url.username or url.password or url.path not in {"", "/"} or url.query or url.fragment or not url.hostname or (
        url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1"})
    ):
        raise SystemExit("Use an HTTPS origin or localhost for USB testing.")
    java = next((ROOT / ".tools/android-jdk").glob("*/bin/java.exe"), None)
    sdk = Path(os.environ.get("ANDROID_HOME", ROOT / ".tools/android-sdk"))
    npm = shutil.which("npm.cmd")
    if not java or not (sdk / "platforms/android-36/android.jar").is_file() or not npm:
        raise SystemExit("Run scripts/setup_android.py --accept-sdk-license first. See docs/ANDROID.md.")
    environment = dict(os.environ, JAVA_HOME=str(java.parent.parent), ANDROID_HOME=str(sdk), ANDROID_SDK_ROOT=str(sdk),
                       GRADLE_USER_HOME=str(ROOT / ".tools/gradle"), ANDROID_USER_HOME=str(ROOT / ".tools/android-user"),
                       VITE_AFTERCARE_API_ORIGIN=args.server.rstrip("/"))
    if not args.skip_web_build:
        subprocess.run([npm, "run", "test:phone"], cwd=FRONTEND, env=environment, check=True)
        subprocess.run([npm, "run", "build"], cwd=FRONTEND, env=environment, check=True)
    subprocess.run([npm, "run", "android:sync"], cwd=FRONTEND, env=environment, check=True)
    gradle = ROOT / ".tools/gradle-dist/gradle-8.14.3/bin/gradle.bat"
    subprocess.run([str(gradle if gradle.is_file() else FRONTEND / "android/gradlew.bat"), "assembleDebug", "--no-daemon", "--console=plain"],
                   cwd=FRONTEND / "android", env=environment, check=True)
    built = FRONTEND / "android/app/build/outputs/apk/debug/app-debug.apk"
    subprocess.run([str(sdk / "build-tools/35.0.0/apksigner.bat"), "verify", "--verbose", str(built)], env=environment, check=True)
    output = ROOT / "releases"
    output.mkdir(exist_ok=True)
    target = output / "AfterCare-2.1.0-test.apk"
    shutil.copyfile(built, target)
    with target.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    target.with_suffix(".apk.sha256").write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    print(f"APK ready: {target}\nConnect your Android phone and run scripts/connect_android.py.")


if __name__ == "__main__":
    main()
