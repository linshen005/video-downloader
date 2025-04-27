from flask import Flask, render_template, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from urllib.parse import unquote
import yt_dlp
import os
import logging
import threading
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json
from datetime import datetime
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import re
import time
import tempfile
from os.path import join, dirname
from dotenv import load_dotenv

# 尝试加载环境变量，如果.env文件存在
try:
    load_dotenv(join(dirname(__file__), '.env'))
except:
    pass

# 初始化应用
app = Flask(__name__)
# 启用CORS，允许所有来源的请求
CORS(app)

# 日志设置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 配置路径
DOWNLOAD_FOLDER = os.environ.get('DOWNLOAD_FOLDER', 'downloads')
FFMPEG_PATH = os.environ.get('FFMPEG_PATH', '/usr/bin')

# 下载进度全局变量
download_progress = {
    "status": "idle",  # idle, downloading, finished, error
    "percent": "0.0%",
    "message": "",
    "speed": "",
    "eta": ""
}
progress_lock = threading.Lock()

# 确保下载目录存在
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
    logger.info(f"已创建下载目录: {DOWNLOAD_FOLDER}")

@app.route('/')
def home():
    try:
        files = []
        if os.path.exists(DOWNLOAD_FOLDER):
            for filename in os.listdir(DOWNLOAD_FOLDER):
                if os.path.isfile(os.path.join(DOWNLOAD_FOLDER, filename)):
                    file_path = os.path.join(DOWNLOAD_FOLDER, filename)
                    file_stats = os.stat(file_path)
                    size_mb = file_stats.st_size / (1024 * 1024)
                    files.append({
                        'name': filename,
                        'size': f'{size_mb:.2f} MB',
                        'path': file_path
                    })
        return render_template('index.html', files=files)
    except Exception as e:
        logger.error(f"Error in home route: {str(e)}")
        return "Error loading page. Check server logs for details.", 500

def progress_hook(d):
    with progress_lock:
        if d['status'] == 'downloading':
            percent = d.get('_percent_str', None)
            if percent and '%' in percent:
                percent = percent.strip().replace('N/A', '0.0%')
            else:
                # 计算百分比
                downloaded = d.get('downloaded_bytes', 0)
                total = d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0)
                if total:
                    percent = f"{downloaded / total * 100:.1f}%"
                else:
                    percent = "0.0%"
            
            # 获取下载速度
            speed = d.get('_speed_str', '')
            
            # 计算剩余时间 (ETA)
            eta = d.get('_eta_str', '')
            
            # 只保留数字和百分号
            if not percent.endswith('%'):
                percent = "0.0%"
                
            download_progress['status'] = 'downloading'
            download_progress['percent'] = percent
            download_progress['message'] = d.get('filename', '')
            download_progress['speed'] = speed
            download_progress['eta'] = eta
        elif d['status'] == 'finished':
            download_progress['status'] = 'finished'
            download_progress['percent'] = '100.0%'
            download_progress['message'] = 'Download finished'
        elif d['status'] == 'error':
            download_progress['status'] = 'error'
            download_progress['message'] = 'Download error'

