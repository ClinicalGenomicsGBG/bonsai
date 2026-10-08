# NGPIris 5.6.8 requires Python >= 3.14, so this worker runs separately from the API (Python 3.11).
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN groupadd --gid 1001 worker && useradd -g worker --uid 1001 --shell /usr/sbin/nologin --create-home worker
WORKDIR /home/worker/app

COPY pyproject.toml ./
COPY hci_hcp_service hci_hcp_service/
RUN pip install --no-cache-dir .

USER worker
# Redis connection is read from RQ_REDIS_URL (set in hci_hcp.env).
CMD ["rq", "worker", "hcp"]
