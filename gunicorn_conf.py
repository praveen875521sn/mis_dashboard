# gunicorn_conf.py — tuned for 300MB+ file uploads and 3GB total data
#
# KEY CHANGES for large data:
#  - timeout 300s: file read + MySQL insert for 50L rows takes 2-4 min
#  - workers=1: with 3GB in-memory data, 2 workers = 6GB RAM → OOM on Cloud Run
#               Use 1 worker + 8 threads (threads share memory, workers don't)
#  - worker_class=gthread: async threads handle concurrent API calls
#  - worker_connections not needed for gthread (that's for gevent/eventlet)

bind         = "0.0.0.0:8080"
workers      = 1        # FIX: was 2 — each worker duplicates 3GB RAM → OOM
threads      = 8        # FIX: was 4 — threads share memory, safe to increase
worker_class = "gthread"
timeout      = 600      # FIX: was 300 — 300MB XLSX upload over slow network can take > 5 min
keepalive    = 5
loglevel     = "info"
accesslog    = "-"
errorlog     = "-"

# Prevent gunicorn from killing long-running background rebuild threads
graceful_timeout = 600
