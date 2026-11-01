FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ALMS_HOST=0.0.0.0 \
    ALMS_PORT=5000 \
    ALMS_DATA_DIR=/data

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alms ./alms
COPY run.py .

RUN useradd --create-home --uid 1000 alms && mkdir -p /data && chown alms:alms /data
USER alms
VOLUME ["/data"]
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:5000/login'); sys.exit(0)" || exit 1

CMD ["python", "run.py", "--no-browser"]
