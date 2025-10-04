import os
import subprocess
import time
import httpx

TEST_IMAGE = os.environ.get("TEST_IMAGE", "discountmate:local")
BASE_URL_ENV = os.environ.get("BASE_URL")  # set by CI to reuse an already-running service


def run(cmd: str) -> None:
    subprocess.check_call(cmd, shell=True)


def wait_for_health(base_url: str, attempts: int = 60, delay: float = 0.5) -> bool:
    for _ in range(attempts):
        try:
            r = httpx.get(f"{base_url}/health", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(delay)
    return False


def test_end_to_end():
    cid = None

    # If CI provided BASE_URL, do NOT call docker; just hit that service.
    if BASE_URL_ENV:
        base_url = BASE_URL_ENV
    else:
        base_url = "http://localhost:8089"
        cid = subprocess.check_output(
            f"docker run -d -p 8089:8080 --rm --name dm_it {TEST_IMAGE}",
            shell=True,
        ).decode().strip()

    try:
        assert wait_for_health(base_url), f"Service at {base_url} never became healthy"

        payload = {"total": 220.0, "items": 5, "tier": "silver"}
        r = httpx.post(f"{base_url}/recommend", json=payload, timeout=5)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "discount" in body
    finally:
        # Only stop/remove if this test started the container.
        if cid:
            run("docker rm -f dm_it")