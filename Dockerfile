# 使用官方Python基础镜像
FROM python:3.9-slim

# 安装必要的系统包（包含ffmpeg）
RUN apt-get update && apt-get install -y ffmpeg gcc

# 设置工作目录
WORKDIR /app

# 复制当前所有文件到容器
COPY . /app/

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 声明端口（可选，Railway会自动处理）
EXPOSE 8000

# 启动命令（注意：端口写死8000，不要用$PORT）
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"] 