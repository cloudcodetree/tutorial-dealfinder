# DealFinder service image — same artifact in dev, staging, and prod.
FROM python:3.11-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .

EXPOSE 8000
# The CMD must match the ASGI app in dealfinder/serve.py (test_deploy guards this).
CMD ["uvicorn", "dealfinder.serve:app", "--host", "0.0.0.0", "--port", "8000"]
