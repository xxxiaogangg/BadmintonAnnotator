# file: main.py

import sys
import uuid
import cv2
import os
import json
from pathlib import Path
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                             QPushButton, QSlider, QFileDialog, QGroupBox, QTreeWidget,
                             QListWidget, QMenuBar, QMenu, QListWidgetItem, QDialog, QCheckBox, QBoxLayout, QGridLayout)  # Add QGridLayout
from PyQt6.QtGui import QPixmap, QImage, QAction, QKeySequence, QShortcut, QIntValidator
from PyQt6.QtCore import Qt, QThread, QRect, QPoint, QTimer, QEvent
from PyQt6.QtWidgets import (QLabel, QSplitter, QComboBox, QMessageBox,
                             QStackedWidget, QLineEdit, QAbstractItemView, QSizePolicy) # Add QSizePolicy

from core.video_worker import VideoWorker
from widgets.drawing_label import DrawingLabel
from widgets.match_setup_dialog import MatchSetupDialog # 导入新对话框
from widgets.serve_player_dialog import ServePlayerDialog, WinnerSelectionDialog
from core.data_model import get_new_annotation_structure, normalize_annotations
from mixins.event_tree_mixin import EventTreeMixin
from mixins.review_mixin import ReviewMixin

DEFAULT_VIDEO_FPS = 30
AUTOSAVE_INTERVAL_MS = 60000

# 配置文件夹路径
ANNOTATOR_CONFIG_DIR = os.path.join(Path.home(), ".badminton_annotator")
CONFIG_FILE = os.path.join(ANNOTATOR_CONFIG_DIR, "config.json")


