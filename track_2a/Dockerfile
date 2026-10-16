FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ src/
COPY data/ data/
COPY tests/ tests/
COPY eval/ eval/
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1 PORT=8000
EXPOSE 8000
CMD ["python", "-m", "william", "serve"]
