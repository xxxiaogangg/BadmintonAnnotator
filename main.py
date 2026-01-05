# file: main.py

import sys
import uuid
import cv2
import os
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                             QPushButton, QSlider, QFileDialog, QGroupBox, QTreeWidget, QTreeWidgetItem,
                             QListWidget, QMenuBar, QMenu, QListWidgetItem, QDialog, QCheckBox)  # Add QListWidgetItem
from PyQt6.QtGui import QPixmap, QImage, QAction, QKeySequence, QShortcut, QIntValidator
from PyQt6.QtCore import Qt, QThread, QRect, QPoint, QTimer, QEvent
from PyQt6.QtWidgets import (QLabel, QSplitter, QComboBox, QMessageBox, QTreeWidgetItem,
                             QTreeWidgetItemIterator, QAbstractItemView, QStackedWidget, QLineEdit)

from core.video_worker import VideoWorker
from widgets.drawing_label import DrawingLabel, TechniqueSelectionDialog
from widgets.match_setup_dialog import MatchSetupDialog # 导入新对话框
from widgets.serve_player_dialog import ServePlayerDialog, WinnerSelectionDialog
from core.data_model import get_new_annotation_structure

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("羽毛球技战术分析工具 v2.0")
        self.setGeometry(100, 100, 1600, 900)

        # --- 核心变量 ---
        self.video_worker = None
        self.video_thread = None
        self.annotations = {}
        self.current_frame_num = -1
        self.selected_object_id = None # 新增：跟踪当前选中的对象ID
        self._is_selecting_programmatically = False # 新增：防止信号循环的标志
        self._tech_dialog_open = False # 防抖：防止技术动作对话框重复打开
        self.last_selected_event_id = None # 跟踪最后选中的事件ID，用于连续调整
        self.play_a_name = ""
        self.play_b_name = ""
        self.shot_loop_enabled = False
        self.shot_loop_bounds = None
        # 审阅相关
        self.event_items = {}  # event_id -> QTreeWidgetItem，用于导航和审阅
        self.review_index_map = {
            "待定": -1,
            "不适用": -1,
            "视角异常": -1,
            "击球缺帧": -1,
            "非常规动作": -1,
        }  # 当前在各自序列中的位置

        # 自动保存
        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.autosave_annotations)
        self.data_is_dirty = False # 标志位，判断数据是否被修改过

        # self._create_menu_bar()
        QApplication.instance().installEventFilter(self)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus) # 确保主窗口能接收焦点
        self._create_menu_bar()
        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        main_layout = QHBoxLayout(main_widget)
        left_panel = self._create_left_panel()

        # 创建右侧多页面面板（通过下拉框切换）
        right_panel = self._create_right_panel()

        # 将左右两大块添加到主布局
        main_layout.addWidget(left_panel, 3)      # 左侧视频区，比例为3
        main_layout.addWidget(right_panel, 1)     # 右侧整个工具区，比例为1

    def _create_menu_bar(self):
        menu_bar = self.menuBar()
        
        # --- 文件菜单 ---
        file_menu = menu_bar.addMenu("&文件")
        open_action = QAction("&打开视频...", self)
        open_action.triggered.connect(self.open_video_file)
        file_menu.addAction(open_action)
        
        save_action = QAction("&保存标注...", self)
        save_action.setShortcut("Ctrl+S") # 添加快捷键提示
        save_action.triggered.connect(self.save_annotations)
        file_menu.addAction(save_action)
        # 为 Ctrl+S 添加真正的快捷键
        QShortcut(QKeySequence("Ctrl+S"), self, self.save_annotations)

        load_action = QAction("&加载标注...", self)
        load_action.setShortcut("Ctrl+O") # O for Open
        load_action.triggered.connect(self.load_annotations)
        file_menu.addAction(load_action)
        QShortcut(QKeySequence("Ctrl+O"), self, self.load_annotations)

        # --- 编辑菜单 ---
        edit_menu = menu_bar.addMenu("&编辑")
        delete_action = QAction("删除选中事件", self)
        delete_action.setShortcut("Delete")
        delete_action.triggered.connect(self.delete_selected_event)
        edit_menu.addAction(delete_action)

        # --- 播放菜单 ---
        playback_menu = menu_bar.addMenu("&播放")
        play_pause_action = QAction("播放/暂停", self)
        # play_pause_action.setShortcut("Space")
        play_pause_action.triggered.connect(self.toggle_play_pause)
        playback_menu.addAction(play_pause_action)
        
        # ... 可以添加更多播放相关的菜单项 ...
        
        # --- 标注菜单 ---
        annotation_menu = menu_bar.addMenu("&标注")
        set_start_action = QAction("局开始", self)
        set_start_action.setShortcut("S")
        set_start_action.triggered.connect(self.add_set_start_event)
        annotation_menu.addAction(set_start_action)

    def _create_left_panel(self):
        left_widget = QWidget()
        layout = QVBoxLayout(left_widget)
        layout.setContentsMargins(0,0,0,0)

        self.video_label = DrawingLabel()
        self.video_label.setStyleSheet("background-color: black;")
        
        self.video_label.new_rect_drawn.connect(self.add_new_box_annotation)
        self.video_label.new_point_drawn.connect(self.add_new_point_annotation)
        # <<< ================== 核心修改 1: 连接编辑信号 ================== >>>
        self.video_label.object_selected.connect(self.on_object_selected_from_canvas)
        self.video_label.object_moved.connect(self.on_object_moved)
        
        layout.addWidget(self.video_label, 1)

        # --- 控制区 ---
        controls_widget = QWidget()
        # 使用垂直布局容纳两排控制
        controls_layout = QVBoxLayout(controls_widget)

        # --- 上排：进度条 ---
        slider_layout = QHBoxLayout()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.time_label = QLabel("00:00:00 / 00:00:00") # 添加时间标签
        slider_layout.addWidget(self.slider, 1)
        slider_layout.addWidget(self.time_label)
        
        # --- 下排：按钮 ---
        buttons_layout = QHBoxLayout()
        
        # 帧步进
        self.step_back_btn = QPushButton("<<")
        self.step_forward_btn = QPushButton(">>")
        self.step_interval_combo = QComboBox()
        self.step_intervals = {"1 帧": 1, "10 帧": 10, "1 秒": 30, "5 秒": 150} # 帧数会动态更新
        self.step_interval_combo.addItems(self.step_intervals.keys())

        # 播放/暂停
        self.play_pause_btn = QPushButton("▶ 播放")
        
        # 倍速
        self.rate_label = QLabel("速度:")
        self.rate_combo = QComboBox()
        self.playback_rates = {"0.5x": 0.5, "1.0x": 1.0, "2.0x": 2.0, "4.0x": 4.0}
        self.rate_combo.addItems(self.playback_rates.keys())
        self.rate_combo.setCurrentText("1.0x")

        buttons_layout.addStretch()
        buttons_layout.addWidget(self.step_back_btn)
        buttons_layout.addWidget(self.step_interval_combo)
        buttons_layout.addWidget(self.step_forward_btn)
        buttons_layout.addSpacing(50)
        buttons_layout.addWidget(self.play_pause_btn)
        buttons_layout.addSpacing(50)
        buttons_layout.addWidget(self.rate_label)
        buttons_layout.addWidget(self.rate_combo)
        buttons_layout.addStretch()

        controls_layout.addLayout(slider_layout)
        controls_layout.addLayout(buttons_layout)
        layout.addWidget(controls_widget)

        # --- 连接信号 ---
        self.slider.sliderMoved.connect(self.seek_video)
        self.play_pause_btn.clicked.connect(self.toggle_play_pause)
        self.step_back_btn.clicked.connect(lambda: self.step_frames(forward=False))
        self.step_forward_btn.clicked.connect(lambda: self.step_frames(forward=True))
        self.rate_combo.currentTextChanged.connect(self.on_rate_changed)
        # --- 添加快捷键（如果之前有的话，可在此恢复）---
        # self._create_shortcuts()

        return left_widget

    def _create_right_panel(self):
        """创建右侧多功能面板，通过下拉框切换不同页面"""
        right_widget = QWidget()
        layout = QVBoxLayout(right_widget)
        layout.setContentsMargins(5, 5, 5, 5)

        # 顶部：页面选择下拉框
        switch_layout = QHBoxLayout()
        switch_label = QLabel("右侧页面：")
        self.right_page_combo = QComboBox()
        self.right_page_combo.addItems(["球与运动员", "标注击球事件", "击球事件审阅", "AI辅助"])
        self.right_page_combo.setMaximumWidth(180)
        self.right_page_combo.currentIndexChanged.connect(self.on_right_page_changed)
        self.shot_loop_toggle = QCheckBox("击球循环")
        self.shot_loop_toggle.setToolTip("开启后，在两次击球之间循环播放")
        self.shot_loop_toggle.toggled.connect(self.on_shot_loop_toggled)
        switch_layout.addWidget(switch_label)
        switch_layout.addWidget(self.right_page_combo)
        switch_layout.addWidget(self.shot_loop_toggle)
        switch_layout.addStretch()
        layout.addLayout(switch_layout)

        # 中部：堆叠窗口，放置不同功能页面
        self.right_stacked = QStackedWidget()

        # 页面0：球与运动员（沿用原来的右上面板）
        page_objects = QWidget()
        page_objects_layout = QVBoxLayout(page_objects)
        page_objects_layout.setContentsMargins(0, 0, 0, 0)
        page_objects_layout.addWidget(self._create_top_right_panel())
        self.right_stacked.addWidget(page_objects)

        # 页面1：击球事件（沿用原来的右下面板）
        page_events = QWidget()
        page_events_layout = QVBoxLayout(page_events)
        page_events_layout.setContentsMargins(0, 0, 0, 0)
        page_events_layout.addWidget(self._create_bottom_right_panel())
        self.right_stacked.addWidget(page_events)

        # 页面2：击球事件审阅
        page_review = QWidget()
        page_review_layout = QVBoxLayout(page_review)

        # 审阅统计与跳转控制
        self.review_box = QGroupBox("击球事件审阅")
        review_layout = QVBoxLayout(self.review_box)

        # 统计信息（分两行：待定一行，不适用一行）
        self.review_pending_label = QLabel("待定:0 | 不适用:0 | 视角异常:0 | 击球缺帧:0 | 非常规动作:0")
        self.review_na_label = QLabel("当前位置: 0/0")
        review_layout.addWidget(self.review_pending_label)
        review_layout.addWidget(self.review_na_label)

        # 审阅跳转控制
        review_filter_layout = QHBoxLayout()
        self.review_filter_combo = QComboBox()
        self.review_filter_combo.addItems(["待定", "不适用", "视角异常", "击球缺帧", "非常规动作"])
        self.review_filter_combo.currentIndexChanged.connect(self._update_review_position_label)
        self.review_prev_btn = QPushButton("上一个")
        self.review_next_btn = QPushButton("下一个")
        review_filter_layout.addWidget(self.review_filter_combo, 1)
        review_filter_layout.addWidget(self.review_prev_btn)
        review_filter_layout.addWidget(self.review_next_btn)
        review_layout.addLayout(review_filter_layout)

        review_jump_layout = QHBoxLayout()
        review_jump_label = QLabel("跳转到帧:")
        self.review_jump_input = QLineEdit()
        self.review_jump_input.setPlaceholderText("帧号")
        self.review_jump_input.setFixedWidth(80)
        self.review_jump_validator = QIntValidator(0, 0, self)
        self.review_jump_input.setValidator(self.review_jump_validator)
        self.review_jump_btn = QPushButton("跳转")
        review_jump_layout.addWidget(review_jump_label)
        review_jump_layout.addWidget(self.review_jump_input)
        review_jump_layout.addWidget(self.review_jump_btn)
        review_layout.addLayout(review_jump_layout)

        # 连接按钮信号
        self.review_prev_btn.clicked.connect(
            lambda: self.navigate_review_by_filter(backward=True)
        )
        self.review_next_btn.clicked.connect(
            lambda: self.navigate_review_by_filter(backward=False)
        )
        self.review_jump_btn.clicked.connect(self.jump_to_frame_from_review)

        page_review_layout.addWidget(self.review_box)
        self.right_stacked.addWidget(page_review)

        layout.addWidget(self.right_stacked)

        # --- 通用事件浏览器（两个页面共用） ---
        events_box = QGroupBox("事件浏览器")
        events_layout = QVBoxLayout(events_box)
        self.event_tree = QTreeWidget()
        self.event_tree.setHeaderLabels(["事件", "详情"])
        self.event_tree.itemClicked.connect(self.on_event_tree_item_clicked)
        self.event_tree.itemDoubleClicked.connect(self.on_event_tree_item_double_clicked)
        events_layout.addWidget(self.event_tree)
        events_box.setLayout(events_layout)
        layout.addWidget(events_box, 1)  # 让事件树占据更多垂直空间

        # 默认显示第一个页面
        self.right_stacked.setCurrentIndex(0)
        self.right_page_combo.setCurrentIndex(0)

        return right_widget

    def on_right_page_changed(self, index: int):
        """右侧页面下拉框切换时，切换堆叠窗口页面"""
        if hasattr(self, "right_stacked") and 0 <= index < self.right_stacked.count():
            self.right_stacked.setCurrentIndex(index)

        # 在“击球事件审阅”页面时，让上方堆叠区域高度尽量贴合审阅框，
        # 这样事件浏览器就会紧贴在审阅框下方，而不是中间留一大块空白。
        if hasattr(self, "review_box"):
            if index == 2:  # 第 3 个页面：击球事件审阅
                h = self.review_box.sizeHint().height() + 20
                self.right_stacked.setMaximumHeight(h)
            else:
                # 恢复为默认最大高度
                self.right_stacked.setMaximumHeight(16777215)
   
    def _create_top_right_panel(self):
        """创建右上角的面板，用于对象标注"""
        top_right_widget = QWidget()
        layout = QVBoxLayout(top_right_widget)
        layout.setContentsMargins(5, 5, 5, 5) # 设置一些边距

        # --- 标注模式 ---
        mode_box = QGroupBox("标注模式")
        mode_layout = QHBoxLayout(mode_box)
        # ... (mode buttons code remains the same) ...
        self.btn_mode_select = QPushButton("选择/编辑")
        self.btn_mode_box = QPushButton("框选球员")
        self.btn_mode_point = QPushButton("标记羽毛球")
        # ... (checkable, setChecked, connects code remains the same) ...
        self.btn_mode_select.setCheckable(True)
        self.btn_mode_box.setCheckable(True)
        self.btn_mode_point.setCheckable(True)
        self.btn_mode_select.setChecked(True)
        self.btn_mode_select.clicked.connect(lambda: self.on_mode_button_clicked("select"))
        self.btn_mode_box.clicked.connect(lambda: self.on_mode_button_clicked("box"))
        self.btn_mode_point.clicked.connect(lambda: self.on_mode_button_clicked("point"))
        mode_layout.addWidget(self.btn_mode_select)
        mode_layout.addWidget(self.btn_mode_box)
        mode_layout.addWidget(self.btn_mode_point)
        mode_box.setLayout(mode_layout)
        layout.addWidget(mode_box)

        # --- 帧内对象 ---
        frame_objects_box = QGroupBox("当前帧标注对象")
        frame_objects_layout = QVBoxLayout(frame_objects_box)
        self.frame_objects_list = QListWidget()
        self.frame_objects_list.currentItemChanged.connect(self.on_object_selected_from_list)
        frame_objects_layout.addWidget(self.frame_objects_list)
        
        self.delete_object_btn = QPushButton("删除选中对象 (Delete)")
        self.delete_object_btn.clicked.connect(self.delete_selected_object)
        frame_objects_layout.addWidget(self.delete_object_btn)
        frame_objects_box.setLayout(frame_objects_layout)
        layout.addWidget(frame_objects_box)
        
        layout.addStretch() # 把内容推到顶部
        return top_right_widget

    def _create_bottom_right_panel(self):
        """创建右下角的面板，用于事件标注"""
        bottom_right_widget = QWidget()
        layout = QVBoxLayout(bottom_right_widget)
        layout.setContentsMargins(5, 5, 5, 5)

        # --- 比赛信息 ---
        match_info_box = QGroupBox("比赛信息")
        match_info_layout = QFormLayout(match_info_box)
        self.score_label = QLabel("未加载")
        self.player_a_label = QLabel("球员A: -")
        self.player_b_label = QLabel("球员B: -")
        match_info_layout.addRow("比分:", self.score_label)
        match_info_layout.addRow(self.player_a_label)
        match_info_layout.addRow(self.player_b_label)
        layout.addWidget(match_info_box)

        # --- 事件控制 ---
        event_control_box = QGroupBox("事件控制")
        event_control_layout = QVBoxLayout(event_control_box) 
        # ... (event buttons code remains the same) ...
        set_layout = QHBoxLayout()
        self.set_start_btn = QPushButton("局开始 (S)")
        self.set_end_btn = QPushButton("局结束 (Shift+S)")
        set_layout.addWidget(self.set_start_btn)
        set_layout.addWidget(self.set_end_btn)
        rally_layout = QHBoxLayout()
        self.rally_start_btn = QPushButton("回合开始 (R)")
        self.rally_end_btn = QPushButton("回合结束 (E)")
        rally_layout.addWidget(self.rally_start_btn)
        rally_layout.addWidget(self.rally_end_btn)
        shot_layout = QHBoxLayout()
        self.add_shot_btn = QPushButton("添加击球 (I)")
        shot_layout.addWidget(self.add_shot_btn)
        event_control_layout.addLayout(set_layout)
        event_control_layout.addLayout(rally_layout)
        event_control_layout.addLayout(shot_layout)
        # ... (connects code remains the same) ...
        self.set_start_btn.clicked.connect(self.add_set_start_event)
        self.set_end_btn.clicked.connect(self.add_set_end_event)
        self.rally_start_btn.clicked.connect(self.add_rally_start_event)
        self.rally_end_btn.clicked.connect(self.add_rally_end_event)
        self.add_shot_btn.clicked.connect(self.add_shot_event)
        layout.addWidget(event_control_box)
        
        return bottom_right_widget

    def autosave_annotations(self):
        """由定时器触发，执行自动备份"""
        # 如果数据没有被修改过，或者没有标注，则跳过
        if not self.data_is_dirty or not self.annotations:
            # print("数据无变化，跳过本次自动保存。") # 用于调试
            return

        video_path = self.annotations.get('video_info', {}).get('path')
        if not video_path: return

        # 约定自动保存文件名为: [视频文件名].autosave.json
        backup_path = video_path + ".autosave.json"
        
        try:
            with open(backup_path, 'w', encoding='utf-8') as f:
                import json
                json.dump(self.annotations, f, indent=4, ensure_ascii=False)
            
            # 状态栏提示用户
            self.statusBar().showMessage(f"已自动备份标注。", 2000) # 显示2秒
            self.data_is_dirty = False # 保存后，将数据标记为“干净”
            print(f"自动保存成功: {backup_path}")

        except Exception as e:
            print(f"自动保存失败: {e}")

    def set_dirty(self):
        """将数据标记为已修改"""
        self.data_is_dirty = True

    def step_frames(self, forward=True):
        """根据下拉框选择的步长，前进或后退帧"""
        if not self.video_worker: return
        
        interval_text = self.step_interval_combo.currentText()
        step = self.step_intervals.get(interval_text, 1) # 默认为1帧
        
        direction = 1 if forward else -1
        target_frame = self.current_frame_num + (step * direction)
        
        # 边界检查
        max_frame = self.slider.maximum()
        target_frame = max(0, min(target_frame, max_frame))
        
        self.seek_video(target_frame)

    def on_rate_changed(self, rate_text):
        """当倍速下拉框变化时，通知Worker"""
        if self.video_worker:
            rate = self.playback_rates.get(rate_text, 1.0)
            self.video_worker.set_playback_rate(rate)
            
    def update_time_label(self):
        """更新时间戳显示"""
        if not self.annotations.get('video_info'): return
        
        total_frames = self.annotations['video_info']['total_frames']
        fps = self.annotations['video_info']['fps']
        
        current_sec = self.current_frame_num / fps
        total_sec = total_frames / fps

        def format_time(seconds):
            s = int(seconds)
            h = s // 3600
            m = (s % 3600) // 60
            s = s % 60
            return f"{h:02}:{m:02}:{s:02}"

        self.time_label.setText(f"{format_time(current_sec)} / {format_time(total_sec)}")

    def on_mode_button_clicked(self, mode):
        self.video_label.set_draw_mode(mode)
        self.btn_mode_select.setChecked(mode == "select")
        self.btn_mode_box.setChecked(mode == "box")
        self.btn_mode_point.setChecked(mode == "point")
        print(f"标注模式已切换为: {mode}")

    def add_new_box_annotation(self, ui_rect: QRect):
        """槽函数：当 DrawingLabel 画完一个新矩形框时调用"""
        if self.current_frame_num < 0: return

        # 1. 坐标转换：从UI坐标转为视频原始坐标
        video_rect = self.video_label.ui_coord_to_video_coord_rect(ui_rect)
        
        # 2. 创建标注数据对象 (符合 v2 数据模型)
        new_obj = {
            "id": f"box_{uuid.uuid4().hex[:6]}", # 生成一个唯一的短ID
            "type": "box",
            "label": "player", # 暂时硬编码
            "bbox": [video_rect.x(), video_rect.y(), video_rect.width(), video_rect.height()]
        }

        # 3. 写入内存中的 annotations 字典
        self.add_annotation_to_frame(self.current_frame_num, new_obj)
        print(f"在帧 {self.current_frame_num} 添加了新的框选: {new_obj['id']}")

    def add_new_point_annotation(self, ui_point: QPoint):
        """槽函数：当 DrawingLabel 标记一个新点时调用"""
        if self.current_frame_num < 0: return

        video_point = self.video_label.ui_coord_to_video_coord_point(ui_point)
        
        new_obj = {
            "id": f"point_{uuid.uuid4().hex[:6]}",
            "type": "point",
            "label": "ball", # 暂时硬编码
            "coords": [video_point.x(), video_point.y()]
        }
        self.add_annotation_to_frame(self.current_frame_num, new_obj)
        print(f"在帧 {self.current_frame_num} 添加了新的标记点: {new_obj['id']}")

    def add_annotation_to_frame(self, frame_num, annotation_obj):
        """通用辅助函数：将一个标注对象添加到指定帧"""
        frame_key = str(frame_num)
        
        # 确保该帧的列表存在
        if frame_key not in self.annotations['frame_annotations']:
            self.annotations['frame_annotations'][frame_key] = []
        
        self.annotations['frame_annotations'][frame_key].append(annotation_obj)
        
        # 【关键】数据更新后，立即刷新UI
        self.refresh_ui_for_current_frame()

        self.set_dirty()

    def on_object_selected_from_canvas(self, object_id: str):
        """槽函数: 当在视频画布上点击选中一个对象时"""
        if self._is_selecting_programmatically: return
        self.set_selected_object(object_id)

    def on_object_selected_from_list(self, current_item: QListWidgetItem, previous_item: QListWidgetItem):
        """槽函数: 当在右侧列表中点击选中一个对象时"""
        if self._is_selecting_programmatically or not current_item: return
        self.set_selected_object(current_item.text())
        
    def set_selected_object(self, object_id: str):
        """统一的设置选中对象的函数，实现双向绑定"""
        self.selected_object_id = object_id
        
        # 防止信号循环
        self._is_selecting_programmatically = True
        
        # 1. 更新 DrawingLabel 的高亮状态
        self.video_label.set_selected_object(object_id)
        
        # 2. 更新右侧列表的选中项
        if object_id:
            items = self.frame_objects_list.findItems(object_id, Qt.MatchFlag.MatchExactly)
            if items:
                self.frame_objects_list.setCurrentItem(items[0])
        else:
            self.frame_objects_list.clearSelection() # 如果点击空白处，取消列表选择
            
        self._is_selecting_programmatically = False
        print(f"当前选中对象: {object_id if object_id else 'None'}")
        
    def on_object_moved(self, object_id: str, new_geometry):
        """槽函数: 当一个对象被移动或缩放后，更新数据模型"""
        frame_key = str(self.current_frame_num)
        frame_data = self.annotations.get("frame_annotations", {}).get(frame_key, [])
        
        for obj in frame_data:
            if obj['id'] == object_id:
                if obj['type'] == 'box':
                    obj['bbox'] = new_geometry
                elif obj['type'] == 'point':
                    obj['coords'] = new_geometry
                # 不需要手动刷新UI，因为DrawingLabel在拖动时是实时绘制的
                # 但我们需要在拖动结束后，重新加载一次，以确保数据和UI绝对同步
                # self.refresh_ui_for_current_frame() 
                break

    def delete_selected_object(self):
        """删除当前选中的标注对象"""
        if not self.selected_object_id:
            print("没有选中的对象可供删除。")
            return
            
        frame_key = str(self.current_frame_num)
        frame_data = self.annotations.get("frame_annotations", {}).get(frame_key, [])
        
        # 使用列表推导式过滤掉要删除的对象
        self.annotations["frame_annotations"][frame_key] = [
            obj for obj in frame_data if obj['id'] != self.selected_object_id
        ]
        
        print(f"已删除对象: {self.selected_object_id}")
        # 清除选中状态并刷新UI
        self.set_selected_object(None)
        self.refresh_ui_for_current_frame()

    def refresh_ui_for_current_frame(self):
        if self.current_frame_num < 0: return
        
        # 切换帧时，清除旧的选中状态
        self.set_selected_object(None)
        
        frame_key = str(self.current_frame_num)
        objects_on_frame = self.annotations.get('frame_annotations', {}).get(frame_key, [])
        self.video_label.load_frame_annotations(objects_on_frame)
        
        self.frame_objects_list.clear()
        for obj in objects_on_frame:
            self.frame_objects_list.addItem(obj['id'])

    def open_video_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择视频文件", "", "Video Files (*.mp4 *.avi)")
        if not file_path: return

        self.start_session(file_path)

    def start_session(self, video_path):
        """
        启动一个工作会话的核心函数，负责加载视频和关联的标注。
        """
        # 1. 停止旧的线程 (逻辑不变)
        if self.video_thread and self.video_thread.isRunning():
            self.video_worker.stop()
            self.video_thread.quit()
            self.video_thread.wait()

        # 2. 启动新的后台视频线程 (逻辑不变)
        self.video_thread = QThread()
        self.video_worker = VideoWorker(video_path)
        self.video_worker.moveToThread(self.video_thread)
        # 信号连接
        self.video_worker.video_loaded.connect(self.on_video_loaded)
        self.video_worker.frame_ready.connect(self.update_frame)
        self.video_worker.error.connect(self.on_video_error)
        self.video_thread.started.connect(self.video_worker.run)
        self.video_worker.finished.connect(self.video_thread.quit)
        self.video_worker.finished.connect(self.video_worker.deleteLater)
        self.video_thread.finished.connect(self.video_thread.deleteLater)
        self.video_thread.start()

        # <<< ================== 核心新增: 自动加载逻辑 ================== >>>
        # 3. 尝试自动加载同名的标注文件
        # 约定标注文件名为: [视频文件名].json
        annotation_path = video_path + ".json"
        backup_path = video_path + ".autosave.json"
        should_load_backup = False
        did_load_file = False

        if os.path.exists(backup_path):
            # 如果主文件不存在，或备份文件比主文件更新，则提示加载备份
            if not os.path.exists(annotation_path) or \
               os.path.getmtime(backup_path) > os.path.getmtime(annotation_path):
                from PyQt6.QtWidgets import QMessageBox
                reply = QMessageBox.question(self, "恢复文件", 
                                             "检测到上次有未保存的工作，是否从自动备份中恢复？",
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if reply == QMessageBox.StandardButton.Yes:
                    should_load_backup = True
        
        if should_load_backup:
            print(f"从备份文件中恢复: {backup_path}")
            self.load_annotations(backup_path)
            did_load_file = True
        elif os.path.exists(annotation_path):
            print(f"自动加载主标注文件: {annotation_path}")
            self.load_annotations(annotation_path)
            did_load_file = True
        else:
            print("未找到任何标注文件，将创建新的标注。")
            self.annotations = {}
            self.update_match_info_ui()
            self.refresh_all_ui()
            self.refresh_ui_for_current_frame()

                # 将弹窗逻辑移到这里
        if not did_load_file:
            print("未找到任何标注文件，将为新会话初始化。")
            # 只有在没有加载任何文件的情况下，才创建新标注并弹窗
            
            # 先获取视频元数据来初始化
            cap = cv2.VideoCapture(video_path)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS) or 30
            filename = os.path.basename(video_path)
            cap.release()

            self.annotations = get_new_annotation_structure(
                video_filename=filename, video_path=video_path,
                resolution=[width, height], fps=fps, total_frames=total_frames
            )
            
            # 弹出比赛设置对话框
            dialog = MatchSetupDialog(self.annotations['match_info'], self)
            if dialog.exec():
                updated_info = dialog.get_data()
                self.annotations['match_info'].update(updated_info)
            
            # 更新UI
            self.update_match_info_ui()
            self.refresh_all_ui()
            self.refresh_ui_for_current_frame()

    def on_video_error(self, error_message):
        """处理视频加载或播放错误"""
        QMessageBox.critical(self, "视频错误", f"视频处理时发生错误：\n{error_message}")
        print(f"视频错误: {error_message}")
    
    def on_video_loaded(self, total_frames, fps):
        print(f"视频加载成功: {total_frames} 帧, {fps} FPS")
        self.slider.setRange(0, total_frames - 1)
        if hasattr(self, "review_jump_validator"):
            self.review_jump_validator.setTop(max(0, total_frames - 1))
        
        # 更新视频FPS，用于步进间隔计算
        self.video_fps = fps if fps > 0 else 30
        # 更新步进间隔字典中的秒数对应的帧数
        self.step_intervals["1 秒"] = int(self.video_fps)
        self.step_intervals["5 秒"] = int(self.video_fps * 5)
        
        # 获取视频尺寸并设置
        cap = cv2.VideoCapture(self.video_worker.video_path)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        
        self.video_label.set_video_dimensions(width, height)
        
        # 修复Windows兼容性：确保video_label有有效尺寸后再设置target_size
        # 如果video_label的尺寸还是0，使用视频原始尺寸
        label_width = self.video_label.width()
        label_height = self.video_label.height()
        if label_width > 0 and label_height > 0:
            self.video_worker.set_target_size(label_width, label_height)
        else:
            # 如果label尺寸还是0，使用视频原始尺寸（稍后resizeEvent会更新）
            self.video_worker.set_target_size(width, height)
        
        # 启动自动保存（60秒 = 60000毫秒）
        self.autosave_timer.start(60000)
        
        # 无论是新文件还是加载的文件，都显示第一帧
        self.seek_video(0)

    def update_frame(self, frame_num, rgb_array, width, height):
        """
        在主线程中更新视频帧显示。
        
        重要：严格遵守跨线程GUI编程规则
        - 所有GUI对象（QImage, QPixmap）的创建都在主线程完成
        - 使用数据副本确保内存安全，避免后台线程修改数据时影响显示
        """
        self.current_frame_num = frame_num
        
        # 【关键修复】在主线程中创建QImage和QPixmap
        # 确保数据是连续的，并使用tobytes()创建独立的数据副本
        if not rgb_array.flags['C_CONTIGUOUS']:
            rgb_array = rgb_array.copy()
        
        bytes_per_line = 3 * width  # RGB格式，每个像素3字节
        qt_image = QImage(rgb_array.tobytes(), width, height, bytes_per_line, QImage.Format.Format_RGB888)
        
        # 创建QPixmap的副本，确保UI线程使用的图像数据是独立且安全的
        # 这避免了后台线程更新数据时可能导致的图像损坏
        pixmap = QPixmap.fromImage(qt_image.copy())
        self.video_label.setPixmap(pixmap)
        
        # 【重要】每次切换帧时，都必须刷新该帧的标注
        # 但我们不再在此处直接刷新，因为seek和播放的逻辑会处理
        if not self.video_worker.is_playing:
             self.refresh_ui_for_current_frame()
        else: # 播放时，只需加载标注数据，无需更新列表等，追求性能
            frame_key = str(self.current_frame_num)
            objects_on_frame = self.annotations.get('frame_annotations', {}).get(frame_key, [])
            self.video_label.load_frame_annotations(objects_on_frame)

        self.slider.blockSignals(True)
        self.slider.setValue(frame_num)
        self.slider.blockSignals(False)
        self.update_time_label()
        if self.video_worker and self.video_worker.is_playing and self.shot_loop_enabled and self.shot_loop_bounds:
            start_frame, end_frame = self.shot_loop_bounds
            if frame_num >= end_frame:
                self.video_worker.seek(start_frame)

    def seek_video(self, frame_num, keep_playing: bool = False):
        was_playing = False
        if self.video_worker:
            was_playing = self.video_worker.is_playing
        if self.video_worker.is_playing and not keep_playing:
            self.toggle_play_pause()
        self.video_worker.seek(frame_num)
        self.refresh_ui_for_current_frame()
        self._sync_event_selection_to_frame(frame_num)
        if keep_playing and was_playing and self.video_worker and not self.video_worker.is_playing:
            self.video_worker.set_playing(True)
            self.play_pause_btn.setText("❚❚ 暂停")

    def toggle_play_pause(self):
        if self.video_worker and self.video_thread.isRunning():
            if self.video_worker.is_playing:
                self.video_worker.set_playing(False)
                self.play_pause_btn.setText("▶ 播放")
            else:
                if self.shot_loop_enabled:
                    self._update_shot_loop_bounds()
                    if self.shot_loop_bounds:
                        start_frame, _ = self.shot_loop_bounds
                        if self.current_frame_num != start_frame:
                            self.video_worker.seek(start_frame)
                self.video_worker.set_playing(True)
                self.play_pause_btn.setText("❚❚ 暂停")

    def on_shot_loop_toggled(self, checked):
        self.shot_loop_enabled = checked
        if not checked:
            self.shot_loop_bounds = None
            return
        self._update_shot_loop_bounds()
        if self.video_worker and self.video_worker.is_playing and self.shot_loop_bounds:
            start_frame, _ = self.shot_loop_bounds
            if self.current_frame_num != start_frame:
                self.video_worker.seek(start_frame)

    def _get_hit_events_sorted(self):
        events = self.annotations.get('events', [])
        hit_events = [
            e for e in events
            if e.get('type') in ['SHOT', 'RALLY_START'] and 'frame' in e
        ]
        return sorted(hit_events, key=lambda e: e.get('frame', 0))

    def _resolve_shot_loop_bounds(self):
        hit_events = self._get_hit_events_sorted()
        if not hit_events:
            return None

        start_index = None
        if self.last_selected_event_id:
            for i, event in enumerate(hit_events):
                if event.get('event_id') == self.last_selected_event_id:
                    start_index = i
                    break

        if start_index is None:
            for i, event in enumerate(hit_events):
                if event.get('frame', -1) <= self.current_frame_num:
                    start_index = i
                else:
                    break
            if start_index is None:
                start_index = 0

        if start_index + 1 >= len(hit_events):
            return None

        start_frame = hit_events[start_index].get('frame')
        end_frame = hit_events[start_index + 1].get('frame')
        if start_frame is None or end_frame is None or end_frame <= start_frame:
            return None

        return (start_frame, end_frame)

    def _update_shot_loop_bounds(self):
        if not self.shot_loop_enabled:
            self.shot_loop_bounds = None
            return
        self.shot_loop_bounds = self._resolve_shot_loop_bounds()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.video_worker:
            self.video_worker.set_target_size(self.video_label.width(), self.video_label.height())
            
    def closeEvent(self, event):
        if self.video_thread and self.video_thread.isRunning():
            self.video_worker.stop()
            self.video_thread.quit()
            self.video_thread.wait()
        event.accept()

    def add_rally_start_event(self):
        """
        添加一个回合开始事件。
        智能判断：仅在0-0开局时要求用户选择发球方。
        """
        if self.current_frame_num < 0: return

        serving_player = None
        score = self.annotations['match_info']['current_set_score']
        
        # 1. 判断是否是0-0开局
        if score == [0, 0]:
            dialog = ServePlayerDialog(self.player_a_name, self.player_b_name, self)
            dialog.setWindowTitle("新的一局开始，请选择发球方")
            if dialog.exec():
                serving_player = dialog.serving_player
        else:
            # 2. 如果不是开局，自动从上一个回合的胜利者推断
            last_winner = None
            events = self.annotations.get('events', [])
            if events:
                # 从后往前找最后一个回合结束事件
                for event in reversed(events):
                    if event['type'] == 'RALLY_END':
                        last_winner = event['details'].get('winner')
                        break
            
            if last_winner:
                serving_player = last_winner
            else:
                # 兜底：如果找不到上一个胜利者（例如用户删除了事件），还是让用户手动选
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "信息缺失", "无法自动确定发球方，请手动选择。")
                dialog = ServePlayerDialog(self.player_a_name, self.player_b_name, self)
                if dialog.exec():
                    serving_player = dialog.serving_player

        if not serving_player:
            return # 如果用户取消选择，则不添加事件

        # 3. 创建并添加事件
        new_event = {
            "event_id": f"evt_{uuid.uuid4().hex[:6]}",
            "type": "RALLY_START",
            "frame": self.current_frame_num,
            "details": {
                "serving_player": serving_player,
                "score_at_start": list(self.annotations['match_info']['current_set_score']),
                "hand": "待定",
                "major": "待定",
                "minor": "待定",
                "view_desc": "视角正常"
            }
        }
        self.add_event(new_event)
        self.refresh_all_ui()

    def add_rally_end_event(self):
        """添加一个回合结束事件，并让用户选择得分方（逻辑修正版）"""
        if self.current_frame_num < 0: return

        # 【逻辑修正】检查当前是否在一个开放的回合内
        is_in_open_rally = False
        for event in reversed(self.annotations.get('events', [])):
            if event['type'] == 'RALLY_END':
                break # 遇到了上一个回合的结束点，说明当前不在开放回合内
            if event['type'] == 'RALLY_START':
                is_in_open_rally = True # 找到了开放回合的起点
                break
        
        if not is_in_open_rally:
             from PyQt6.QtWidgets import QMessageBox
             QMessageBox.warning(self, "操作顺序错误", "请先标记一个“回合开始”，才能标记“回合结束”。")
             return

        # 1. 弹出得分方选择对话框
        dialog = WinnerSelectionDialog(self.player_a_name, self.player_b_name, self)
        if not dialog.exec(): return
            
        winner = dialog.winner
        if not winner: return
        
        # 2. 更新分数
        self.update_score(winner)

        # 3. 创建“待定”的结束事件
        new_event = {
            "event_id": f"evt_{uuid.uuid4().hex[:6]}",
            "type": "RALLY_END",
            "frame": self.current_frame_num,
            "details": {
                "winner": winner,
                "hand": "不适用",
                "major": "待定",
                "minor": "待定",
                "view_desc": "视角正常"
            }
        }
        self.add_event(new_event)
        
        # 4. 刷新UI并检查本局是否结束
        self.refresh_all_ui()
        set_winner = self.check_set_winner()
        if set_winner:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "本局结束", f"恭喜 {set_winner} 赢得本局！")

    def add_set_start_event(self):
        """添加一个新局的开始事件，并重置比分"""
        if self.current_frame_num < 0: return

        # 重置当前局的比分
        self.annotations['match_info']['current_set_score'] = [0, 0]
        self.update_match_info_ui()

        new_event = {
            "event_id": f"evt_{uuid.uuid4().hex[:6]}",
            "type": "SET_START",
            "frame": self.current_frame_num,
            "details": {}
        }
        self.add_event(new_event)
        print("新的一局已开始，比分已重置。")

    def add_set_end_event(self):
        """结束当前局，并将比分存档"""
        if self.current_frame_num < 0: return
        
        # 将当前比分添加到已完成的局分列表中
        final_score = self.annotations['match_info']['current_set_score']
        self.annotations['match_info']['set_scores'].append(list(final_score))
        
        # 更新UI，显示局分
        self.update_match_info_ui()

        new_event = {
            "event_id": f"evt_{uuid.uuid4().hex[:6]}",
            "type": "SET_END",
            "frame": self.current_frame_num,
            "details": { "final_score": list(final_score) }
        }
        self.add_event(new_event)
        print(f"本局结束，最终比分: {final_score}")

    def add_shot_event(self):
        """
        添加一个击球事件（重构版）。
        能根据当前帧号，自动找到其归属的回合。
        """
        if self.current_frame_num < 0: return
        
        frame_to_add = self.current_frame_num
        events = self.annotations.get('events', [])
        
        # <<< ================== 核心重构：时间轴归属逻辑 ================== >>>
        
        # 1. 寻找当前帧所属的回合边界
        owning_rally_start = None
        
        # 从后往前遍历，找到离当前帧最近的、在它之前的 RALLY_START
        for event in reversed(events):
            if event['frame'] <= frame_to_add and event['type'] == 'RALLY_START':
                owning_rally_start = event
                break
        
        # 如果连一个 RALLY_START 都找不到，则无法添加
        if not owning_rally_start:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "操作无效", "无法添加击球事件，因为在此之前不存在任何“回合开始”的标记。")
            return
            
        # 2. 检查这个 SHOT 是否在回合的有效范围内
        # 回合的结束点是下一个 RALLY_START 或 SET_START
        rally_end_frame = float('inf') # 默认为无穷大
        start_index = events.index(owning_rally_start)
        for i in range(start_index + 1, len(events)):
            next_event = events[i]
            if next_event['type'] in ['RALLY_START', 'SET_START']:
                rally_end_frame = next_event['frame']
                break
        
        # 如果当前帧号不在这个回合的范围内，则不允许添加
        if not (owning_rally_start['frame'] <= frame_to_add < rally_end_frame):
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "操作无效", "当前时间点不属于任何一个已标记的回合。")
            return

        # 1. 不再弹出对话框，直接创建“待定”事件
        new_event = {
            "event_id": f"evt_{uuid.uuid4().hex[:6]}",
            "type": "SHOT",
            "frame": frame_to_add,
            "details": {
                "player": "待定", # 球员也设为待定
                "hand": "待定",
                "major": "待定",
                "minor": "待定",
                "view_desc": "视角正常"
            }
        }
        
        # 2. 添加并自动排序
        self.add_event(new_event)
        
        # 3. 重新评估该回合内所有击球员的顺序
        self.reevaluate_players_in_rally(start_index)

        print(f"在帧 {frame_to_add} 添加了待定击球事件，并已刷新回合内球员顺序。")
        
        # 4. 刷新UI
        self.refresh_all_ui()

    def update_match_info_ui(self):
        """根据 self.annotations 更新比赛信息的UI显示 (增强版)"""
        info = self.annotations.get('match_info', {})
        self.player_a_name = info.get('player_a', '球员A')
        self.player_b_name = info.get('player_b', '球员B')

        # 构建局分显示
        set_scores_list = info.get('set_scores', [])
        player_a_sets_won = 0
        player_b_sets_won = 0
        for score in set_scores_list:
            if score[0] > score[1]:
                player_a_sets_won += 1
            else:
                player_b_sets_won += 1

        self.player_a_label.setText(f"{self.player_a_name} ({player_a_sets_won})")
        self.player_b_label.setText(f"{self.player_b_name} ({player_b_sets_won})")

        score = info.get('current_set_score', [0, 0])
        self.score_label.setText(f"{score[0]} - {score[1]}")

    def update_score(self, winner_name):
        """根据胜利者更新分数"""
        score = self.annotations['match_info']['current_set_score']
        if winner_name == self.player_a_name:
            score[0] += 1
        elif winner_name == self.player_b_name:
            score[1] += 1
        
        self.update_match_info_ui()

    def reevaluate_players_in_rally(self, rally_start_index):
        """
        核心函数：重新计算并修正一个回合内所有击球事件的球员归属。
        :param rally_start_index: 该回合 RALLY_START 事件在总事件列表中的索引。
        """
        events = self.annotations['events']
        
        # 1. 确定这个回合的边界
        rally_end_index = len(events)
        for i in range(rally_start_index + 1, len(events)):
            if events[i]['type'] in ['RALLY_START', 'SET_START']:
                rally_end_index = i
                break
        
        # 2. 获取发球方作为第一个击球者
        serving_player = events[rally_start_index]['details']['serving_player']
        last_player = serving_player
        
        player_a = self.player_a_name
        player_b = self.player_b_name

        # 3. 遍历这个回合内的所有 SHOT 事件
        for i in range(rally_start_index + 1, rally_end_index):
            if events[i]['type'] == 'SHOT':
                # 根据上一个击球者，确定当前的击球者
                if last_player == player_a:
                    current_player = player_b
                else:
                    current_player = player_a
                
                # 更新数据模型
                events[i]['details']['player'] = current_player
                # 更新下一个循环的参照
                last_player = current_player

    def check_set_winner(self):
        """检查当前局是否有人获胜，包含deuce和30分封顶规则"""
        score = self.annotations['match_info']['current_set_score']
        s1, s2 = score[0], score[1]

        if s1 >= 21 and (s1 - s2) >= 2:
            return self.player_a_name
        if s2 >= 21 and (s2 - s1) >= 2:
            return self.player_b_name
        
        if s1 == 30 and s2 < 30:
            return self.player_a_name
        if s2 == 30 and s1 < 30:
            return self.player_b_name
            
        return None # 比赛继续
        
    def add_event(self, event_obj):
        """通用函数，用于添加任何类型的事件并刷新UI"""
        self.annotations['events'].append(event_obj)
        # 保持事件按帧号排序
        self.annotations['events'].sort(key=lambda x: x['frame'])
        
        # 重新计算比分以确保数据一致性（特别是当用户手动编辑事件时）
        # 对于可能影响比分的事件，重新计算整个比分历史
        if event_obj['type'] in ['RALLY_END', 'SET_START']:
            self.recalculate_scores()
        
        self.refresh_all_ui(scroll_to_event_id=event_obj['event_id'])
        self.set_dirty()

    # 统一的UI刷新函数，替代原来的 refresh_event_tree() 和 refresh_all_ui()
    def refresh_all_ui(self, scroll_to_event_id=None, scroll_to_bottom=None):
        """
        统一的UI刷新函数，刷新事件树并保持展开状态。
        :param scroll_to_event_id: 刷新后需要滚动到的事件ID（优先）。
        :param scroll_to_bottom: 是否强制滚动到底部（默认True，除非指定了scroll_to_event_id）。
        """

        # 1. 刷新前，记录所有展开的节点的 event_id
        expanded_ids = set()
        iterator = QTreeWidgetItemIterator(self.event_tree)
        while iterator.value():
            item = iterator.value()
            if item.isExpanded():
                item_id = item.data(0, Qt.ItemDataRole.UserRole + 1)
                if item_id:
                    expanded_ids.add(item_id)
            iterator += 1
        
        # 暂停UI更新，可以轻微提升大规模刷新性能
        self.event_tree.setUpdatesEnabled(False)
        self.event_tree.clear()
        
        # 使用字典来管理所有创建的UI节点，便于后续查找
        all_items = {} # key: event_id, value: QTreeWidgetItem

        events = self.annotations.get('events', [])
        
        # 第一遍：创建所有节点并建立父子关系
        for event in events:
            event_id = event['event_id']
            event_type = event['type']
            
            parent_item = None
            # 确定父节点
            if event_type in ['SHOT', 'RALLY_END']:
                parent_event = next((e for e in reversed(events[:events.index(event)]) if e['type'] == 'RALLY_START'), None)
                if parent_event:
                    parent_item = all_items.get(parent_event['event_id'])
            elif event_type in ['RALLY_START', 'SET_END']:
                parent_event = next((e for e in reversed(events[:events.index(event)]) if e['type'] == 'SET_START'), None)
                if parent_event:
                    parent_item = all_items.get(parent_event['event_id'])

            # 创建节点
            if parent_item:
                item = QTreeWidgetItem(parent_item)
            else: # 顶层节点 (SET_START)
                item = QTreeWidgetItem(self.event_tree)
            
            # 存储节点和其元数据
            all_items[event_id] = item
            item.setData(0, Qt.ItemDataRole.UserRole, event['frame'])
            item.setData(0, Qt.ItemDataRole.UserRole + 1, event_id)

        # 第二遍：填充所有节点的文本信息
        set_counter = 0
        rally_counter_map = {}

        for event in events:
            event_id = event['event_id']
            event_type = event['type']
            item = all_items.get(event_id)
            if not item: continue

            if event_type == 'SET_START':
                set_counter += 1
                rally_counter_map[event_id] = 0
                item.setText(0, f"🌳 第 {set_counter} 局")
                
                # 检查是否有结束事件来添加最终比分
                set_end_event = next((e for e in events[events.index(event):] if e['type'] == 'SET_END' and next((se for se in reversed(events[:events.index(e)]) if se['type'] == 'SET_START'), None) == event), None)
                if set_end_event:
                    final_score = set_end_event['details']['final_score']
                    item.setText(1, f"最终比分: {final_score[0]}-{final_score[1]}")

            elif event_type == 'RALLY_START':
                parent_set_id = next((e['event_id'] for e in reversed(events[:events.index(event)]) if e['type'] == 'SET_START'), None)
                if parent_set_id:
                    rally_counter_map[parent_set_id] += 1
                    rally_num = rally_counter_map[parent_set_id]
                    score_str = f"{event['details']['score_at_start'][0]}-{event['details']['score_at_start'][1]}"
                    item.setText(0, f"🏸 回合 {rally_num} (比分 {score_str})")
                    # 显示发球人名字和技术动作（与击球事件格式一致）
                    details = event['details']
                    serving_player = details.get('serving_player', '待定')
                    hand = details.get('hand', '待定')
                    # 根据hand字段决定显示内容：适用时显示技术动作，否则显示hand值（包括"不适用"和"待定"）
                    if hand == "适用":
                        technique_display = details.get('minor', '待定')
                    else:
                        # hand为"不适用"、"待定"或其他值时，直接显示hand值
                        technique_display = str(hand) if hand else '待定'
                    view_desc = details.get('view_desc', '视角正常')
                    item.setText(1, f"{serving_player}: {technique_display}-{view_desc}")

            elif event_type == 'SHOT':
                details = event['details']
                item.setText(0, f"🎾 击球 (帧: {event['frame']})")
                hand = details.get('hand', '待定')
                # 根据hand字段决定显示内容：适用时显示技术动作，否则显示hand值（包括"不适用"和"待定"）
                if hand == "适用":
                    technique_display = details.get('minor', '待定')
                else:
                    # hand为"不适用"、"待定"或其他值时，直接显示hand值
                    technique_display = str(hand) if hand else '待定'
                view_desc = details.get('view_desc', '视角正常')
                item.setText(1, f"{details['player']}: {technique_display}-{view_desc}")
            
            elif event_type == 'RALLY_END':
                item.setText(0, f"🏁 回合结束 (帧: {event['frame']})")
                item.setText(1, f"得分: {event['details']['winner']}")

            elif event_type == 'SET_END':
                item.setText(0, f"🏆 局结束 (帧: {event['frame']})")

        # 2. 所有节点都创建完毕后，一次性恢复展开状态
        for event_id, item in all_items.items():
            if event_id in expanded_ids:
                item.setExpanded(True)

        # 更新全局引用，供审阅模块使用
        self.event_items = all_items

        self.event_tree.resizeColumnToContents(0)
        
        # 智能滚动逻辑：优先滚动到指定事件，否则滚动到底部
        if scroll_to_event_id and scroll_to_event_id in all_items:
            item_to_scroll = all_items[scroll_to_event_id]
            self.event_tree.scrollToItem(item_to_scroll, QAbstractItemView.ScrollHint.PositionAtCenter)
        elif scroll_to_bottom is None or scroll_to_bottom:
            # 默认滚动到底部（保持向后兼容）
            self.event_tree.scrollToBottom()

        # 恢复UI更新
        self.event_tree.setUpdatesEnabled(True)

        # 同步更新审阅统计信息
        self.update_review_stats()

    def on_event_tree_item_clicked(self, item, column):
        """槽函数：当事件树中的一项被点击时（逻辑优化版）"""
        if not self.video_worker: return

        frame_num = None
        event_id = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if not event_id: return

        # 更新最后选中的事件ID，用于连续调整功能
        self.last_selected_event_id = event_id
        if self.shot_loop_enabled:
            self._update_shot_loop_bounds()

        # 找到被点击的事件对象
        clicked_event = next((e for e in self.annotations['events'] if e['event_id'] == event_id), None)
        if not clicked_event: return

        # 新的导航逻辑：
        # 如果点击的是父节点（局或回合），我们用它自身存的帧号（就是开始帧）。
        # 如果点击的是子节点（击球或回合结束），也用它自身存的帧号。
        # 这样逻辑就统一了：跳转到被点击节点自身代表的事件帧。
        # 上一版逻辑"点击回合结束跳转到回合开始"被移除，因为现在可以直接点击回合父节点。
        
        frame_num = clicked_event['frame']
        
        if frame_num is not None:
            print(f"导航到事件: {item.text(0)}, 目标帧: {frame_num}")
            
            self.video_worker.seek(frame_num)
            
            # 导航后自动播放
            # if not self.video_worker.is_playing:
                # self.toggle_play_pause()

    def on_event_tree_item_double_clicked(self, item, column):
        """当事件树中的一项被双击时，用于编辑 SHOT 或 RALLY_END 或 RALLY_START 事件的细节"""
        event_id = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if not event_id: return
        
        # 更新最后选中的事件ID，用于连续调整功能
        self.last_selected_event_id = event_id
        if self.shot_loop_enabled:
            self._update_shot_loop_bounds()

        clicked_event = next((e for e in self.annotations['events'] if e['event_id'] == event_id), None)
        if not clicked_event: return

        event_type = clicked_event['type']

        # 允许编辑 RALLY_START, SHOT, RALLY_END
        if event_type in ['RALLY_START', 'SHOT', 'RALLY_END']:
            # 对话框防抖：如果已经打开，则直接返回
            if self._tech_dialog_open:
                return
            self._tech_dialog_open = True
            dialog = TechniqueSelectionDialog(clicked_event['details'], self)
            
            # 在"标注击球事件"页面下，默认第一列选择"适用"
            if hasattr(self, 'right_page_combo') and self.right_page_combo.currentIndex() == 1:
                # 索引1对应"标注击球事件"页面
                for i in range(dialog.hand_list.count()):
                    if dialog.hand_list.item(i).text() == "适用":
                        dialog.hand_list.setCurrentRow(i)
                        break
            
            if event_type == 'RALLY_START':
                dialog.setWindowTitle("编辑发球技术")
                # 预选 "发球"
                for i in range(dialog.major_list.count()):
                    if dialog.major_list.item(i).text() == "发球":
                        dialog.major_list.setCurrentRow(i)
                        break
            elif event_type == 'RALLY_END':
                dialog.setWindowTitle("选择得分方式或失误原因")
                # 预选 "得分方式/失误原因"
                for i in range(dialog.major_list.count()):
                    if dialog.major_list.item(i).text() == "得分方式/失误原因":
                        dialog.major_list.setCurrentRow(i)
                        break
            
            # 关闭时无论结果如何都清理标志
            result = dialog.exec()
            self._tech_dialog_open = False
            if result:
                selection = dialog.get_selection()
                if selection:
                    clicked_event['details'].update(selection)
                    # 如果编辑的是可能影响比分的事件，重新计算比分
                    if clicked_event['type'] in ['RALLY_END', 'SET_START']:
                        self.recalculate_scores()
                    print(f"已更新事件 {event_id} 的细节。")
                    # 跳转到下一条，若无下一条则停留当前
                    next_event_id = self._get_next_event_id(event_id)
                    target_event_id = next_event_id or event_id
                    self.refresh_all_ui(scroll_to_event_id=target_event_id)
                    self._select_event_in_tree(target_event_id)
                    self.event_tree.setFocus()
                    
                    # 让视频画面也跳转到目标事件的帧
                    if self.video_worker and target_event_id:
                        target_event = next((e for e in self.annotations['events'] if e['event_id'] == target_event_id), None)
                        if target_event and 'frame' in target_event:
                            self.video_worker.seek(target_event['frame'])

        # 编辑后，可能会改变 hand 字段（待定 / 不适用 / 适用），需要刷新审阅统计
        self.update_review_stats()

    # ----------------------------- 审阅功能相关 -----------------------------
    def update_review_stats(self):
        """统计所有 hand 为 '待定' 或 '不适用' 的击球/发球事件，用于审阅界面"""
        if not hasattr(self, "review_pending_label") or not hasattr(self, "review_na_label"):
            return

        events = self.annotations.get("events", [])
        # 统计：类型为 SHOT 或 RALLY_START（发球），并按 hand 区分
        self.pending_events = [
            e for e in events
            if e.get("type") in ["SHOT", "RALLY_START"]
            and str(e.get("details", {}).get("hand", "")) == "待定"
        ]
        self.na_events = [
            e for e in events
            if e.get("type") in ["SHOT", "RALLY_START"]
            and str(e.get("details", {}).get("hand", "")) == "不适用"
        ]
        # 统计视角问题
        self.view_abnormal_events = [
            e for e in events
            if e.get("type") in ["SHOT", "RALLY_START"]
            and str(e.get("details", {}).get("view_desc", "")) == "视角异常"
        ]
        self.view_missing_events = [
            e for e in events
            if e.get("type") in ["SHOT", "RALLY_START"]
            and str(e.get("details", {}).get("view_desc", "")) == "击球缺帧"
        ]
        self.unusual_events = [
            e for e in events
            if e.get("type") in ["SHOT", "RALLY_START"]
            and str(e.get("details", {}).get("hand", "")) == "不适用"
            and str(e.get("details", {}).get("minor", "")) == "非常规动作"
        ]

        total_pending = len(self.pending_events)
        total_na = len(self.na_events)
        total_view_abnormal = len(self.view_abnormal_events)
        total_view_missing = len(self.view_missing_events)
        total_unusual = len(self.unusual_events)

        # 重置当前位置索引
        if total_pending == 0:
            self.review_index_map["待定"] = -1
        else:
            # 如果之前的位置还在范围内，就保持，否则重置为第一个
            idx = self.review_index_map.get("待定", -1)
            self.review_index_map["待定"] = idx if 0 <= idx < total_pending else 0

        if total_na == 0:
            self.review_index_map["不适用"] = -1
        else:
            idx = self.review_index_map.get("不适用", -1)
            self.review_index_map["不适用"] = idx if 0 <= idx < total_na else 0

        if total_view_abnormal == 0:
            self.review_index_map["视角异常"] = -1
        else:
            idx = self.review_index_map.get("视角异常", -1)
            self.review_index_map["视角异常"] = idx if 0 <= idx < total_view_abnormal else 0

        if total_view_missing == 0:
            self.review_index_map["击球缺帧"] = -1
        else:
            idx = self.review_index_map.get("击球缺帧", -1)
            self.review_index_map["击球缺帧"] = idx if 0 <= idx < total_view_missing else 0

        if total_unusual == 0:
            self.review_index_map["非常规动作"] = -1
        else:
            idx = self.review_index_map.get("非常规动作", -1)
            self.review_index_map["非常规动作"] = idx if 0 <= idx < total_unusual else 0

        counts_text = (
            f"待定:{total_pending} | 不适用:{total_na} | 视角异常:{total_view_abnormal} | "
            f"击球缺帧:{total_view_missing} | 非常规动作:{total_unusual}"
        )
        self.review_pending_label.setText(counts_text)
        self._update_review_position_label()

    def _find_nearest_event_id_by_frame(self, frame_num):
        """返回与frame_num最近的事件ID，若不存在则返回None"""
        events = self.annotations.get('events', [])
        if not events:
            return None
        nearest_id = None
        nearest_dist = None
        for event in events:
            event_frame = event.get('frame')
            if event_frame is None:
                continue
            dist = abs(event_frame - frame_num)
            if nearest_dist is None or dist < nearest_dist:
                nearest_dist = dist
                nearest_id = event.get('event_id')
        return nearest_id

    def _sync_event_selection_to_frame(self, frame_num):
        """让事件树选中与当前帧最接近的事件"""
        if not hasattr(self, "event_tree"):
            return
        event_id = self._find_nearest_event_id_by_frame(frame_num)
        if not event_id:
            return
        current_item = self.event_tree.currentItem()
        current_id = current_item.data(0, Qt.ItemDataRole.UserRole + 1) if current_item else None
        if event_id != current_id:
            self._select_event_in_tree(event_id)

    def _update_review_position_label(self):
        """根据当前筛选项刷新当前位置显示"""
        if not hasattr(self, "review_filter_combo") or not hasattr(self, "review_na_label"):
            return

        def fmt(current_idx, total):
            if total == 0 or current_idx < 0:
                return "0/0"
            return f"{current_idx + 1}/{total}"

        target = self.review_filter_combo.currentText()
        if target == "待定":
            total = len(getattr(self, "pending_events", []))
            idx = self.review_index_map.get("待定", -1)
        elif target == "不适用":
            total = len(getattr(self, "na_events", []))
            idx = self.review_index_map.get("不适用", -1)
        elif target == "视角异常":
            total = len(getattr(self, "view_abnormal_events", []))
            idx = self.review_index_map.get("视角异常", -1)
        elif target == "击球缺帧":
            total = len(getattr(self, "view_missing_events", []))
            idx = self.review_index_map.get("击球缺帧", -1)
        elif target == "非常规动作":
            total = len(getattr(self, "unusual_events", []))
            idx = self.review_index_map.get("非常规动作", -1)
        else:
            total = 0
            idx = -1

        self.review_na_label.setText(f"当前位置({target}): {fmt(idx, total)}")

    def navigate_review_by_filter(self, backward: bool = False):
        """根据当前筛选项在审阅列表中跳转"""
        if not hasattr(self, "review_filter_combo"):
            return
        target = self.review_filter_combo.currentText()
        if target in ["待定", "不适用"]:
            self.navigate_review_events(target, backward=backward)
        elif target in ["视角异常", "击球缺帧"]:
            self.navigate_review_view_desc(target, backward=backward)
        elif target == "非常规动作":
            self.navigate_review_unusual(backward=backward)

    def jump_to_frame_from_review(self):
        """从审阅面板输入框跳转到指定帧"""
        if not self.video_worker or not hasattr(self, "review_jump_input"):
            return
        text = self.review_jump_input.text().strip()
        if not text:
            return
        try:
            target_frame = int(text)
        except ValueError:
            return
        max_frame = self.slider.maximum()
        target_frame = max(0, min(target_frame, max_frame))
        self.seek_video(target_frame)

    def navigate_review_events(self, target_hand: str, backward: bool = False):
        """
        在审阅界面中，根据 hand 字段（'待定' 或 '不适用'）跳转到上/下一个击球事件。
        """
        if target_hand not in ["待定", "不适用"]:
            return

        # 选择对应的事件列表
        if target_hand == "待定":
            events_list = getattr(self, "pending_events", [])
        else:
            events_list = getattr(self, "na_events", [])

        if not events_list:
            return

        idx = self.review_index_map.get(target_hand, -1)
        if idx < 0:
            idx = 0

        # 计算新的索引（循环遍历）
        if backward:
            idx = (idx - 1) % len(events_list)
        else:
            idx = (idx + 1) % len(events_list)

        self.review_index_map[target_hand] = idx

        target_event = events_list[idx]
        event_id = target_event.get("event_id")

        # 在事件树中找到对应的节点并选中 / 滚动
        if event_id:
            self._select_event_in_tree(event_id)

        # 同时让视频跳转到该事件的帧
        if self.video_worker:
            frame_num = target_event.get("frame")
            if frame_num is not None:
                self.seek_video(frame_num, keep_playing=self.video_worker.is_playing)

        # 更新统计显示（当前位置会变化）
        self.update_review_stats()

    def navigate_review_view_desc(self, target_view: str, backward: bool = False):
        """
        在审阅界面中，根据视角描述（'视角异常' 或 '击球缺帧'）跳转到上/下一个事件。
        """
        if target_view not in ["视角异常", "击球缺帧"]:
            return

        # 选择对应的事件列表
        if target_view == "视角异常":
            events_list = getattr(self, "view_abnormal_events", [])
        else:
            events_list = getattr(self, "view_missing_events", [])

        if not events_list:
            return

        idx = self.review_index_map.get(target_view, -1)
        if idx < 0:
            idx = 0

        # 计算新的索引（循环遍历）
        if backward:
            idx = (idx - 1) % len(events_list)
        else:
            idx = (idx + 1) % len(events_list)

        self.review_index_map[target_view] = idx

        target_event = events_list[idx]
        event_id = target_event.get("event_id")

        # 在事件树中找到对应的节点并选中 / 滚动
        if event_id:
            self._select_event_in_tree(event_id)

        # 同时让视频跳转到该事件的帧
        if self.video_worker:
            frame_num = target_event.get("frame")
            if frame_num is not None:
                self.seek_video(frame_num, keep_playing=self.video_worker.is_playing)

        # 更新统计显示（当前位置会变化）
        self.update_review_stats()

    def navigate_review_unusual(self, backward: bool = False):
        """在审阅界面中，根据“非常规动作”跳转到上/下一个事件。"""
        events_list = getattr(self, "unusual_events", [])
        if not events_list:
            return

        idx = self.review_index_map.get("非常规动作", -1)
        if idx < 0:
            idx = 0

        if backward:
            idx = (idx - 1) % len(events_list)
        else:
            idx = (idx + 1) % len(events_list)

        self.review_index_map["非常规动作"] = idx

        target_event = events_list[idx]
        event_id = target_event.get("event_id")

        if event_id:
            self._select_event_in_tree(event_id)

        if self.video_worker:
            frame_num = target_event.get("frame")
            if frame_num is not None:
                self.seek_video(frame_num, keep_playing=self.video_worker.is_playing)

        self.update_review_stats()

    def delete_selected_event(self):
        """删除事件，并对齐Set和Rally的删除逻辑"""
        selected_item = self.event_tree.currentItem()
        if not selected_item: return

        event_id = selected_item.data(0, Qt.ItemDataRole.UserRole + 1)
        if not event_id: return

        events = self.annotations['events']
        event_to_delete = next((e for e in events if e['event_id'] == event_id), None)
        if not event_to_delete: return
        
        indices_to_delete = []
        rally_to_re_evaluate_index = -1
        event_type = event_to_delete['type']

        if event_type == 'RALLY_START' or event_type == 'SET_START':
            # --- 删除整个回合 或 整个局 ---
            unit = "回合" if event_type == 'RALLY_START' else "局"
            reply = QMessageBox.question(self, f"确认删除{unit}", 
                                         f"这将删除整个{unit}及其内部的所有事件，是否继续？",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No: return
            
            start_index = events.index(event_to_delete)
            # 结束点是下一个同类型的开始事件
            end_boundary_type = 'SET_START' if event_type == 'SET_START' else 'RALLY_START'
            end_index = len(events)
            for i in range(start_index + 1, len(events)):
                # 如果是删局，下一个局开始是边界
                if events[i]['type'] == 'SET_START' and end_boundary_type == 'SET_START':
                    end_index = i
                    break
                # 如果是删回合，下一个回合或局开始都是边界
                if events[i]['type'] in ['RALLY_START', 'SET_START'] and end_boundary_type == 'RALLY_START':
                    end_index = i
                    break
            indices_to_delete = list(range(start_index, end_index))

        elif event_type in ['SHOT', 'RALLY_END', 'SET_END']:
            # --- 只删除单个子事件 ---
            index_to_delete = events.index(event_to_delete)
            indices_to_delete.append(index_to_delete)

            # 如果删除的是击球，需要重排球员
            if event_type == 'SHOT':
                for i in range(index_to_delete, -1, -1):
                    if events[i]['type'] == 'RALLY_START':
                        rally_to_re_evaluate_index = i
                        break
        else:
            QMessageBox.information(self, "提示", f"暂不支持删除 '{event_type}' 类型的事件。")
            return

        if not indices_to_delete: return

        # 1. 从数据模型中删除
        for i in sorted(indices_to_delete, reverse=True):
            del events[i]
        
        # 2. 如果删的是SHOT或RALLY_END，重排该回合的球员
        if rally_to_re_evaluate_index != -1:
            self.reevaluate_players_in_rally(rally_to_re_evaluate_index)

        # 3. 触发全局数据重算（比分等）
        self.recalculate_scores()
        
        # 4. 全面刷新UI
        self.update_match_info_ui()
        self.refresh_all_ui() # 不带参数，保持当前视图
        print(f"已删除 {len(indices_to_delete)} 个事件并刷新数据。")

        self.set_dirty()

    def adjust_selected_event_frame(self, delta):
        """
        调整选中事件的帧号（微调功能）
        :param delta: 帧号变化量，正数为向前移动，负数为向后移动
        """
        # 优先使用当前选中的事件树项，如果没有，则使用最后选中的事件ID
        event_id = None
        selected_item = self.event_tree.currentItem()
        
        if selected_item:
            event_id = selected_item.data(0, Qt.ItemDataRole.UserRole + 1)
        
        # 如果当前没有选中的项，使用最后选中的事件ID
        if not event_id and self.last_selected_event_id:
            event_id = self.last_selected_event_id
            self._select_event_in_tree(event_id)
        
        if not event_id:
            return
        
        # 找到对应的事件对象
        events = self.annotations.get('events', [])
        event_to_adjust = next((e for e in events if e['event_id'] == event_id), None)
        if not event_to_adjust:
            return
        
        # 计算新的帧号
        old_frame = event_to_adjust['frame']
        new_frame = old_frame + delta
        
        # 边界检查：确保帧号在有效范围内
        video_info = self.annotations.get('video_info', {})
        max_frame = video_info.get('total_frames', 0) - 1
        if max_frame > 0:
            new_frame = max(0, min(new_frame, max_frame))
        else:
            return  # 如果没有视频信息，无法确定边界
        
        # 如果帧号没有变化，直接返回
        if new_frame == old_frame:
            return
        
        # 更新事件的帧号
        event_to_adjust['frame'] = new_frame
        
        # 重新排序事件列表（因为事件是按帧号排序的）
        events.sort(key=lambda x: x['frame'])
        
        # 根据事件类型，可能需要重新计算相关数据
        event_type = event_to_adjust['type']
        needs_score_recalc = False
        
        if event_type in ['RALLY_END', 'SET_START']:
            # 影响比分的事件，需要重新计算比分
            needs_score_recalc = True
        elif event_type == 'SHOT':
            # 击球事件，需要重新计算球员顺序
            # 找到该击球所在的回合
            event_index = events.index(event_to_adjust)
            for i in range(event_index, -1, -1):
                if events[i]['type'] == 'RALLY_START':
                    self.reevaluate_players_in_rally(i)
                    break
        
        # 如果需要，重新计算比分
        if needs_score_recalc:
            self.recalculate_scores()
        
        # 更新最后选中的事件ID（确保连续调整时使用正确的事件）
        self.last_selected_event_id = event_id
        
        # 刷新UI，保持选中状态并滚动到该事件
        self.update_match_info_ui()
        self.refresh_all_ui(scroll_to_event_id=event_id)
        
        # 确保事件树中该事件仍然被选中（刷新后可能会丢失选中状态）
        QTimer.singleShot(10, lambda: self._ensure_event_selected(event_id))
        
        # 跳转到新的帧号
        if self.video_worker:
            self.video_worker.seek(new_frame)
        
        self.set_dirty()
        print(f"已将事件 {event_id} ({event_type}) 从帧 {old_frame} 调整到帧 {new_frame}")
    
    def _ensure_event_selected(self, event_id):
        """确保指定的事件在事件树中被选中"""
        if not event_id:
            return
        self._select_event_in_tree(event_id)

    def _get_next_event_id(self, current_event_id):
        """返回事件列表中当前事件的下一条ID，若没有则返回None"""
        events = self.annotations.get('events', [])
        for idx, e in enumerate(events):
            if e.get('event_id') == current_event_id:
                if idx + 1 < len(events):
                    return events[idx + 1].get('event_id')
                break
        return None

    def _ensure_view_desc_defaults(self):
        """为历史数据补充视角字段缺省值"""
        events = self.annotations.get('events', [])
        for e in events:
            details = e.get('details')
            if isinstance(details, dict) and 'view_desc' not in details:
                details['view_desc'] = "视角正常"
    
    def navigate_to_adjacent_event(self, direction):
        """
        导航到上一个或下一个事件
        :param direction: -1 表示上一个事件，1 表示下一个事件
        """
        # 获取当前选中的事件ID
        event_id = None
        selected_item = self.event_tree.currentItem()
        
        if selected_item:
            event_id = selected_item.data(0, Qt.ItemDataRole.UserRole + 1)
        
        # 如果当前没有选中的项，使用最后选中的事件ID
        if not event_id and self.last_selected_event_id:
            event_id = self.last_selected_event_id
        
        if not event_id:
            return
        
        # 获取所有事件并按帧号排序
        events = self.annotations.get('events', [])
        if not events:
            return
        
        # 找到当前事件在列表中的索引
        current_index = -1
        for i, event in enumerate(events):
            if event['event_id'] == event_id:
                current_index = i
                break
        
        if current_index == -1:
            return
        
        # 计算目标索引
        target_index = current_index + direction
        
        # 边界检查
        if target_index < 0 or target_index >= len(events):
            return
        
        # 获取目标事件
        target_event = events[target_index]
        target_event_id = target_event['event_id']
        
        # 在事件树中找到并选中该事件
        self._select_event_in_tree(target_event_id)
        
        # 跳转到目标事件的帧号
        if self.video_worker:
            self.seek_video(target_event['frame'], keep_playing=self.video_worker.is_playing)
        
        print(f"导航到{'下一个' if direction > 0 else '上一个'}事件: {target_event_id} (帧: {target_event['frame']})")
    
    def edit_selected_event(self):
        """打开选中事件的技术动作编辑对话框"""
        # 获取当前选中的事件ID（必须要有选中项，不使用last_selected_event_id）
        selected_item = self.event_tree.currentItem()
        if not selected_item:
            return
        
        event_id = selected_item.data(0, Qt.ItemDataRole.UserRole + 1)
        if not event_id:
            return
        
        # 找到对应的事件对象
        events = self.annotations.get('events', [])
        clicked_event = next((e for e in events if e['event_id'] == event_id), None)
        if not clicked_event:
            return
        
        event_type = clicked_event['type']
        
        # 只允许编辑 RALLY_START, SHOT, RALLY_END
        if event_type not in ['RALLY_START', 'SHOT', 'RALLY_END']:
            return
        
        # 打开编辑对话框（复用双击的逻辑），带防抖
        if self._tech_dialog_open:
            return
        self._tech_dialog_open = True
        dialog = TechniqueSelectionDialog(clicked_event['details'], self)
        
        # 在"标注击球事件"页面下，默认第一列选择"适用"
        if hasattr(self, 'right_page_combo') and self.right_page_combo.currentIndex() == 1:
            # 索引1对应"标注击球事件"页面
            for i in range(dialog.hand_list.count()):
                if dialog.hand_list.item(i).text() == "适用":
                    dialog.hand_list.setCurrentRow(i)
                    break
        
        if event_type == 'RALLY_START':
            dialog.setWindowTitle("编辑发球技术")
            # 预选 "发球"
            for i in range(dialog.major_list.count()):
                if dialog.major_list.item(i).text() == "发球":
                    dialog.major_list.setCurrentRow(i)
                    break
        elif event_type == 'RALLY_END':
            dialog.setWindowTitle("选择得分方式或失误原因")
            # 预选 "得分方式/失误原因"
            for i in range(dialog.major_list.count()):
                if dialog.major_list.item(i).text() == "得分方式/失误原因":
                    dialog.major_list.setCurrentRow(i)
                    break
        
        result = dialog.exec()
        self._tech_dialog_open = False
        if result:
            selection = dialog.get_selection()
            if selection:
                clicked_event['details'].update(selection)
                # 如果编辑的是可能影响比分的事件，重新计算比分
                if clicked_event['type'] in ['RALLY_END', 'SET_START']:
                    self.recalculate_scores()
                print(f"已更新事件 {event_id} 的细节。")
                next_event_id = self._get_next_event_id(event_id)
                target_event_id = next_event_id or event_id
                self.refresh_all_ui(scroll_to_event_id=target_event_id)
                # 关闭后保持聚焦与选中项，并默认跳转到下一条
                self._select_event_in_tree(target_event_id)
                self.event_tree.setFocus()
                self.set_dirty()
                
                # 让视频画面也跳转到目标事件的帧
                if self.video_worker and target_event_id:
                    target_event = next((e for e in self.annotations['events'] if e['event_id'] == target_event_id), None)
                    if target_event and 'frame' in target_event:
                        self.video_worker.seek(target_event['frame'])
    
    def _select_event_in_tree(self, event_id):
        """在事件树中选中指定的事件"""
        if not event_id:
            return
        
        iterator = QTreeWidgetItemIterator(self.event_tree)
        while iterator.value():
            item = iterator.value()
            item_event_id = item.data(0, Qt.ItemDataRole.UserRole + 1)
            if item_event_id == event_id:
                parent = item.parent()
                while parent:
                    parent.setExpanded(True)
                    parent = parent.parent()
                self.event_tree.setCurrentItem(item)
                self.last_selected_event_id = event_id  # 更新最后选中的事件ID
                # 确保该项可见
                self.event_tree.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)
                if self.shot_loop_enabled:
                    self._update_shot_loop_bounds()
                    if self.video_worker and self.video_worker.is_playing and self.shot_loop_bounds:
                        start_frame, _ = self.shot_loop_bounds
                        if self.current_frame_num != start_frame:
                            self.video_worker.seek(start_frame)
                break
            iterator += 1

    def recalculate_scores(self):
        """
        核心审计函数：从头遍历事件列表，重新计算所有比分。
        """
        print("正在重新计算比分...")
        if 'match_info' not in self.annotations: return

        # 1. 重置所有比分数据到初始状态
        match_info = self.annotations['match_info']
        match_info['set_scores'] = []
        match_info['current_set_score'] = [0, 0]
        
        player_a = match_info['player_a']
        player_b = match_info['player_b']

        # 2. 按顺序“重放”事件，重建比分历史
        for event in self.annotations['events']:
            event_type = event['type']
            
            if event_type == 'SET_START':
                # 开始新的一局，重置当前局分
                match_info['current_set_score'] = [0, 0]
            
            elif event_type == 'RALLY_START':
                # 记录回合开始时的比分
                event['details']['score_at_start'] = list(match_info['current_set_score'])
            
            elif event_type == 'RALLY_END':
                # 根据胜利者，更新当前局分
                winner = event['details'].get('winner')
                if winner == player_a:
                    match_info['current_set_score'][0] += 1
                elif winner == player_b:
                    match_info['current_set_score'][1] += 1
            
            elif event_type == 'SET_END':
                # 结束一局，存档比分
                final_score = list(match_info['current_set_score'])
                match_info['set_scores'].append(final_score)
                event['details']['final_score'] = final_score

        print(f"比分重算完成。当前局分: {match_info['current_set_score']}, 局分记录: {match_info['set_scores']}")

    def save_annotations(self):
        if not self.annotations:
            QMessageBox.information(self, "提示", "没有标注可以保存。")
            return
        
        default_path = self.annotations['video_info']['path'] + ".json"
        file_path, _ = QFileDialog.getSaveFileName(self, "保存标注文件", default_path, "JSON Files (*.json)")

        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    import json
                    json.dump(self.annotations, f, indent=4, ensure_ascii=False)
                self.statusBar().showMessage(f"标注已保存到: {file_path}", 3000)
                backup_path = self.annotations['video_info']['path'] + ".autosave.json"
                if os.path.exists(backup_path):
                    try:
                        os.remove(backup_path)
                        print(f"已删除自动备份文件: {backup_path}")
                    except Exception as e:
                        print(f"删除备份文件失败: {e}")
                self.data_is_dirty = False  # 保存后重置脏数据标志
            except PermissionError:
                QMessageBox.warning(self, "保存失败", f"无法保存文件：权限不足。\n请检查文件是否被其他程序占用。")
            except OSError as e:
                QMessageBox.warning(self, "保存失败", f"无法保存文件：\n{str(e)}")
            except Exception as e:
                QMessageBox.critical(self, "保存失败", f"保存标注时发生错误：\n{str(e)}")
                print(f"保存失败: {e}")

    def load_annotations(self, annotation_path=None):
        if annotation_path:
            file_path = annotation_path
        else:
            file_path, _ = QFileDialog.getOpenFileName(self, "加载标注文件", "", "JSON Files (*.json)")
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    import json
                    self.annotations = json.load(f)
                # 校正视频路径：若与标注文件所在目录不一致，则更新到当前目录
                try:
                    ann_dir = os.path.dirname(file_path)
                    video_info = self.annotations.get('video_info', {})
                    filename = video_info.get('filename')
                    if filename:
                        expected_path = os.path.normpath(os.path.join(ann_dir, filename))
                        saved_path = os.path.normpath(video_info.get('path', ''))
                        if expected_path != saved_path:
                            self.annotations.setdefault('video_info', {})['path'] = expected_path
                            print(f"已将视频路径校正为: {expected_path}")
                except Exception as e:
                    print(f"校正视频路径时出现问题: {e}")
                # 为历史数据补充视角字段缺省值
                self._ensure_view_desc_defaults()
                self.statusBar().showMessage(f"标注已从 {os.path.basename(file_path)} 加载", 3000)
                print(f"标注成功从 {file_path} 加载。")
                
                # 【关键】加载后，必须全面刷新UI
                self.update_match_info_ui()
                self.refresh_all_ui()
                self.refresh_ui_for_current_frame()
                self.data_is_dirty = False  # 加载后重置脏数据标志
                
            except FileNotFoundError:
                QMessageBox.warning(self, "加载失败", f"文件不存在：\n{file_path}")
            except json.JSONDecodeError as e:
                QMessageBox.warning(self, "加载失败", f"JSON格式错误：\n{str(e)}\n\n请检查文件是否损坏。")
            except PermissionError:
                QMessageBox.warning(self, "加载失败", f"无法读取文件：权限不足。\n请检查文件权限。")
            except Exception as e:
                QMessageBox.critical(self, "加载失败", f"加载标注时发生错误：\n{str(e)}")
                print(f"加载失败: {e}")

    def eventFilter(self, source, event):
        """
        全局事件过滤器，用于处理所有快捷键（修复版）。
        """
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            # 统一使用 Qt.KeyboardModifier
            modifiers = event.modifiers()
            normalized_modifiers = modifiers & ~Qt.KeyboardModifier.KeypadModifier

            active_window = QApplication.activeWindow()
            if active_window and isinstance(active_window, QDialog):
                return False
            focus_widget = QApplication.focusWidget()
            if focus_widget and isinstance(focus_widget, QLineEdit):
                return False
            
            # --- 播放控制 ---
            if key == Qt.Key.Key_Space:
                self.toggle_play_pause()
                return True
            # <<< ================== 核心修正 ================== >>>
            elif key == Qt.Key.Key_Left and normalized_modifiers == Qt.KeyboardModifier.NoModifier:
                self.seek_video(max(0, self.current_frame_num - 1))
                return True
            elif key == Qt.Key.Key_Right and normalized_modifiers == Qt.KeyboardModifier.NoModifier:
                self.seek_video(min(self.slider.maximum(), self.current_frame_num + 1))
                return True
            elif key == Qt.Key.Key_Left and normalized_modifiers == Qt.KeyboardModifier.ControlModifier:
                self.step_frames(forward=False)
                return True
            elif key == Qt.Key.Key_Right and normalized_modifiers == Qt.KeyboardModifier.ControlModifier:
                self.step_frames(forward=True)
                return True
            elif key == Qt.Key.Key_Left and normalized_modifiers == Qt.KeyboardModifier.ShiftModifier:
                # Shift + Left: 将选中事件的帧号减1
                self.adjust_selected_event_frame(-1)
                return True
            elif key == Qt.Key.Key_Right and normalized_modifiers == Qt.KeyboardModifier.ShiftModifier:
                # Shift + Right: 将选中事件的帧号加1
                self.adjust_selected_event_frame(1)
                return True
            elif key == Qt.Key.Key_Up and normalized_modifiers == Qt.KeyboardModifier.NoModifier:
                # Up: 选中上一个事件
                self.navigate_to_adjacent_event(-1)
                return True
            elif key == Qt.Key.Key_Down and normalized_modifiers == Qt.KeyboardModifier.NoModifier:
                # Down: 选中下一个事件
                self.navigate_to_adjacent_event(1)
                return True
            elif key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
                # Enter: 打开选中事件的技术动作编辑对话框
                # 检查是否有对话框打开，如果有就不拦截Enter键
                if normalized_modifiers == Qt.KeyboardModifier.NoModifier:
                    self.edit_selected_event()
                    return True

            # --- 事件标注 ---
            elif key == Qt.Key.Key_S and normalized_modifiers == Qt.KeyboardModifier.ShiftModifier:
                self.add_set_end_event()
                return True
            elif key == Qt.Key.Key_S and normalized_modifiers == Qt.KeyboardModifier.NoModifier:
                self.add_set_start_event()
                return True
            # <<< =============================================== >>>
            elif key == Qt.Key.Key_R:
                self.add_rally_start_event()
                return True
            elif key == Qt.Key.Key_E:
                self.add_rally_end_event()
                return True
            elif key == Qt.Key.Key_I:
                self.add_shot_event()
                return True

            # --- 标注模式 ---
            elif key == Qt.Key.Key_Q:
                self.on_mode_button_clicked("select")
                return True
            elif key == Qt.Key.Key_W:
                self.on_mode_button_clicked("box")
                return True
            elif key == Qt.Key.Key_A:
                self.on_mode_button_clicked("point")
                return True

            # --- 数据操作 ---
            elif key == Qt.Key.Key_Delete or key == Qt.Key.Key_Backspace:
                self.delete_selected_event()
                return True
            elif key == Qt.Key.Key_S and normalized_modifiers == Qt.KeyboardModifier.ControlModifier:
                self.save_annotations()
                return True
            elif key == Qt.Key.Key_O and normalized_modifiers == Qt.KeyboardModifier.ControlModifier:
                self.load_annotations()
                return True
        
        return super().eventFilter(source, event)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
