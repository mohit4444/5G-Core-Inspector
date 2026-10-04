"""Exercise the built Docker image using synthetic logs and isolated containers.

Run `docker compose build`, then `python3 scripts/check-docker.py`.
Requires Docker Compose and the Python standard library only.
"""

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid


ROOT = Path(__file__).resolve().parents[1]
PROJECT = f"inspector-check-{uuid.uuid4().hex[:10]}"
ENV = dict(os.environ, INSPECTOR_PORT="0")
COMPOSE = ["docker", "compose", "-p", PROJECT, "-f", str(ROOT / "compose.yaml")]


def run(*args, check=True):
    return subprocess.run(args, cwd=ROOT, env=ENV, check=check,
                          capture_output=True, text=True, timeout=30)


def inspect(name):
    result = run("docker", "inspect", name, check=False)
    return json.loads(result.stdout)[0] if result.returncode == 0 else None


def wait_for(check, description):
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (urllib.error.URLError, ConnectionError):
            pass
        time.sleep(0.2)
    raise AssertionError(f"Timed out: {description}")


def request(base, path, as_json=True):
    with urllib.request.urlopen(base + path, timeout=2) as response:
        data = response.read().decode()
    return json.loads(data) if as_json else data


def check_case(label, args, core, duration, stdin=False, volume=None, default=False):
    name = f"{PROJECT}-{label}"
    process = None
    with tempfile.TemporaryFile(mode="w+") as output:
        try:
            if default:
                run(*COMPOSE, "up", "--detach", "--no-build")
                name = run(*COMPOSE, "ps", "--quiet", "inspector").stdout.strip()
            else:
                command = [*COMPOSE, "run", "--rm", "--service-ports", "-T", "--name", name]
                if volume:
                    command += ["--volume", volume]
                command += ["inspector", *args]
                process = subprocess.Popen(command, cwd=ROOT, env=ENV,
                                           stdin=subprocess.PIPE, stdout=output,
                                           stderr=subprocess.STDOUT, text=True)
            container = wait_for(lambda: inspect(name), "container creation")

            def address():
                ports = inspect(name)["NetworkSettings"]["Ports"].get("8000/tcp")
                if ports:
                    assert ports[0]["HostIp"] == "127.0.0.1", ports
                    return "http://127.0.0.1:" + ports[0]["HostPort"]

            base = wait_for(address, "published port")
            wait_for(lambda: request(base, "/api/health"), "HTTP readiness")
            if stdin:
                process.stdin.write((ROOT / "examples/success.log").read_text())
                process.stdin.flush()
            registration = wait_for(
                lambda: (value if (value := request(base, "/api/registration"))
                         .get("state") == "REGISTERED" else None), "registration")
            assert registration["durationMs"] == duration, registration
            health = request(base, "/api/health")
            assert health["status"] == "ok", health
            assert health["coreDetection"]["core"] == core, health
            assert health["logSource"]["connected"] is stdin, health
            if stdin:
                process.stdin.close()
                wait_for(lambda: not request(base, "/api/health")["logSource"]["connected"],
                         "stdin EOF")
                assert request(base, "/api/registration")["state"] == "REGISTERED"
            html = request(base, "/", as_json=False)
            assets = re.findall(r'(?:src|href)="(/static/[^\"]+)"', html)
            assert assets, html
            for asset in assets:
                assert request(base, asset, as_json=False)
            assert container["Config"]["User"] == "10001:10001"
            assert container["HostConfig"]["ReadonlyRootfs"]
            assert "ALL" in container["HostConfig"]["CapDrop"]
            assert not any(m["Destination"] == "/var/run/docker.sock" for m in container["Mounts"])
            wait_for(lambda: inspect(name)["State"]["Health"]["Status"] == "healthy",
                     "Docker health check")
            run("docker", "stop", "--time", "5", name)
            if process:
                exit_code = process.wait(timeout=10)
            else:
                exit_code = inspect(name)["State"]["ExitCode"]
            # Uvicorn re-raises SIGTERM after graceful shutdown (128 + 15).
            assert exit_code in (0, 143), f"Unexpected shutdown exit: {exit_code}"
            print(f"PASS {label}: {core}, {duration} ms, UI, health, clean shutdown", flush=True)
        except Exception:
            logs = run("docker", "logs", "--tail", "30", name, check=False)
            print(logs.stdout + logs.stderr)
            output.seek(0)
            print(output.read())
            raise
        finally:
            run("docker", "rm", "--force", name, check=False)
            if process:
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    try:
        run(*COMPOSE, "config", "--quiet")
        check_case("default", [], "open5gs", 538, default=True)
        check_case("oai", ["--replay", "/app/examples/oai-success.log"], "oai", 200)
        check_case("stdin", ["--stdin", "--year", "2026"], "open5gs", 538, stdin=True)
        check_case("file", ["--replay", "/logs/core.log", "--year", "2026"], "open5gs", 538,
                   volume=f"{ROOT / 'examples/success.log'}:/logs/core.log:ro")
    finally:
        run(*COMPOSE, "down", "--remove-orphans", check=False)
