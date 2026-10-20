import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    python = ROOT / ".venv/Scripts/python.exe" if os.name == "nt" else ROOT / ".venv/bin/python"
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not python.is_file() or not npm:
        raise SystemExit("Set up Python and Node dependencies using README.md first.")
    checks = ROOT / "data"
    checks.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="release-check-", dir=checks) as temporary:
        commands = [
            ([str(python), "-m", "pytest", "backend", "-q", "--basetemp", str(Path(temporary) / "tests")], ROOT),
            ([npm, "run", "test:care"], ROOT / "frontend"),
            ([npm, "run", "build"], ROOT / "frontend"),
        ]
        for command, directory in commands:
            subprocess.run(command, cwd=directory, check=True)
    print("Local release checks passed. This is functional verification, not clinical validation.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)
