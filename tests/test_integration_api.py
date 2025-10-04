import subprocess, time, httpx, os

IMAGE = os.environ.get("TEST_IMAGE","discountmate:local")

def run(cmd): subprocess.check_call(cmd, shell=True)

def test_end_to_end():
    cid = subprocess.check_output(
        f"docker run -d -p 8089:8080 --rm --name dm_it {IMAGE}",
        shell=True).decode().strip()
    try:
        # wait for health
        for _ in range(60):
            try:
                r = httpx.get("http://localhost:8089/health", timeout=2)
                if r.status_code == 200: break
            except Exception:
                time.sleep(0.2)

        payload = {"total": 220.0, "items": 5, "tier": "silver"}
        r = httpx.post("http://localhost:8089/recommend", json=payload, timeout=5)
        assert r.status_code == 200
        assert "discount" in r.json()
    finally:
        run("docker stop dm_it")