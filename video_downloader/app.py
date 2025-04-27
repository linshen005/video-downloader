from flask import Flask, render_template, request, jsonify, send_file
from urllib.parse import unquote
import yt_dlp
import os
import logging
from datetime import datetime
import subprocess

app = Flask(__name__)

# 设置日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# 确保下载目录存在
DOWNLOAD_FOLDER = 'downloads'
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

FFMPEG_PATH = os.path.expanduser('~/ffmpeg')  # 只指定目录
FFPROBE_PATH = os.path.expanduser('~/ffmpeg/ffprobe')

def check_ffmpeg():
    ffmpeg_path = os.path.join(FFMPEG_PATH, 'ffmpeg')
    ffprobe_path = os.path.join(FFMPEG_PATH, 'ffprobe')
    
    if not os.path.exists(ffmpeg_path) or not os.path.exists(ffprobe_path):
        logger.error("FFmpeg or FFprobe not found!")
        return False
    
    try:
        subprocess.run([ffmpeg_path, '-version'], capture_output=True)
        subprocess.run([ffprobe_path, '-version'], capture_output=True)
        logger.info("FFmpeg and FFprobe are working correctly")
        return True
    except Exception as e:
        logger.error(f"FFmpeg check failed: {e}")
        return False

def get_file_info(filename):
    """获取文件信息"""
    file_path = os.path.join(DOWNLOAD_FOLDER, filename)
    file_stats = os.stat(file_path)
    size_mb = file_stats.st_size / (1024 * 1024)  # 转换为MB
    modified_time = datetime.fromtimestamp(file_stats.st_mtime)
    
    return {
        'name': filename,
        'size': f'{size_mb:.2f} MB',
        'modified': modified_time.strftime('%Y-%m-%d %H:%M:%S'),
        'path': file_path
    }

@app.route('/')
def home():
    try:
        # 获取下载文件夹中的所有文件
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

@app.route('/download', methods=['POST'])
def download_video():
    try:
        url = unquote(request.form['url'])
        format_type = request.form.get('format', 'mp4')
        logger.info(f"Download request received, URL: {url}, Format: {format_type}")

        # 检查 ffmpeg 是否存在
        ffmpeg_exec = os.path.join(FFMPEG_PATH, 'ffmpeg')
        ffprobe_exec = os.path.join(FFMPEG_PATH, 'ffprobe')
        
        if not os.path.exists(ffmpeg_exec) or not os.path.exists(ffprobe_exec):
            return jsonify({
                'success': False,
                'message': 'FFmpeg not found. Please check installation.'
            })

        # 基础选项
        base_opts = {
            'quiet': False,
            'no_warnings': False,
            'outtmpl': f'{DOWNLOAD_FOLDER}/%(title)s.%(ext)s',
            'ffmpeg_location': FFMPEG_PATH,
        }

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

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.info("Getting video information...")
            info = ydl.extract_info(url, download=False)
            video_title = info.get('title', None)
            
            logger.info(f"Starting download: {video_title}")
            ydl.download([url])
            
            files = [f for f in os.listdir(DOWNLOAD_FOLDER) 
                    if os.path.isfile(os.path.join(DOWNLOAD_FOLDER, f))]
            latest_file = max(files, key=lambda x: os.path.getctime(os.path.join(DOWNLOAD_FOLDER, x)))
            
            return jsonify({
                'success': True,
                'message': f"{'Audio' if format_type == 'mp3' else 'Video'} '{video_title}' downloaded successfully!",
                'file': {
                    'name': latest_file,
                    'size': f"{os.path.getsize(os.path.join(DOWNLOAD_FOLDER, latest_file)) / (1024*1024):.2f} MB"
                }
            })

    except Exception as e:
        logger.error(f"Download failed: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f"Download failed: {str(e)}"
        })

@app.route('/delete/<filename>', methods=['POST'])
def delete_file(filename):
    try:
        file_path = os.path.join(DOWNLOAD_FOLDER, filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            return jsonify({'success': True, 'message': f'File {filename} has been deleted'})
        return jsonify({'success': False, 'message': 'File does not exist'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/download_file/<filename>')
def download_file(filename):
    try:
        return send_file(os.path.join(DOWNLOAD_FOLDER, filename), as_attachment=True)
    except Exception as e:
        return str(e), 404

if __name__ == '__main__':
    if not check_ffmpeg():
        print("Error: FFmpeg is not properly installed or configured")
        print("Please make sure FFmpeg is installed in ~/ffmpeg/")
        exit(1)
    logger.info(f"FFmpeg path: {FFMPEG_PATH}")
    logger.info(f"FFmpeg exists: {os.path.exists(os.path.join(FFMPEG_PATH, 'ffmpeg'))}")
    logger.info(f"FFprobe exists: {os.path.exists(os.path.join(FFMPEG_PATH, 'ffprobe'))}")
    app.run(debug=True, port=5000, host='0.0.0.0') 