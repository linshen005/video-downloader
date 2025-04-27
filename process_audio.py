import librosa
import soundfile as sf
import numpy as np

def create_speed_variants():
    print("开始处理音频文件...")
    
    # 加载原始音频
    try:
        y, sr = librosa.load('chipi.wav')
        print(f"原始音频加载成功，采样率: {sr}")
        
        # 创建不同速度的版本
        speeds = [0.8, 1.0, 1.2, 1.5, 1.8, 2.0, 2.3, 2.5]
        for speed in speeds:
            print(f"正在生成 {speed}x 速度的版本...")
            # 使用 librosa 的时间拉伸
            y_fast = librosa.effects.time_stretch(y=y, rate=speed)
            # 保存新的音频文件
            sf.write(f'chipi_{speed:.1f}x.wav', y_fast, sr)
            print(f"已保存 chipi_{speed:.1f}x.wav")
            
        print("所有音频文件处理完成！")
        return True
        
    except Exception as e:
        print(f"处理音频时出错: {e}")
        return False

if __name__ == "__main__":
    create_speed_variants() 