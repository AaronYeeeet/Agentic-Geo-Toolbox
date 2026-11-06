# Pin the QGIS version (LTR). New version = change the tag here.
FROM qgis/qgis:3.44.15-noble

ENV QT_QPA_PLATFORM=offscreen \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Separate environment for our packages. --system-site-packages keeps PyQGIS visible,
# and the Ubuntu packages stay untouched (pip cannot uninstall them).
RUN python3 -m venv --system-site-packages /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

WORKDIR /app
COPY *.py /app/

EXPOSE 8100
CMD ["python", "server.py"]
