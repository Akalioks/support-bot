FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot ./bot
COPY knowledge ./knowledge
VOLUME /app/data
ENV DATABASE_URL=sqlite+aiosqlite:////app/data/support.db
CMD ["python", "-m", "bot"]