class MainWindow(EventTreeMixin, ReviewMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("羽毛球技战术分析工具 v2.2.2")
        self.setGeometry(100, 100, 1600, 900)
        # 支持拖拽文件进入窗口
        self.setAcceptDrops(True)

        # --- 核心变量 ---
        self.video_worker = None
        self.video_thread = None
        self.annotations = {}
        self._frame_annotations_cache = None
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
        self.event_by_id = {}  # event_id -> event dict，减少重复查找
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
        self.video_fps = DEFAULT_VIDEO_FPS

        # self._create_menu_bar()
        QApplication.instance().installEventFilter(self)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus) # 确保主窗口能接收焦点
        self._create_menu_bar()
        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        self.main_layout = QGridLayout(main_widget)
        left_panel = self._create_left_panel()

        # 创建右侧多页面面板（通过下拉框切换）
        right_panel = self._create_right_panel()

        # 将左右两大块添加到主布局
        # Row 0, Col 0: Video (Span 1 row, 1 col)
        self.main_layout.addWidget(left_panel, 0, 0)
        # Row 0, Col 1: Right Panel Tools (Span 1 row, 1 col)
        self.main_layout.addWidget(right_panel, 0, 1)
        
        # Set column stretch
        self.main_layout.setColumnStretch(0, 3)
        self.main_layout.setColumnStretch(1, 1)

        # 启动后检查上次打开的视频
        QTimer.singleShot(100, self._check_last_session)

    def dragEnterEvent(self, event):
        """允许拖拽本地文件到主窗口"""
        mime = event.mimeData()
        if not mime.hasUrls():
            event.ignore()
            return
        # 只要存在本地文件就允许进入，具体校验放到 dropEvent
        for url in mime.urls():
            if url.isLocalFile():
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event):
        """拖拽文件后尝试打开视频"""
        mime = event.mimeData()
        if not mime.hasUrls():
            event.ignore()
            return
        local_path = None
        for url in mime.urls():
            if url.isLocalFile():
                local_path = url.toLocalFile()
                break
        if not local_path:
            event.ignore()
            return
        if not os.path.exists(local_path):
            QMessageBox.warning(self, "打开失败", "拖拽的文件不存在。")
            return
        if os.path.isdir(local_path):
            QMessageBox.warning(self, "打开失败", "请拖拽视频文件，而不是文件夹。")
            return
        self.start_session(local_path)

    def _load_config(self):
        """加载配置文件"""
        if not os.path.exists(CONFIG_FILE):
            return {}
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
            return {}

    def _save_config(self, key, value):
        """保存配置项"""
        if not os.path.exists(ANNOTATOR_CONFIG_DIR):
            os.makedirs(ANNOTATOR_CONFIG_DIR, exist_ok=True)
        
        config = self._load_config()
        config[key] = value
        
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving config: {e}")

    def _check_last_session(self):
        """检查是否有上次打开的视频记录，并询问是否打开"""
        config = self._load_config()
        last_video = config.get("last_video_path")
        
        if last_video and os.path.exists(last_video):
            reply = QMessageBox.question(
                self, 
                "恢复上次会话", 
                f"是否重新打开上次查看的视频？\n\n{os.path.basename(last_video)}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.start_session(last_video)

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
        self.step_intervals = self._build_step_intervals(self.video_fps)
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
        self.right_panel_layout = QBoxLayout(QBoxLayout.Direction.TopToBottom, right_widget)
        self.right_panel_layout.setContentsMargins(5, 5, 5, 5)

        # 顶部：页面选择下拉框
        switch_layout = QHBoxLayout()
        switch_label = QLabel("右侧页面：")
        self.right_page_combo = QComboBox()
        self.right_page_combo.addItems(["球与运动员", "标注击球事件", "击球事件审阅", "击球事件审阅（横屏）", "AI辅助"])
        self.right_page_combo.setMaximumWidth(180)
        self.right_page_combo.currentIndexChanged.connect(self.on_right_page_changed)
        self.shot_loop_toggle = QCheckBox("击球循环")
        self.shot_loop_toggle.setToolTip("开启后，在两次击球之间循环播放")
        self.shot_loop_toggle.toggled.connect(self.on_shot_loop_toggled)
        switch_layout.addWidget(switch_label)
        switch_layout.addWidget(self.right_page_combo)
        switch_layout.addWidget(self.shot_loop_toggle)
        switch_layout.addStretch()
        self.right_panel_layout.addLayout(switch_layout)

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

        self.right_panel_layout.addWidget(self.right_stacked)

        # --- 通用事件浏览器（两个页面共用） ---
        self.events_box = QGroupBox("事件浏览器")
        events_layout = QVBoxLayout(self.events_box)
        self.event_tree = QTreeWidget()
        self.event_tree.setHeaderLabels(["事件", "详情"])
        self.event_tree.itemClicked.connect(self.on_event_tree_item_clicked)
        self.event_tree.itemDoubleClicked.connect(self.on_event_tree_item_double_clicked)
        events_layout.addWidget(self.event_tree)
        self.events_box.setLayout(events_layout)
        self.right_panel_layout.addWidget(self.events_box, 1)  # 让事件树占据更多垂直空间

        # 默认显示第一个页面
        self.right_stacked.setCurrentIndex(0)
        self.right_page_combo.setCurrentIndex(0)

        return right_widget

    def on_right_page_changed(self, index: int):
        """右侧页面下拉框切换时，切换堆叠窗口页面，并处理布局变化"""
        # 下拉框索引映射到 StackedWidget 索引
        # 0: 球与运动员 -> Stacked 0
        # 1: 标注击球事件 -> Stacked 1
        # 2: 击球事件审阅 -> Stacked 2
        # 3: 击球事件审阅（横屏）-> Stacked 2 (复用审阅页面)
        # 4: AI辅助 -> (如果 Stacked 有对应页面的话，可能是 3? 但原代码只添加了3个页面)

        # 之前的代码添加了3个页面到 right_stacked:
        # page_objects (0), page_events (1), page_review (2)
        
        target_stack_index = index
        is_horizontal_mode = False

        if index == 3: # 击球事件审阅（横屏）
            target_stack_index = 2 # 复用审阅页面
            is_horizontal_mode = True
        elif index > 3:
            target_stack_index = index - 1 # AI辅助等后续项往前挪一位

        if hasattr(self, "right_stacked") and 0 <= target_stack_index < self.right_stacked.count():
            self.right_stacked.setCurrentIndex(target_stack_index)
        
        # 切换布局模式
        self._set_layout_mode(is_horizontal_mode)

        # 在“击球事件审阅”页面（非横屏模式）时，让上方堆叠区域高度尽量贴合
        if hasattr(self, "review_box"):
            if index == 2:  # 竖屏审阅
                h = self.review_box.sizeHint().height() + 20
                self.right_stacked.setMaximumHeight(h)
            else:
                self.right_stacked.setMaximumHeight(16777215)

    def _set_layout_mode(self, horizontal_review: bool):
        """
        切换布局模式
        horizontal_review: True 表示开启横屏审阅模式 (事件浏览器在底部全宽)
                           False 表示默认模式 (事件浏览器在右侧面板底部)
        """
        if horizontal_review:
            # 1. 从右侧面板移除 events_box
            if self.events_box.parent() != self.centralWidget():
                 self.right_panel_layout.removeWidget(self.events_box)
                 self.events_box.setParent(None)
            
            # 2. 添加到主 Grid 布局的底部 (Row 1, Spanning 2 columns)
            self.main_layout.addWidget(self.events_box, 1, 0, 1, 2)
            self.events_box.show()
            
            # 2a. 允许视频区域缩小，防止撑大窗口
            # Video: Ignored (可以尽可能缩小), Right Panel: Preferred
            if hasattr(self, 'video_label'):
                 self.video_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

            # 3. 调整 Video 和 Tools 的比例 (Row 0)
            self.main_layout.setColumnStretch(0, 2)  # Video
            self.main_layout.setColumnStretch(1, 1)  # Tools
            self.main_layout.setRowStretch(0, 3) # Upper Area (Give more space to video if possible)
            self.main_layout.setRowStretch(1, 1) # Bottom Area (Events)
            
            # 右侧面板保持垂直 (恢复之前的改动)
            self.right_panel_layout.setDirection(QBoxLayout.Direction.TopToBottom)
            
        else:
            # 恢复 Video Label 默认大小策略
            # 使用 Ignored + Layout Stretch 是最可靠的缩放方式，避免 Preferred 导致的尺寸固化
            if hasattr(self, 'video_label'):
                 self.video_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

            # 1. 从主布局移除 events_box
            self.main_layout.removeWidget(self.events_box)
            self.events_box.setParent(None)
            
            # 2. 放回右侧面板底部
            self.right_panel_layout.addWidget(self.events_box, 1)
            self.events_box.show()
            
            # 3. 恢复标准比例
            self.main_layout.setColumnStretch(0, 3) 
            self.main_layout.setColumnStretch(1, 1)
            self.main_layout.setRowStretch(0, 10)
            self.main_layout.setRowStretch(1, 0)
            
            # 右侧面板保持垂直
            self.right_panel_layout.setDirection(QBoxLayout.Direction.TopToBottom)
   
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
                json.dump(self.annotations, f, indent=4, ensure_ascii=False)
            
            # 状态栏提示用户
            self.statusBar().showMessage(f"已自动备份标注。", 2000) # 显示2秒
            self.data_is_dirty = False # 保存后，将数据标记为“干净”
            print(f"自动保存成功: {backup_path}")

        except PermissionError:
            self.statusBar().showMessage("自动备份失败：权限不足。", 3000)
            print(f"自动保存失败: 权限不足 -> {backup_path}")
        except OSError as e:
            self.statusBar().showMessage("自动备份失败：文件错误。", 3000)
            print(f"自动保存失败: {e}")
        except Exception as e:
            self.statusBar().showMessage("自动备份失败：未知错误。", 3000)
            print(f"自动保存失败: {e}")

    def set_dirty(self):
        """将数据标记为已修改"""
        self.data_is_dirty = True

    def _build_step_intervals(self, fps):
        base_fps = int(fps) if fps and fps > 0 else DEFAULT_VIDEO_FPS
        return {"1 帧": 1, "10 帧": 10, "1 秒": base_fps, "5 秒": base_fps * 5}

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

    def _build_frame_annotations_cache(self):
        frame_annotations = self.annotations.get("frame_annotations", {})
        cache = {}
        if isinstance(frame_annotations, dict):
            for key, value in frame_annotations.items():
                try:
                    frame_num = int(key)
                except (TypeError, ValueError):
                    continue
                if not isinstance(value, list):
                    value = []
                    frame_annotations[str(frame_num)] = value
                cache[frame_num] = value
        self._frame_annotations_cache = cache

    def _get_frame_annotations(self, frame_num, create=False):
        if self._frame_annotations_cache is None:
            self._build_frame_annotations_cache()
        if frame_num in self._frame_annotations_cache:
            return self._frame_annotations_cache[frame_num]
        if not create:
            return []
        objects = []
        self._set_frame_annotations(frame_num, objects)
        return objects

    def _set_frame_annotations(self, frame_num, objects):
        self.annotations.setdefault("frame_annotations", {})[str(frame_num)] = objects
        if self._frame_annotations_cache is None:
            self._frame_annotations_cache = {}
        self._frame_annotations_cache[frame_num] = objects

    def add_annotation_to_frame(self, frame_num, annotation_obj):
        """通用辅助函数：将一个标注对象添加到指定帧"""
        objects_on_frame = self._get_frame_annotations(frame_num, create=True)
        objects_on_frame.append(annotation_obj)
        
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
        frame_data = self._get_frame_annotations(self.current_frame_num)
        
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
            
        frame_data = self._get_frame_annotations(self.current_frame_num)
        if not frame_data:
            return
        
        # 使用列表推导式过滤掉要删除的对象
        frame_data = [
            obj for obj in frame_data if obj['id'] != self.selected_object_id
        ]
        self._set_frame_annotations(self.current_frame_num, frame_data)
        
        print(f"已删除对象: {self.selected_object_id}")
        # 清除选中状态并刷新UI
        self.set_selected_object(None)
        self.refresh_ui_for_current_frame()

    def refresh_ui_for_current_frame(self):
        if self.current_frame_num < 0: return
        
        # 切换帧时，清除旧的选中状态
        self.set_selected_object(None)
        
        objects_on_frame = self._get_frame_annotations(self.current_frame_num)
        self.video_label.load_frame_annotations(objects_on_frame)
        
        self.frame_objects_list.clear()
        for obj in objects_on_frame:
            self.frame_objects_list.addItem(obj['id'])

    def open_video_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择视频文件", "", "Video Files (*.mp4 *.avi)")
        if not file_path: return
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "打开失败", "视频文件不存在，请重新选择。")
            print(f"打开失败: 文件不存在 -> {file_path}")
            return

        self.start_session(file_path)

    def start_session(self, video_path):
        """
        启动一个工作会话的核心函数，负责加载视频和关联的标注。
        """
        if not os.path.exists(video_path):
            QMessageBox.warning(self, "打开失败", "视频文件不存在，请重新选择。")
            print(f"打开失败: 文件不存在 -> {video_path}")
            return
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
        self.video_worker.playback_finished.connect(self.on_video_playback_finished)
        self.video_thread.started.connect(self.video_worker.run)
        self.video_worker.finished.connect(self.video_thread.quit)
        self.video_worker.finished.connect(self.video_worker.deleteLater)
        self.video_thread.finished.connect(self.video_thread.deleteLater)
        self.video_thread.start()

        # 成功启动会话后，记录到配置文件
        self._save_config("last_video_path", video_path)

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
            did_load_file = self.load_annotations(backup_path)
        elif os.path.exists(annotation_path):
            print(f"自动加载主标注文件: {annotation_path}")
            did_load_file = self.load_annotations(annotation_path)
        else:
            print("未找到任何标注文件，将创建新的标注。")
            self.annotations = {}
            self._frame_annotations_cache = None
            self.update_match_info_ui()
            self._reset_event_tree_view()
            self.refresh_ui_for_current_frame()

                # 将弹窗逻辑移到这里
        if not did_load_file:
            print("未找到任何标注文件，将为新会话初始化。")
            # 只有在没有加载任何文件的情况下，才创建新标注并弹窗
            
            # 先获取视频元数据来初始化
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                QMessageBox.critical(self, "视频错误", "无法读取视频元数据，请检查文件是否损坏。")
                print(f"读取视频元数据失败: {video_path}")
                cap.release()
                return
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
            self._build_frame_annotations_cache()
            
            # 弹出比赛设置对话框
            dialog = MatchSetupDialog(self.annotations['match_info'], self)
            if dialog.exec():
                updated_info = dialog.get_data()
                self.annotations['match_info'].update(updated_info)
            
            # 更新UI
            self.update_match_info_ui()
            self._reset_event_tree_view()
            self.refresh_ui_for_current_frame()

    def on_video_error(self, error_message):
        """处理视频加载或播放错误"""
        QMessageBox.critical(self, "视频错误", f"视频处理时发生错误：\n{error_message}")
        print(f"视频错误: {error_message}")

    def on_video_playback_finished(self, last_frame_num):
        """播放结束后，回退到暂停状态并更新UI"""
        if self.video_worker:
            self.video_worker.set_playing(False)
        self.play_pause_btn.setText("▶ 播放")
        self.statusBar().showMessage("视频播放结束", 2000)
    
    def on_video_loaded(self, total_frames, fps):
        print(f"视频加载成功: {total_frames} 帧, {fps} FPS")
        self.slider.setRange(0, total_frames - 1)
        if hasattr(self, "review_jump_validator"):
            self.review_jump_validator.setTop(max(0, total_frames - 1))
        
        # 更新视频FPS，用于步进间隔计算
        self.video_fps = fps if fps > 0 else DEFAULT_VIDEO_FPS
        self.step_intervals = self._build_step_intervals(self.video_fps)
        
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
        
        # 启动自动保存
        self.autosave_timer.start(AUTOSAVE_INTERVAL_MS)
        
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
            objects_on_frame = self._get_frame_annotations(self.current_frame_num)
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
        self.event_by_id = {
            e.get('event_id'): e for e in events if isinstance(e, dict) and e.get('event_id')
        }
        hit_events = [
            e for e in events
            if e.get('type') in ['SHOT', 'RALLY_START'] and 'frame' in e
        ]
        return sorted(hit_events, key=lambda e: e.get('frame', 0))

    def _resolve_shot_loop_bounds(self):
        hit_events = self._get_hit_events_sorted()
        if not hit_events:
            return None

        center_frame = None
        if self.last_selected_event_id:
            selected_event = self.event_by_id.get(self.last_selected_event_id)
            if selected_event and selected_event.get("frame") is not None:
                center_frame = selected_event.get("frame")

        if center_frame is None:
            center_frame = self.current_frame_num

        start_index = None
        if self.last_selected_event_id:
            for i, event in enumerate(hit_events):
                if event.get('event_id') == self.last_selected_event_id:
                    start_index = i
                    break

        if start_index is None:
            for i, event in enumerate(hit_events):
                if event.get('frame', -1) <= center_frame:
                    start_index = i
                else:
                    break
            if start_index is None:
                start_index = 0

        if start_index + 1 >= len(hit_events):
            return None

        hit_start = hit_events[start_index].get('frame')
        hit_end = hit_events[start_index + 1].get('frame')
        if hit_start is None or hit_end is None or hit_end <= hit_start:
            return None

        duration = hit_end - hit_start
        if duration <= 0:
            return None

        pad_frames = max(1, int(round(self.video_fps * 0.5)))

        max_frame = 0
        if hasattr(self, "slider"):
            max_frame = self.slider.maximum()
        elif self.annotations.get("video_info"):
            max_frame = max(0, self.annotations["video_info"].get("total_frames", 1) - 1)

        desired_length = duration + (pad_frames * 2)
        half = desired_length // 2
        start_frame = int(center_frame - half)
        if start_frame < 0:
            start_frame = 0
        end_frame = start_frame + desired_length
        if end_frame > max_frame:
            end_frame = max_frame
            start_frame = max(0, end_frame - desired_length)

        if end_frame <= start_frame:
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
        updated_events = self.reevaluate_players_in_rally(start_index)

        print(f"在帧 {frame_to_add} 添加了待定击球事件，并已刷新回合内球员顺序。")
        if updated_events:
            self._update_event_items(updated_events)

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
        updated_events = []
        
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
                updated_events.append(events[i])
        return updated_events

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
        if hasattr(self, "event_by_id"):
            self.event_by_id[event_obj.get('event_id')] = event_obj
        
        # 重新计算比分以确保数据一致性（特别是当用户手动编辑事件时）
        # 对于可能影响比分的事件，重新计算整个比分历史
        if event_obj['type'] in ['RALLY_END', 'SET_START']:
            self.recalculate_scores()

        inserted = None
        events = self.annotations.get('events', [])
        if events and events[-1] is event_obj:
            inserted = self._insert_event_item(event_obj)

        if inserted:
            self.update_review_stats()
            self.event_tree.scrollToItem(inserted, QAbstractItemView.ScrollHint.PositionAtCenter)
        else:
            rebuilt = False
            if hasattr(self, "_rebuild_set_subtree"):
                event_index = events.index(event_obj)
                set_start_index = self._find_set_start_index(events, event_index)
                if set_start_index >= 0 and event_obj.get("type") != "SET_START":
                    rebuilt = self._rebuild_set_subtree(set_start_index)
            if rebuilt:
                self.update_review_stats()
                self._select_event_in_tree(event_obj['event_id'])
            else:
                self.refresh_all_ui(scroll_to_event_id=event_obj['event_id'])
        self.set_dirty()

    def _ensure_view_desc_defaults(self):
        """为历史数据补充视角字段缺省值"""
        events = self.annotations.get('events', [])
        for e in events:
            details = e.get('details')
            if isinstance(details, dict) and 'view_desc' not in details:
                details['view_desc'] = "视角正常"
    
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
        if hasattr(self, "_refresh_score_related_items"):
            self._refresh_score_related_items()

    def save_annotations(self):
        if not self.annotations:
            QMessageBox.information(self, "提示", "没有标注可以保存。")
            return
        
        default_path = self.annotations['video_info']['path'] + ".json"
        file_path, _ = QFileDialog.getSaveFileName(self, "保存标注文件", default_path, "JSON Files (*.json)")

        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
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
                QMessageBox.warning(self, "保存失败", "无法保存文件：权限不足。\n请检查文件是否被其他程序占用。")
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
        if not file_path:
            return False
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                self.annotations = json.load(f)
            self.annotations = normalize_annotations(self.annotations)
            self._build_frame_annotations_cache()
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
            if self.annotations.get("events"):
                self.refresh_all_ui()
            else:
                self._reset_event_tree_view()
            self.refresh_ui_for_current_frame()
            self.data_is_dirty = False  # 加载后重置脏数据标志
            return True
        except FileNotFoundError:
            QMessageBox.warning(self, "加载失败", "文件不存在，请重新选择。")
            print(f"加载失败: 文件不存在 -> {file_path}")
        except PermissionError:
            QMessageBox.warning(self, "加载失败", "无法读取文件：权限不足。\n请检查文件权限。")
            print(f"加载失败: 权限不足 -> {file_path}")
        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "加载失败", f"标注文件格式错误：\n{e}\n\n请检查文件是否损坏。")
            print(f"加载失败: JSON解析错误 -> {e}")
        except OSError as e:
            QMessageBox.critical(self, "加载失败", f"无法读取标注文件：\n{e}")
            print(f"加载失败: {e}")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"加载标注时发生错误：\n{str(e)}")
            print(f"加载失败: {e}")
        return False

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
