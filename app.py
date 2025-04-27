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
        logger.info(f"下载请求收到, URL: {url}, 格式: {format_type}")

        # 检查目标平台
        platform = "unknown"
        if "tiktok.com" in url:
            platform = "tiktok"
            logger.info("检测到TikTok URL")
        elif "youtube.com" in url or "youtu.be" in url:
            platform = "youtube"
            logger.info("检测到YouTube URL")
        elif "bilibili.com" in url:
            platform = "bilibili"
            logger.info("检测到Bilibili URL")
        
        # 确保下载目录存在
        if not os.path.exists(DOWNLOAD_FOLDER):
            logger.info(f"创建下载目录: {DOWNLOAD_FOLDER}")
            os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
        
        # 显示当前目录和下载目录
        logger.info(f"当前工作目录: {os.getcwd()}")
        logger.info(f"下载目录: {DOWNLOAD_FOLDER}")
        logger.info(f"下载目录是否存在: {os.path.exists(DOWNLOAD_FOLDER)}")
        logger.info(f"下载目录权限: {oct(os.stat(DOWNLOAD_FOLDER).st_mode)[-3:]}")

        # 测试临时文件写入和读取
        try:
            test_file_path = os.path.join(DOWNLOAD_FOLDER, f"test_file_{int(time.time())}.txt")
            with open(test_file_path, 'w') as f:
                f.write('Test content')
            logger.info(f"成功创建测试文件: {test_file_path}")
            
            with open(test_file_path, 'r') as f:
                content = f.read()
            logger.info(f"成功读取测试文件内容: {content}")
            
            os.remove(test_file_path)
            logger.info(f"成功删除测试文件")
        except Exception as e:
            logger.error(f"测试文件操作失败: {str(e)}")
            return jsonify({
                'success': False,
                'message': f'无法写入下载目录: {str(e)}'
            })

        # 检查FFMPEG路径
        ffmpeg_exec = os.path.join(FFMPEG_PATH, 'ffmpeg')
        logger.info(f"FFmpeg路径: {ffmpeg_exec}")
        logger.info(f"FFmpeg是否存在: {os.path.exists(ffmpeg_exec)}")
        
        if not os.path.exists(ffmpeg_exec):
            logger.error(f"未找到FFmpeg: {ffmpeg_exec}")
            return jsonify({
                'success': False,
                'message': f'未找到FFmpeg。请检查安装。'
            })

        # 下载前重置进度
        with progress_lock:
            download_progress['status'] = 'downloading'
            download_progress['percent'] = '0.0%'
            download_progress['message'] = '开始下载...'

        # 文件名处理函数
        def sanitize_filename(filename):
            if not filename:
                return f"video_{int(time.time())}"
            
            # 移除非法字符
            s = re.sub(r'[\\/*?:"<>|]', "", filename)
            # 替换空格为下划线
            s = re.sub(r'\s+', '_', s)
            # 移除前后的点和空格
            s = s.strip('. ')
            # 移除其他潜在问题字符
            s = re.sub(r'[^\w\.-]', '_', s)
            # 截断长文件名
            if len(s) > 50:  # 更短的长度限制
                s = s[:47] + "..."
            # 如果文件名为空，使用时间戳
            return s if s else f"video_{int(time.time())}"

        # 生成唯一的时间戳
        timestamp = int(time.time())
        
        # 使用绝对路径
        output_dir = os.path.abspath(DOWNLOAD_FOLDER)
        logger.info(f"下载目录(绝对路径): {output_dir}")
        
        # 对于TikTok视频，使用更简单的文件名
        filename_base = f"video_{timestamp}"
        if platform == "tiktok":
            filename_base = f"tiktok_{timestamp}"
        elif platform == "youtube":
            filename_base = f"youtube_{timestamp}"
        elif platform == "bilibili":
            filename_base = f"bilibili_{timestamp}"
            
        # 确定最终文件名
        final_filename = f"{filename_base}.{format_type}"
        output_file = os.path.join(output_dir, final_filename)
        logger.info(f"输出文件: {output_file}")
        
        # 使用临时目录下载
        with tempfile.TemporaryDirectory() as temp_dir:
            logger.info(f"创建临时目录: {temp_dir}")
            
            # 设置临时输出路径
            temp_output = os.path.join(temp_dir, f"temp_output.{format_type}")
            logger.info(f"临时输出文件: {temp_output}")
            
            # 配置yt-dlp选项
            ydl_opts = {
                'quiet': False,
                'no_warnings': False,
                'outtmpl': temp_output,
                'ffmpeg_location': FFMPEG_PATH,
                'progress_hooks': [progress_hook],
                'verbose': True,
            }
            
            if format_type == 'mp3':
                ydl_opts.update({
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                })
                # 对于mp3，修改临时输出路径
                temp_output = os.path.join(temp_dir, "temp_output.mp3")
                logger.info(f"修正的MP3临时输出: {temp_output}")
            else:
                ydl_opts.update({
                    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                })
            
            try:
                # 下载视频
                logger.info(f"开始下载: {url}")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info_dict = ydl.extract_info(url, download=True)
                    if info_dict:
                        # 提取视频标题
                        original_title = info_dict.get('title', filename_base)
                        logger.info(f"视频标题: {original_title}")
                        safe_title = sanitize_filename(original_title)
                        logger.info(f"安全的标题: {safe_title}")
                        
                        # 更新最终文件名
                        final_filename = f"{safe_title}.{format_type}"
                        output_file = os.path.join(output_dir, final_filename)
                        
                        # 检查临时文件是否存在
                        if not os.path.exists(temp_output):
                            actual_temp_file = None
                            # 查找实际下载的文件
                            for file in os.listdir(temp_dir):
                                logger.info(f"临时目录中的文件: {file}")
                                if os.path.isfile(os.path.join(temp_dir, file)):
                                    actual_temp_file = os.path.join(temp_dir, file)
                                    break
                            
                            if actual_temp_file:
                                logger.info(f"找到实际下载的文件: {actual_temp_file}")
                                temp_output = actual_temp_file
                            else:
                                raise Exception("下载失败，临时目录中未找到文件")
                        
                        # 检查文件大小
                        file_size = os.path.getsize(temp_output)
                        logger.info(f"下载的文件大小: {file_size/1024/1024:.2f} MB")
                        
                        if file_size == 0:
                            raise Exception("下载的文件大小为0")
                        
                        # 确保输出目录存在
                        os.makedirs(output_dir, exist_ok=True)
                        
                        # 将文件复制到最终位置
                        logger.info(f"将文件从 {temp_output} 复制到 {output_file}")
                        with open(temp_output, 'rb') as src_file:
                            with open(output_file, 'wb') as dest_file:
                                dest_file.write(src_file.read())
                        
                        # 验证最终文件存在
                        if os.path.exists(output_file):
                            logger.info(f"成功创建最终文件: {output_file}")
                            final_size = os.path.getsize(output_file)
                            logger.info(f"最终文件大小: {final_size/1024/1024:.2f} MB")
                            
                            with progress_lock:
                                download_progress['status'] = 'finished'
                                download_progress['percent'] = '100.0%'
                                download_progress['message'] = f'下载完成: {safe_title}'
                            
                            return jsonify({
                                'success': True,
                                'message': f'下载成功: {safe_title}',
                                'file': {
                                    'name': final_filename,
                                    'size': f"{final_size/1024/1024:.2f} MB"
                                }
                            })
                        else:
                            raise Exception(f"无法创建最终文件: {output_file}")
                    else:
                        raise Exception("无法获取视频信息")
            except Exception as e:
                logger.error(f"下载过程中出错: {str(e)}")
                with progress_lock:
                    download_progress['status'] = 'error'
                    download_progress['message'] = f'下载错误: {str(e)}'
                return jsonify({
                    'success': False,
                    'message': f'下载错误: {str(e)}'
                })
    except Exception as e:
        logger.error(f"意外错误: {str(e)}")
        with progress_lock:
            download_progress['status'] = 'error'
            download_progress['message'] = f'下载错误: {str(e)}'
        return jsonify({
            'success': False,
            'message': f'意外错误: {str(e)}'
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