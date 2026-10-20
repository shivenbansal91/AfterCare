import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    frontend = ROOT / "frontend/dist/client/index.html"
    python = ROOT / ".venv/Scripts/python.exe" if os.name == "nt" else ROOT / ".venv/bin/python"
    if not python.is_file() or not frontend.is_file():
        raise SystemExit("Install the locked backend dependencies and run npm run build in frontend first. See README.md.")
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", 8000))
        except OSError:
            raise SystemExit("Port 8000 is already in use. Stop the other AfterCare server before starting the local release.")
    environment = dict(os.environ, AFTERCARE_SERVE_FRONTEND="1")
    environment.setdefault("AFTERCARE_PUSH_SUBJECT", "https://localhost")
    data = Path(environment.get("AFTERCARE_DATA", ROOT / "data")).resolve()
    data.mkdir(parents=True, exist_ok=True)
    with (data / "server.log").open("a", encoding="utf-8") as log:
        process = subprocess.Popen([str(python), "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000"],
                                   cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            for _ in range(30):
                if process.poll() is not None:
                    raise SystemExit(f"AfterCare could not start. Read {data / 'server.log'}.")
                try:
                    with urlopen("http://127.0.0.1:8000/api/health", timeout=3) as response:
                        if response.status == 200:
                            break
                except (URLError, TimeoutError):
                    time.sleep(0.5)
            else:
                raise SystemExit("AfterCare did not become ready. Read the server log.")
            print("AfterCare Local: http://127.0.0.1:8000/\nPress Ctrl+C to stop. Keep this window open.", flush=True)
            process.wait()
        except KeyboardInterrupt:
            pass
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
