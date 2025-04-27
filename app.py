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
DOWNLOAD_FOLDER = os.environ.get('DOWNLOAD_FOLDER', '/tmp/downloads')
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
            logger.info(f"Scanning download folder: {DOWNLOAD_FOLDER}")
            for filename in os.listdir(DOWNLOAD_FOLDER):
                file_path = os.path.join(DOWNLOAD_FOLDER, filename)
                if os.path.isfile(file_path):
                    try:
                        file_stats = os.stat(file_path)
                        size_mb = file_stats.st_size / (1024 * 1024)
                        files.append({
                            'name': filename,
                            'size': f'{size_mb:.2f} MB',
                            'path': file_path
                        })
                        logger.info(f"Found file: {filename}, size: {size_mb:.2f} MB")
                    except Exception as e:
                        logger.error(f"Error processing file {file_path}: {str(e)}")
        else:
            logger.warning(f"Download folder {DOWNLOAD_FOLDER} does not exist")
            
        logger.info(f"Found {len(files)} files")
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
            os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

        # 检查FFMPEG路径
        ffmpeg_exec = os.path.join(FFMPEG_PATH, 'ffmpeg')
        ffprobe_exec = os.path.join(FFMPEG_PATH, 'ffprobe')
        logger.info(f"Using FFMPEG path: {FFMPEG_PATH}")
        logger.info(f"ffmpeg exists: {os.path.exists(ffmpeg_exec)}, ffprobe exists: {os.path.exists(ffprobe_exec)}")
        
        if not os.path.exists(ffmpeg_exec):
            logger.error(f"FFmpeg not found at {ffmpeg_exec}")
            return jsonify({
                'success': False,
                'message': f'FFmpeg not found at {ffmpeg_exec}. Please check installation.'
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
        output_dir = os.path.abspath(DOWNLOAD_FOLDER)
        logger.info(f"Download directory (absolute path): {output_dir}")
        
        # 测试目录是否可写
        try:
            test_file = os.path.join(output_dir, f"test_{timestamp}.txt")
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            logger.info(f"Directory {output_dir} is writable")
        except Exception as e:
            logger.error(f"Directory {output_dir} is not writable: {str(e)}")
            return jsonify({
                'success': False,
                'message': f'Download directory is not writable: {str(e)}'
            })
            
        safe_output_template = os.path.join(output_dir, f"%(title)s_{timestamp}.%(ext)s")
        
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
            direct_output = os.path.join(output_dir, f"{unique_filename}.mp4")
            base_opts['outtmpl'] = direct_output
            logger.info(f"TikTok video, using direct output: {direct_output}")

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
            logger.info("Using MP3 audio format options")
        else:
            ydl_opts = {
                **base_opts,
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            }
            logger.info("Using MP4 video format options")

        # 下载视频
        video_title = f"video_{timestamp}"  # 默认标题
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.info(f"Starting download with yt-dlp: {url}")
                info = ydl.extract_info(url, download=False)
                if info:
                    video_title = info.get('title', video_title)
                    logger.info(f"Video title: {video_title}")
                    # 清理文件名
                    safe_title = sanitize_filename(video_title)
                    logger.info(f"Sanitized title: {safe_title}")
                    
                    # 更新输出模板使用安全的文件名
                    if format_type == 'mp3':
                        ydl_opts['outtmpl'] = os.path.join(output_dir, f"{safe_title}_{timestamp}.%(ext)s")
                        logger.info(f"Updated output template for MP3: {ydl_opts['outtmpl']}")
                    elif platform != "tiktok":  # TikTok已经有特殊处理
                        ydl_opts['outtmpl'] = os.path.join(output_dir, f"{safe_title}_{timestamp}.%(ext)s")
                        logger.info(f"Updated output template for MP4: {ydl_opts['outtmpl']}")
                    
                    # 执行实际下载
                    logger.info("Starting actual download...")
                    ydl = yt_dlp.YoutubeDL(ydl_opts)
                    ydl.download([url])
                    
                    # 检查下载后文件是否存在
                    expected_files = []
                    if format_type == 'mp3':
                        expected_files.append(os.path.join(output_dir, f"{safe_title}_{timestamp}.mp3"))
                    elif platform == "tiktok":
                        expected_files.append(direct_output)
                    else:
                        expected_files.append(os.path.join(output_dir, f"{safe_title}_{timestamp}.mp4"))
                    
                    # 还可以检查输出目录中是否有新文件
                    new_files = []
                    for filename in os.listdir(output_dir):
                        if str(timestamp) in filename:
                            file_path = os.path.join(output_dir, filename)
                            if os.path.isfile(file_path):
                                new_files.append(file_path)
                                logger.info(f"Found downloaded file: {file_path}")
                    
                    if new_files:
                        with progress_lock:
                            download_progress['status'] = 'finished'
                            download_progress['percent'] = '100.0%'
                            download_progress['message'] = f'Downloaded: {safe_title}'
                        return jsonify({
                            'success': True,
                            'message': f'Video "{safe_title}" downloaded successfully'
                        })
                    else:
                        logger.error(f"No files found in {output_dir} after download. Expected files: {expected_files}")
                        # 列出目录内容
                        logger.error(f"Directory contents: {os.listdir(output_dir)}")
                        with progress_lock:
                            download_progress['status'] = 'error'
                            download_progress['message'] = 'Download failed: No files found after download'
                        return jsonify({
                            'success': False,
                            'message': 'Download failed: No files found after download'
                        })
                else:
                    logger.error("Failed to extract video info")
                    with progress_lock:
                        download_progress['status'] = 'error'
                        download_progress['message'] = 'Failed to extract video info'
                    return jsonify({
                        'success': False,
                        'message': 'Failed to extract video info'
                    })
        except Exception as e:
            logger.error(f"Error during download: {str(e)}")
            with progress_lock:
                download_progress['status'] = 'error'
                download_progress['message'] = f'Download error: {str(e)}'
            return jsonify({
                'success': False,
                'message': f'Download error: {str(e)}'
            })
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Unexpected error: {str(e)}'
        })

@app.route('/progress')
def get_progress():
    with progress_lock:
        return jsonify(download_progress)

@app.route('/download_file/<filename>')
def download_file(filename):
    try:
        # 对文件名进行解码，确保正确处理特殊字符
        decoded_filename = unquote(filename)
        file_path = os.path.join(DOWNLOAD_FOLDER, decoded_filename)
        
        logger.info(f"Request to download file: {file_path}")
        
        # 检查文件是否存在
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return "File not found", 404
            
        # 使用Flask的send_file函数提供文件下载
        logger.info(f"Sending file: {file_path}")
        return send_file(file_path, as_attachment=True)
    except Exception as e:
        logger.error(f"Error downloading file: {str(e)}")
        return str(e), 500

@app.route('/delete/<filename>', methods=['POST'])
def delete_file(filename):
    try:
        # 对文件名进行解码，确保正确处理特殊字符
        decoded_filename = unquote(filename)
        file_path = os.path.join(DOWNLOAD_FOLDER, decoded_filename)
        
        logger.info(f"Request to delete file: {file_path}")
        
        # 检查文件是否存在
        if not os.path.exists(file_path):
            logger.warning(f"Attempting to delete non-existent file: {file_path}")
            return jsonify({
                'success': False,
                'message': 'File does not exist'
            })
        
        # 尝试删除文件
        os.remove(file_path)
        logger.info(f"File deleted successfully: {file_path}")
        
        return jsonify({
            'success': True,
            'message': 'File deleted successfully'
        })
    except Exception as e:
        logger.error(f"Error deleting file: {str(e)}")
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