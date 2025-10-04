from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from app.metrics import REQUESTS, ERRORS, LATENCY
import time

app = FastAPI(title="DiscountMate")

@app.get("/health")
def health():
    return {"status":"ok"}

@app.post("/recommend")
def recommend(payload: dict):
    t0 = time.time()
    status = "200"
    try:
        total = float(payload.get("total", 0))
        items = int(payload.get("items", 1))
        tier  = str(payload.get("tier", "bronze"))
        if total < 0 or items <= 0:
            raise ValueError
        # simple placeholder: 10% discount
        return {"discount": 0.10}
    except Exception:
        status = "400"
        raise HTTPException(status_code=400, detail="invalid request")
    finally:
        LATENCY.observe(time.time() - t0)
        REQUESTS.labels("/recommend","POST",status).inc()

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/simulate_error")
def simulate_error():
    ERRORS.inc()
    raise HTTPException(status_code=500, detail="simulated failure")
