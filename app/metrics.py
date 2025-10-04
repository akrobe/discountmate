from prometheus_client import Counter, Histogram
REQUESTS = Counter("dm_requests_total", "Total requests", ["endpoint","method","status"])
ERRORS   = Counter("dm_errors_total", "Simulated errors")
LATENCY  = Histogram("dm_request_duration_seconds", "Request latency (s)", buckets=(0.05,0.1,0.2,0.5,1,2,5))
