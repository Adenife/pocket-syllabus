FROM python:3.12-slim
WORKDIR /opt/pocket-syllabus
COPY requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && pip install --no-cache-dir -r requirements.txt
COPY app app
COPY frontend frontend
COPY database/migrations database/migrations
COPY app.py ingest.py sync.py backup.py ./
COPY data/samples data/samples
RUN useradd --create-home --uid 10001 pocket && mkdir -p /var/lib/pocket/uploads /var/lib/pocket/indexes /home/pocket/.cache && chown -R pocket:pocket /var/lib/pocket /home/pocket
USER pocket
ENV POCKET_DB_PATH=/var/lib/pocket/syllabus.db POCKET_UPLOAD_DIR=/var/lib/pocket/uploads POCKET_INDEX_DIR=/var/lib/pocket/indexes POCKET_AUTH_ENABLED=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
