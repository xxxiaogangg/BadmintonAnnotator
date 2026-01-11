# file: core/video_worker.py

import cv2
import time
import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal, QThread, pyqtSlot, QMutex, QMutexLocker

class VideoWorker(QObject):
    """
    在后台线程中处理所有视频相关操作的高性能Worker。
    独立于主线程，确保UI永不卡顿。
    
    重要：严格遵守跨线程GUI编程规则
    - 后台线程只处理数据和计算，绝不创建任何GUI对象（如QImage）
    - 所有GUI对象的创建和操作都在主线程完成
    """
    # --- 信号定义 ---
    # 视频成功加载后发出，传递视频信息给主线程
    video_loaded = pyqtSignal(int, float) # total_frames, fps
    
    # 每处理好一帧图像后发出（只传递原始numpy数组数据，不传递GUI对象）
    # 参数：frame_number, numpy_array (RGB格式), width, height
    frame_ready = pyqtSignal(int, object, int, int) # frame_number, rgb_array, width, height
    
    # 发生错误时发出
    error = pyqtSignal(str)

    # 播放到末尾时发出（线程仍可继续运行）
    playback_finished = pyqtSignal(int)

    # 结束时发出
    finished = pyqtSignal()

    def __init__(self, video_path):
        super().__init__()
        self.video_path = video_path
        self.cap = None
        self.state_lock = QMutex()
        
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

        while True:
            with QMutexLocker(self.state_lock):
                is_running = self.is_running
                is_playing = self.is_playing
                frame_to_seek = self.frame_to_seek
                playback_rate = self.playback_rate
                target_size = self.target_size

            if not is_running:
                break

            # 1. 优先处理跳转请求，无论播放还是暂停
            if frame_to_seek >= 0:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_to_seek)
                ret, frame = self.cap.read()
                if ret:
                    # 读取并发送跳转后的那一帧
                    current_frame_num = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES)) -1 # cap.get reports the *next* frame
                    self.process_and_emit_frame(frame, current_frame_num, target_size)

                with QMutexLocker(self.state_lock):
                    if self.frame_to_seek == frame_to_seek:
                        self.frame_to_seek = -1 # 完成跳转，重置标志

            # 2. 如果当前是暂停状态，并且没有跳转请求，则休眠
            if not is_playing:
                QThread.msleep(20)
                continue

            # 3. 如果是播放状态，则执行正常的播放循环
            loop_start_time = time.time()
            
            ret, frame = self.cap.read()
            if not ret:
                with QMutexLocker(self.state_lock):
                    self.is_playing = False
                self.playback_finished.emit(max(0, total_frames - 1))
                continue

            current_frame_num = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES)) -1
            self.process_and_emit_frame(frame, current_frame_num, target_size)

            processing_time_ms = (time.time() - loop_start_time) * 1000
            # 根据播放速率调整休眠时间
            sleep_time = int((frame_interval_ms / playback_rate) - processing_time_ms)
            QThread.msleep(max(1, sleep_time))

        self.cap.release()
        print("Video worker thread finished, emitting finished signal.")
        self.finished.emit()

    def process_and_emit_frame(self, frame, frame_num, target_size):
        """
        一个辅助函数，用于处理和发送帧，避免代码重复。
        
        重要：严格遵守跨线程GUI编程规则
        - 不在后台线程创建任何GUI对象（如QImage）
        - 只发送原始numpy数组数据，由主线程负责创建GUI对象
        """
        if target_size:
            frame = cv2.resize(frame, target_size, interpolation=cv2.INTER_AREA)
        
        # 转换为RGB格式（OpenCV默认是BGR）
        rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # 确保数据是连续的（在某些操作后可能不连续）
        if not rgb_image.flags['C_CONTIGUOUS']:
            rgb_image = rgb_image.copy()
        
        h, w = rgb_image.shape[:2]
        
        # 【关键修复】只发送numpy数组数据，不创建QImage
        # QImage的创建必须在主线程完成，这是跨平台兼容性的关键
        # 使用.copy()确保发送的是独立的数据副本，避免内存共享问题
        self.frame_ready.emit(frame_num, rgb_image.copy(), w, h)

    # --- 以下是供主线程调用的槽函数 ---
    @pyqtSlot(bool)
    def set_playing(self, playing):
        """设置播放状态"""
        with QMutexLocker(self.state_lock):
            self.is_playing = playing

    @pyqtSlot()
    def stop(self):
        """停止线程循环"""
        with QMutexLocker(self.state_lock):
            self.is_running = False

    @pyqtSlot(int)
    def seek(self, frame_num):
        """跳转到指定帧"""
        with QMutexLocker(self.state_lock):
            self.frame_to_seek = frame_num

    @pyqtSlot(int, int)
    def set_target_size(self, width, height):
        """设置视频帧的目标缩放尺寸"""
        if width > 0 and height > 0:
            with QMutexLocker(self.state_lock):
                self.target_size = (width, height)

    @pyqtSlot(float)
    def set_playback_rate(self, rate):
        """设置播放速率"""
        if rate > 0:
            with QMutexLocker(self.state_lock):
                self.playback_rate = rate
