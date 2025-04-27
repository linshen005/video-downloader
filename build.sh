#!/bin/bash
# 构建脚本 - 用于Cloudflare Pages

echo "开始构建过程..."

# 显示Python版本
python --version

# 安装Python依赖
echo "安装依赖..."
pip install -r requirements.txt

# 创建必要的目录
echo "创建目录结构..."
mkdir -p dist/downloads
mkdir -p dist/feedback

# 复制静态文件到输出目录
echo "复制静态资源..."
cp -r static dist/
cp -r templates dist/

# 确保目录正确创建
echo "检查目录结构..."
ls -la dist/

# 创建一个简单的index.html文件确保Pages可以加载
echo "<!DOCTYPE html>
<html>
<head>
    <meta charset='utf-8'>
    <title>Video Downloader</title>
    <meta http-equiv='refresh' content='0; url=/templates/index.html'>
</head>
<body>
    <p>正在重定向到主页...</p>
</body>
</html>" > dist/index.html

# 输出完成信息
echo "构建完成! 文件已准备好部署到Cloudflare Pages。" 