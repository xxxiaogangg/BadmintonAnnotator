# file: core/video_worker.py

import cv2
import time
from PyQt6.QtCore import QObject, pyqtSignal, QThread, pyqtSlot
from PyQt6.QtGui import QImage

class VideoWorker(QObject):
    """
    在后台线程中处理所有视频相关操作的高性能Worker。
    独立于主线程，确保UI永不卡顿。
    """
    # --- 信号定义 ---
    # 视频成功加载后发出，传递视频信息给主线程
    video_loaded = pyqtSignal(int, float) # total_frames, fps
    
    # 每处理好一帧图像后发出
    frame_ready = pyqtSignal(int, QImage) # frame_number, image
    
    # 发生错误时发出
    error = pyqtSignal(str)

    # 结束时发出
    finished = pyqtSignal()

    def __init__(self, video_path):
        super().__init__()
        self.video_path = video_path
        self.cap = None
        
        # --- 状态控制变量 ---
        self.is_running = True  # 控制整个线程的生命周期
        self.is_playing = False # 控制播放/暂停
        
        # --- 播放控制变量 ---
        self.target_size = None # 由主线程设置的目标显示尺寸
        self.frame_to_seek = -1 # -1表示不跳转，否则为目标帧号
        self.playback_rate = 1.0 # 播放速率，1.0为正常速度

    def run(self):
        self.cap = cv2.VideoCapture(self.video_path)
        if not self.cap.isOpened():
            self.error.emit(f"无法打开视频文件: {self.video_path}")
            self.finished.emit()
            return

        total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        if fps == 0:
            fps = 30
        
        self.video_loaded.emit(total_frames, fps)
        
        frame_interval_ms = 1000 / fps

        while self.is_running:
            # <<< ================== 核心逻辑重构开始 ================== >>>
            
            # 1. 优先处理跳转请求，无论播放还是暂停
            if self.frame_to_seek >= 0:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.frame_to_seek)
                ret, frame = self.cap.read()
                if ret:
                    # 读取并发送跳转后的那一帧
                    current_frame_num = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES)) -1 # cap.get reports the *next* frame
                    self.process_and_emit_frame(frame, current_frame_num)
                
                self.frame_to_seek = -1 # 完成跳转，重置标志

            # 2. 如果当前是暂停状态，并且没有跳转请求，则休眠
            if not self.is_playing:
                QThread.msleep(20)
                continue

            # 3. 如果是播放状态，则执行正常的播放循环
            loop_start_time = time.time()
            
            ret, frame = self.cap.read()
            if not ret:
                self.is_playing = False
                continue

            current_frame_num = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES)) -1
            self.process_and_emit_frame(frame, current_frame_num)

            processing_time_ms = (time.time() - loop_start_time) * 1000
            # 根据播放速率调整休眠时间
            sleep_time = int((frame_interval_ms / self.playback_rate) - processing_time_ms)
            if sleep_time > 0:
                QThread.msleep(sleep_time)

            # <<< ================== 核心逻辑重构结束 ================== >>>

        self.cap.release()
        print("Video worker thread finished, emitting finished signal.")
        self.finished.emit()

    def process_and_emit_frame(self, frame, frame_num):
        """一个辅助函数，用于处理和发送帧，避免代码重复"""
        if self.target_size:
            frame = cv2.resize(frame, self.target_size, interpolation=cv2.INTER_AREA)
        
        rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_image.shape
        bytes_per_line = ch * w
        qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        
        self.frame_ready.emit(frame_num, qt_image)

    # --- 以下是供主线程调用的槽函数 ---
    @pyqtSlot(bool)
    def set_playing(self, playing):
        """设置播放状态"""
        self.is_playing = playing

    @pyqtSlot()
    def stop(self):
        """停止线程循环"""
        self.is_running = False

    @pyqtSlot(int)
    def seek(self, frame_num):
        """跳转到指定帧"""
        self.frame_to_seek = frame_num

    @pyqtSlot(int, int)
    def set_target_size(self, width, height):
        """设置视频帧的目标缩放尺寸"""
        if width > 0 and height > 0:
            self.target_size = (width, height)

    @pyqtSlot(float)
    def set_playback_rate(self, rate):
        """设置播放速率"""
        if rate > 0:
            self.playback_rate = rate