@app.route('/download', methods=['POST'])
def download_video():
    try:
        url = unquote(request.form['url'])
        format_type = request.form.get('format', 'mp4')
        logger.info(f"Download request received, URL: {url}, Format: {format_type}")

        # 检查目标平台
        platform = "unknown"
        if "tiktok.com" in url:
            platform = "tiktok"
            logger.info("Detected TikTok URL")
        elif "youtube.com" in url or "youtu.be" in url:
            platform = "youtube"
            logger.info("Detected YouTube URL")
        elif "bilibili.com" in url:
            platform = "bilibili"
            logger.info("Detected Bilibili URL")
        
        # 确保下载目录存在
        if not os.path.exists(DOWNLOAD_FOLDER):
            logger.info(f"Creating download directory: {DOWNLOAD_FOLDER}")
            os.makedirs(DOWNLOAD_FOLDER)

        ffmpeg_exec = os.path.join(FFMPEG_PATH, 'ffmpeg')
        ffprobe_exec = os.path.join(FFMPEG_PATH, 'ffprobe')
        if not os.path.exists(ffmpeg_exec) or not os.path.exists(ffprobe_exec):
            logger.error(f"FFmpeg not found at {FFMPEG_PATH}")
            return jsonify({
                'success': False,
                'message': 'FFmpeg not found. Please check installation.'
            })

        # 下载前重置进度
        with progress_lock:
            download_progress['status'] = 'downloading'
            download_progress['percent'] = '0.0%'
            download_progress['message'] = ''

        # 文件名处理函数
        def sanitize_filename(filename):
            if not filename:
                return f"video_{int(time.time())}"  # 使用时间戳创建唯一文件名
            
            # 移除非法字符
            s = re.sub(r'[\\/*?:"<>|]', "", filename)
            # 替换空格为下划线
            s = re.sub(r'\s+', '_', s)
            # 移除前后的点和空格
            s = s.strip('. ')
            # 移除其他潜在问题字符
            s = re.sub(r'[^\w\.-]', '_', s)
            # 确保长度不超过100个字符
            if len(s) > 100:
                s = s[:97] + "..."
            # 如果文件名为空，使用时间戳
            return s if s else f"video_{int(time.time())}"

        # 生成唯一的输出文件路径
        timestamp = int(time.time())
        safe_output_template = f"{DOWNLOAD_FOLDER}/%(title)s_{timestamp}.%(ext)s"
        
        # 记录使用的输出模板
        logger.info(f"Using output template: {safe_output_template}")

        base_opts = {
            'quiet': False,
            'no_warnings': False,
            'outtmpl': safe_output_template,
            'ffmpeg_location': FFMPEG_PATH,
            'progress_hooks': [progress_hook],
            'ignoreerrors': True,  # 忽略一些非关键错误
            'verbose': True,       # 启用详细日志
        }
        
        # 特殊平台处理
        if platform == "tiktok":
            # TikTok 需要特殊处理，使用唯一文件名避免问题
            unique_filename = f"tiktok_video_{timestamp}"
            direct_output = os.path.join(DOWNLOAD_FOLDER, f"{unique_filename}.mp4")
            base_opts['outtmpl'] = direct_output

        if format_type == 'mp3':
            ydl_opts = {
                **base_opts,
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            }
        else:
            ydl_opts = {
                **base_opts,
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            }

        # 下载视频
        video_title = f"video_{timestamp}"  # 默认标题
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.info("Attempting to extract video info...")
                info = ydl.extract_info(url, download=False)
                
                if info:
                    video_title = info.get('title', f"video_{timestamp}")
                    logger.info(f"Video title: {video_title}")
                    
                    # 清理并安全化文件名
                    safe_title = sanitize_filename(video_title)
                    logger.info(f"Sanitized title: {safe_title}")
                    
                    # 对于非TikTok视频，使用清理后的标题
                    if platform != "tiktok":
                        output_path = os.path.join(DOWNLOAD_FOLDER, f"{safe_title}_{timestamp}")
                        if format_type == 'mp3':
                            ydl_opts['outtmpl'] = f"{output_path}.%(ext)s"
                        else:
                            ydl_opts['outtmpl'] = f"{output_path}.%(ext)s"
                    
                    logger.info(f"Final output template: {ydl_opts['outtmpl']}")
                
                logger.info("Starting download process...")
                ydl.download([url])
                logger.info("Download process completed")
        except Exception as e:
            logger.error(f"Error during yt-dlp execution: {str(e)}", exc_info=True)
            raise

        # 查找最新下载的文件
        try:
            logger.info(f"Scanning {DOWNLOAD_FOLDER} for downloaded files")
            files = [f for f in os.listdir(DOWNLOAD_FOLDER) 
                    if os.path.isfile(os.path.join(DOWNLOAD_FOLDER, f))]
            
            if not files:
                logger.error("No files found in download directory")
                raise Exception("No files found after download")
            
            logger.info(f"Found {len(files)} files, finding latest one")
            latest_file = max(files, key=lambda x: os.path.getctime(os.path.join(DOWNLOAD_FOLDER, x)))
            logger.info(f"Latest file is: {latest_file}")
            
            # 验证文件存在且可访问
            latest_path = os.path.join(DOWNLOAD_FOLDER, latest_file)
            if not os.path.exists(latest_path):
                logger.error(f"Latest file not found: {latest_path}")
                raise Exception(f"Downloaded file not found: {latest_path}")
                
            file_size = os.path.getsize(latest_path) / (1024*1024)
            logger.info(f"File size: {file_size:.2f} MB")
            
            # 检查文件大小是否为0
            if file_size <= 0:
                logger.error("Downloaded file has zero size")
                raise Exception("Downloaded file has zero size")
        except Exception as e:
            logger.error(f"Error processing downloaded file: {str(e)}", exc_info=True)
            raise

        with progress_lock:
            download_progress['status'] = 'finished'
            download_progress['percent'] = '100.0%'
            download_progress['message'] = 'Download finished'

        return jsonify({
            'success': True,
            'message': f"{'Audio' if format_type == 'mp3' else 'Video'} '{safe_title}' downloaded successfully!",
            'file': {
                'name': latest_file,
                'size': f"{file_size:.2f} MB"
            }
        })

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Download failed: {error_msg}", exc_info=True)
        with progress_lock:
            download_progress['status'] = 'error'
            download_progress['message'] = f"Download failed: {error_msg}"
        return jsonify({
            'success': False,
            'message': f"Download failed: {error_msg}"
        })

