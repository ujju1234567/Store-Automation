FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
    FLAGS_enable_pir_api=0 \
    FLAGS_use_mkldnn=0

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7860
CMD ["streamlit", "run", "ui.py", "--server.address=0.0.0.0", "--server.port=7860", "--server.headless=true"]
