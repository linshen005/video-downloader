# 视频下载器

一个简单高效的视频下载工具，支持多种平台，让您轻松获取网络视频内容。

## 功能特性

- 支持多种视频平台：YouTube、TikTok、Bilibili等
- 支持下载视频(MP4)和音频(MP3)格式
- 实时显示下载进度
- 已下载文件管理（下载或删除）
- 多语言支持（中文、英文、日语、韩语）
- 用户反馈系统
- 响应式设计，支持移动设备

## 简易部署指南

### 环境要求

- Python 3.7+
- FFmpeg
- 必要的Python包（见`requirements.txt`）

### 本地运行

1. 克隆仓库
   ```bash
   git clone https://github.com/yourusername/video-downloader.git
   cd video-downloader
   ```

2. 安装依赖
   ```bash
   pip install -r requirements.txt
   ```

3. 运行应用
   ```bash
   python app.py
   ```

4. 访问应用
   打开浏览器访问 `http://localhost:5001`

### 在Render.com上部署

1. 注册并登录Render.com
2. 点击"New" > "Web Service"
3. 连接您的GitHub仓库
4. 使用以下设置：
   - 名称：`video-downloader`
   - 构建命令：`pip install -r requirements.txt`
   - 启动命令：`gunicorn app:app`
   - 高级选项 > 环境变量：
     - `FFMPEG_PATH` = `/usr/bin`
     - `FLASK_ENV` = `production`

5. 点击"Create Web Service"

## 使用说明

1. 在输入框中粘贴要下载的视频链接
2. 选择下载格式（视频或音频）
3. 点击下载按钮开始下载
4. 下载完成后，可在"已下载文件"部分找到文件

## 许可证

本项目采用MIT许可证，详见LICENSE文件。 