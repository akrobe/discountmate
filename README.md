# DiscountMate

A tiny, **production-like** FastAPI microservice that recommends a discount for an e-commerce basket.  
It’s intentionally small but complete enough to demonstrate a full **Jenkins CI/CD** pipeline:
Build → Test → Code Quality → Security → Deploy → Release → Monitoring.

> This repository implements the **SIT223/753 High-Distinction DevOps Pipeline** submission (7 stages, gates, IaC, monitoring, and alert simulation).

---

## What it does

**API endpoints**
- `GET /health` → `{ "status": "ok" }` (used as deploy gate)
- `POST /recommend` → `{"discount": 0.10}` (inputs: `total`, `items`, `tier: bronze|silver|gold|platinum`)
- `GET /metrics` → Prometheus metrics (counters + latency histograms)
- `POST /simulate_error` → increments an error counter (for alerting demo)

**How the discount is computed**
- A small `DecisionTreeRegressor` (scikit-learn) is trained on synthetic data at startup.
- Features: `total`, `items`, `tier_index` (0..3).
- Output is clamped to `[0.0, 0.5]`.

---

## Quick start (Docker)

Build and run locally:

```bash
# from repo root
docker build -t discountmate:local .
docker run -d --rm -p 8081:8080 --name dm_local discountmate:local

# health and recommendation
curl -s http://localhost:8081/health
curl -s -XPOST http://localhost:8081/recommend -H 'content-type: application/json' \
     -d '{"total": 220.0, "items": 5, "tier": "silver"}'