@app.route('/progress')
def get_progress():
    with progress_lock:
        return jsonify(download_progress)

@app.route('/download_file/<filename>')
def download_file(filename):
    try:
        return send_file(os.path.join(DOWNLOAD_FOLDER, filename), as_attachment=True)
    except Exception as e:
        return str(e), 404

@app.route('/delete/<filename>', methods=['POST'])
def delete_file(filename):
    try:
        # 对文件名进行解码，确保正确处理特殊字符
        decoded_filename = unquote(filename)
        file_path = os.path.join(DOWNLOAD_FOLDER, decoded_filename)
        
        # 检查文件是否存在
        if not os.path.exists(file_path):
            app.logger.warning(f"尝试删除不存在的文件: {file_path}")
            return jsonify({
                'success': False,
                'message': 'File does not exist'
            })
        
        # 尝试删除文件
        os.remove(file_path)
        app.logger.info(f"文件删除成功: {file_path}")
        
        return jsonify({
            'success': True,
            'message': 'File deleted successfully'
        })
    except Exception as e:
        app.logger.error(f"删除文件时出错: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })

@app.route('/send_feedback', methods=['POST'])
def send_feedback():
    try:
        data = request.json
        from_email = data.get('email')
        message = data.get('message')
        
        if not from_email or not message:
            return jsonify({'success': False, 'message': '邮箱和消息不能为空'})
        
        # 创建feedback目录（如果不存在）
        feedback_dir = os.path.join(os.path.dirname(__file__), 'feedback')
        os.makedirs(feedback_dir, exist_ok=True)
        
        # 添加时间戳到文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"feedback_{timestamp}_{from_email.replace('@', '_at_')}.txt"
        filepath = os.path.join(feedback_dir, filename)
        
        # 写入反馈内容（添加更多信息）
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"发件人: {from_email}\n")
            f.write(f"IP地址: {request.remote_addr}\n")
            f.write(f"用户代理: {request.headers.get('User-Agent', 'Unknown')}\n")
            f.write(f"\n消息内容:\n{'='*50}\n{message}\n{'='*50}\n")
        
        # 记录到日志
        logger.info(f"收到来自 {from_email} 的反馈")
        
        return jsonify({'success': True, 'message': '反馈已成功保存，感谢您的反馈！'})
        
    except Exception as e:
        logger.error(f"保存反馈错误: {str(e)}")
        return jsonify({'success': False, 'message': f'发送失败: {str(e)}'})

@app.route('/admin/feedback', methods=['GET'])
def view_feedback():
    # 设置一个安全的密钥（不要使用默认值）
    admin_key = request.args.get('key')
    if admin_key != '你的安全密钥':  # 替换为你自己设定的复杂密钥
        return "未授权访问", 401
    
    feedback_dir = os.path.join(os.path.dirname(__file__), 'feedback')
    feedbacks = []
    
    if os.path.exists(feedback_dir):
        for filename in sorted(os.listdir(feedback_dir), reverse=True):
            if filename.startswith('feedback_') and filename.endswith('.txt'):
                file_path = os.path.join(feedback_dir, filename)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 提取基本信息
                email = "Unknown"
                date = "Unknown"
                for line in content.split('\n'):
                    if line.startswith("发件人:"):
                        email = line.replace("发件人:", "").strip()
                    elif line.startswith("时间:"):
                        date = line.replace("时间:", "").strip()
                
                feedbacks.append({
                    'filename': filename,
                    'email': email,
                    'date': date,
                    'content': content
                })
    
    return render_template('admin_feedback.html', feedbacks=feedbacks)

# 主程序入口
if __name__ == '__main__':
    # 在开发环境使用debug模式
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    port = int(os.environ.get('PORT', 5001))
    
    app.run(host='0.0.0.0', port=port, debug=debug_mode)