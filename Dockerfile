FROM python:3.9-slim
RUN apt-get update && apt-get install -y ffmpeg gcc
WORKDIR /app
COPY . /app/
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"] 