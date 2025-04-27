# 使用官方轻量版Python镜像
FROM python:3.9-slim

# 安装系统依赖：ffmpeg 和 gcc（防止yt-dlp需要编译问题）
RUN apt-get update && apt-get install -y ffmpeg gcc

# 设置工作目录
WORKDIR /app

# 复制所有文件到容器
COPY . /app/

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 公开8000端口（可选）
EXPOSE 8000

# 启动服务（这里端口直接写8000，兼容Railway）
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"] 