# file: main.py

import sys
import uuid
import cv2
import numpy as np
import os
import json
from pathlib import Path
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                             QPushButton, QSlider, QFileDialog, QGroupBox, QTreeWidget,
                             QListWidget, QMenuBar, QMenu, QListWidgetItem, QDialog, QCheckBox)  # Add QListWidgetItem
from PyQt6.QtGui import QPixmap, QImage, QAction, QKeySequence, QShortcut, QIntValidator
from PyQt6.QtCore import Qt, QThread, QRect, QPoint, QTimer, QEvent
from PyQt6.QtWidgets import (QLabel, QSplitter, QComboBox, QMessageBox,
                             QStackedWidget, QLineEdit, QAbstractItemView)

from core.video_worker import VideoWorker
from ai.person_detector import YoloPersonDetector
from scripts.export_json_to_shan_xls import default_output_path, write_xls
from widgets.drawing_label import DrawingLabel
from widgets.match_setup_dialog import MatchSetupDialog # 导入新对话框
from widgets.serve_player_dialog import CourtSideAssignmentDialog, ServePlayerDialog, WinnerSelectionDialog
from core.data_model import (
    COURT_POINT_ORDER,
    COURT_SIDE_ASSIGNMENT_VERSION,
    get_default_court_calibration,
    get_new_annotation_structure,
    normalize_annotations,
    normalize_court_calibration,
    normalize_court_side_assignment,
)
from mixins.event_tree_mixin import EventTreeMixin
from mixins.review_mixin import ReviewMixin

DEFAULT_VIDEO_FPS = 30
AUTOSAVE_INTERVAL_MS = 60000


class MainWindow(EventTreeMixin, ReviewMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("羽毛球技战术分析工具 v2.0")
        self.setGeometry(100, 100, 1600, 900)

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
        self.current_rgb_frame = None
        self.current_frame_size = None
        self.person_detector = None
        self.person_detector_warning_shown = False
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

        export_xls_action = QAction("导出xls", self)
        export_xls_action.triggered.connect(self.export_current_annotations_to_xls)
        file_menu.addAction(export_xls_action)

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
        self.video_label.court_point_moved.connect(self.on_court_point_moved)
        
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

        # 导出
        self.export_xls_btn = QPushButton("导出xls")
        self.export_xls_btn.clicked.connect(self.export_current_annotations_to_xls)
        
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
        buttons_layout.addWidget(self.export_xls_btn)
        buttons_layout.addSpacing(20)
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

        # 页面3：AI辅助
        self.right_stacked.addWidget(self._create_ai_panel())

        layout.addWidget(self.right_stacked)

        # --- 通用事件浏览器（两个页面共用） ---
        events_box = QGroupBox("事件浏览器")
        events_layout = QVBoxLayout(events_box)
        self.event_tree = QTreeWidget()
        self.event_tree.setHeaderLabels(["事件", "详情"])
        self.event_tree.setUniformRowHeights(True)
        self.event_tree.setColumnWidth(0, 180)
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

    def _create_ai_panel(self):
        ai_widget = QWidget()
        layout = QVBoxLayout(ai_widget)
        layout.setContentsMargins(5, 5, 5, 5)

        court_box = QGroupBox("场地标定")
        court_layout = QVBoxLayout(court_box)

        court_toggle_layout = QHBoxLayout()
        self.court_edit_toggle = QCheckBox("调整场地点")
        self.court_edit_toggle.toggled.connect(self.on_court_edit_toggled)
        self.reset_court_btn = QPushButton("重置默认8点")
        self.reset_court_btn.clicked.connect(self.reset_court_calibration)
        court_toggle_layout.addWidget(self.court_edit_toggle)
        court_toggle_layout.addWidget(self.reset_court_btn)
        court_layout.addLayout(court_toggle_layout)

        self.court_status_label = QLabel("未加载场地")
        court_layout.addWidget(self.court_status_label)

        layout.addWidget(court_box)

        side_box = QGroupBox("上下半场")
        side_layout = QVBoxLayout(side_box)
        self.court_side_status_label = QLabel("未设置")
        self.set_court_side_btn = QPushButton("设置第1局开局站位")
        self.set_court_side_btn.clicked.connect(self.configure_court_side_assignment)
        side_layout.addWidget(self.court_side_status_label)
        side_layout.addWidget(self.set_court_side_btn)
        layout.addWidget(side_box)

        detector_box = QGroupBox("YOLO位置默认")
        detector_layout = QVBoxLayout(detector_box)
        self.person_detector_status_label = QLabel("按需加载；不可用时自动跳过")
        detector_layout.addWidget(self.person_detector_status_label)
        layout.addWidget(detector_box)

        layout.addStretch()
        return ai_widget

    def _get_video_resolution(self):
        video_info = self.annotations.get("video_info", {}) if self.annotations else {}
        resolution = video_info.get("resolution")
        if isinstance(resolution, (list, tuple)) and len(resolution) >= 2:
            try:
                width = int(resolution[0])
                height = int(resolution[1])
                if width > 0 and height > 0:
                    return [width, height]
            except (TypeError, ValueError):
                pass
        width = getattr(self.video_label, "original_video_width", 1280)
        height = getattr(self.video_label, "original_video_height", 720)
        return [width, height]

    def _ensure_court_calibration(self):
        if not self.annotations:
            return None
        court = normalize_court_calibration(
            self.annotations.get("court_calibration"),
            self._get_video_resolution(),
        )
        self.annotations["court_calibration"] = court
        return court

    def _sync_court_overlay(self):
        court = self._ensure_court_calibration()
        if hasattr(self, "video_label"):
            self.video_label.set_court_calibration(court)
        self._sync_court_edit_toggle()
        self._update_court_status_label()
        self._update_court_side_status_label()

    def _sync_court_edit_toggle(self):
        court = self.annotations.get("court_calibration") if self.annotations else None
        edit_enabled = bool(court and not court.get("locked", True))
        if hasattr(self, "court_edit_toggle"):
            self.court_edit_toggle.blockSignals(True)
            self.court_edit_toggle.setChecked(edit_enabled)
            self.court_edit_toggle.blockSignals(False)
        if hasattr(self, "video_label"):
            self.video_label.set_court_edit_enabled(edit_enabled)

    def _update_court_status_label(self):
        if not hasattr(self, "court_status_label"):
            return
        court = self.annotations.get("court_calibration") if self.annotations else None
        if not isinstance(court, dict):
            self.court_status_label.setText("未加载场地")
            return
        points = court.get("points") if isinstance(court.get("points"), dict) else {}
        point_count = sum(1 for point_id in COURT_POINT_ORDER if point_id in points)
        mode_text = "可调整" if not court.get("locked", True) else "已锁定"
        self.court_status_label.setText(f"{mode_text} | 单打4点 + 球网4点 ({point_count}/8)")

    def _normalize_current_court_side_assignment(self):
        if not self.annotations:
            return None
        assignment = normalize_court_side_assignment(
            self.annotations.get("court_side_assignment"),
            self.annotations.get("match_info", {}),
        )
        self.annotations["court_side_assignment"] = assignment
        return assignment

    def _update_court_side_status_label(self):
        if not hasattr(self, "court_side_status_label"):
            return
        assignment = self._normalize_current_court_side_assignment()
        if not assignment:
            self.court_side_status_label.setText("未设置")
            return
        top_player = assignment.get("initial_top_player", "")
        bottom_player = assignment.get("initial_bottom_player", "")
        self.court_side_status_label.setText(f"第1局开局：上方 {top_player} / 下方 {bottom_player}")

    def configure_court_side_assignment(self):
        if not self.annotations:
            QMessageBox.information(self, "提示", "请先打开视频。")
            return
        match_info = self.annotations.get("match_info", {})
        player_a = match_info.get("player_a") or self.player_a_name
        player_b = match_info.get("player_b") or self.player_b_name
        if not player_a or not player_b or player_a == player_b:
            QMessageBox.warning(self, "站位信息缺失", "请先在比赛信息中设置两名不同的球员。")
            return
        dialog = CourtSideAssignmentDialog(player_a, player_b, self)
        if not dialog.exec() or not dialog.assignment:
            return
        self.annotations["court_side_assignment"] = {
            "version": COURT_SIDE_ASSIGNMENT_VERSION,
            "initial_top_player": dialog.assignment["initial_top_player"],
            "initial_bottom_player": dialog.assignment["initial_bottom_player"],
            "source": "manual",
        }
        self._update_court_side_status_label()
        self.set_dirty()

    def on_court_edit_toggled(self, checked):
        if not self.annotations:
            self.court_edit_toggle.blockSignals(True)
            self.court_edit_toggle.setChecked(False)
            self.court_edit_toggle.blockSignals(False)
            QMessageBox.information(self, "提示", "请先打开视频。")
            return
        court = self._ensure_court_calibration()
        if not court:
            return
        court["locked"] = not checked
        court["visible"] = True
        if checked:
            self.on_mode_button_clicked("select")
        self.video_label.set_court_calibration(court)
        self.video_label.set_court_edit_enabled(checked)
        self._update_court_status_label()
        self.set_dirty()

    def reset_court_calibration(self):
        if not self.annotations:
            QMessageBox.information(self, "提示", "请先打开视频。")
            return
        court = get_default_court_calibration(self._get_video_resolution())
        court["locked"] = not self.court_edit_toggle.isChecked()
        self.annotations["court_calibration"] = court
        self._sync_court_overlay()
        self.set_dirty()

    def on_court_point_moved(self, point_id, coords):
        court = self.annotations.get("court_calibration") if self.annotations else None
        if not isinstance(court, dict):
            return
        points = court.get("points")
        if not isinstance(points, dict) or point_id not in points:
            return
        try:
            points[point_id]["x"] = int(coords[0])
            points[point_id]["y"] = int(coords[1])
        except (TypeError, ValueError, IndexError):
            return
        self._update_court_status_label()
        self.set_dirty()

    def _get_person_detector(self):
        if self.person_detector is None:
            self.person_detector = YoloPersonDetector()
        return self.person_detector

    def _set_person_detector_status(self, message):
        if hasattr(self, "person_detector_status_label"):
            self.person_detector_status_label.setText(message)

    def _note_person_detector_unavailable(self):
        detector = self.person_detector
        reason = detector.last_error if detector and detector.last_error else "YOLO不可用，位置默认保持待定。"
        self._set_person_detector_status("不可用，已自动跳过")
        if not self.person_detector_warning_shown:
            self.statusBar().showMessage(reason, 4000)
            self.person_detector_warning_shown = True

    def _get_ai_frame_for_event(self, frame_num):
        if (
            self.current_rgb_frame is not None
            and self.current_frame_num == frame_num
            and self.current_frame_size
        ):
            frame = self.current_rgb_frame
            frame_h, frame_w = frame.shape[:2]
            original_w = max(1, int(getattr(self.video_label, "original_video_width", frame_w)))
            original_h = max(1, int(getattr(self.video_label, "original_video_height", frame_h)))
            return frame, original_w / frame_w, original_h / frame_h

        video_path = self.annotations.get("video_info", {}).get("path")
        if not video_path or not os.path.exists(video_path):
            return None, 1.0, 1.0
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            cap.release()
            return None, 1.0, 1.0
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ok, frame_bgr = cap.read()
        cap.release()
        if not ok:
            return None, 1.0, 1.0
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        return frame_rgb, 1.0, 1.0

    def _court_geometry_for_ai(self):
        court = self._ensure_court_calibration()
        if not court:
            return None
        points = court.get("points") if isinstance(court.get("points"), dict) else {}
        required = [
            "singles_far_left",
            "singles_far_right",
            "singles_near_right",
            "singles_near_left",
            "net_left_bottom",
            "net_right_bottom",
        ]
        if not all(point_id in points for point_id in required):
            return None
        try:
            court_polygon = np.array(
                [
                    [points["singles_far_left"]["x"], points["singles_far_left"]["y"]],
                    [points["singles_far_right"]["x"], points["singles_far_right"]["y"]],
                    [points["singles_near_right"]["x"], points["singles_near_right"]["y"]],
                    [points["singles_near_left"]["x"], points["singles_near_left"]["y"]],
                ],
                dtype=np.float32,
            )
            canonical = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)
            homography = cv2.getPerspectiveTransform(court_polygon, canonical)
            net_points_video = np.array(
                [
                    [
                        [points["net_left_bottom"]["x"], points["net_left_bottom"]["y"]],
                        [points["net_right_bottom"]["x"], points["net_right_bottom"]["y"]],
                    ]
                ],
                dtype=np.float32,
            )
            net_points_court = cv2.perspectiveTransform(net_points_video, homography)[0]
            return {
                "court_polygon": court_polygon,
                "homography": homography,
                "net_left": net_points_court[0],
                "net_right": net_points_court[1],
            }
        except (TypeError, ValueError, KeyError):
            return None

    def _net_y_at_court_x(self, court_x, geometry):
        left = geometry["net_left"]
        right = geometry["net_right"]
        left_x, left_y = float(left[0]), float(left[1])
        right_x, right_y = float(right[0]), float(right[1])
        if abs(right_x - left_x) < 1e-6:
            return (left_y + right_y) / 2
        ratio = (float(court_x) - left_x) / (right_x - left_x)
        return left_y + ratio * (right_y - left_y)

    def _court_position_from_video_point(self, point_video, geometry, court_half):
        src = np.array([[[float(point_video[0]), float(point_video[1])]]], dtype=np.float32)
        mapped = cv2.perspectiveTransform(src, geometry["homography"])[0, 0]
        x, y = float(mapped[0]), float(mapped[1])
        if not np.isfinite(x) or not np.isfinite(y):
            return None
        net_y = self._net_y_at_court_x(x, geometry)
        if court_half == "top":
            denominator = max(net_y, 1e-6)
            depth = (net_y - y) / denominator
        else:
            denominator = max(1 - net_y, 1e-6)
            depth = (y - net_y) / denominator
        x = min(1, max(0, x))
        depth = min(1, max(0, depth))
        col = "左" if x < 1 / 3 else ("中" if x < 2 / 3 else "右")
        row = "前" if depth < 1 / 3 else ("中" if depth < 2 / 3 else "后")
        return f"{row}{col}"

    def _default_shot_major_from_position(self, court_position):
        if not court_position:
            return None
        if court_position.startswith("前"):
            return "网前技术"
        if court_position.startswith("中"):
            return "中场技术"
        if court_position.startswith("后"):
            return "后场技术"
        return None

    def _suggest_court_position_for_event(self, event_obj):
        if not event_obj or event_obj.get("type") not in ["RALLY_START", "SHOT"]:
            return None
        frame_num = event_obj.get("frame")
        if frame_num is None:
            return None

        player_half = self._resolve_player_court_half(event_obj)
        if player_half not in ["top", "bottom"]:
            return None
        court_geometry = self._court_geometry_for_ai()
        if not court_geometry:
            return None

        frame_rgb, scale_x, scale_y = self._get_ai_frame_for_event(frame_num)
        if frame_rgb is None:
            return None
        detector = self._get_person_detector()
        detections = detector.detect(frame_rgb)
        if detector.disabled:
            self._note_person_detector_unavailable()
            return None
        self._set_person_detector_status("可用")
        if not detections:
            return None

        target_candidates = []
        fallback_candidates = []
        for detection in detections:
            foot = detection.get("foot")
            if not foot:
                continue
            foot_video = [int(foot[0] * scale_x), int(foot[1] * scale_y)]
            position = self._court_position_from_video_point(foot_video, court_geometry, player_half)
            if not position:
                continue
            src = np.array([[[float(foot_video[0]), float(foot_video[1])]]], dtype=np.float32)
            mapped = cv2.perspectiveTransform(src, court_geometry["homography"])[0, 0]
            court_x, court_y = float(mapped[0]), float(mapped[1])
            net_y = self._net_y_at_court_x(court_x, court_geometry)
            in_target_half = court_y <= net_y + 0.08 if player_half == "top" else court_y >= net_y - 0.08
            item = dict(detection)
            item["foot_video"] = foot_video
            item["court_position"] = position
            item["court_distance"] = cv2.pointPolygonTest(
                court_geometry["court_polygon"],
                tuple(foot_video),
                True,
            )
            item["in_target_half"] = in_target_half
            bbox = detection.get("bbox", [0, 0, 0, 0])
            item["bbox_height"] = max(0, int(bbox[3]) - int(bbox[1])) if len(bbox) >= 4 else 0
            fallback_candidates.append(item)
            if item["court_distance"] >= -60 and in_target_half:
                target_candidates.append(item)

        if not fallback_candidates:
            return None
        if target_candidates:
            target = sorted(
                target_candidates,
                key=lambda item: (
                    item["in_target_half"],
                    item["court_distance"] >= 0,
                    item["court_distance"],
                    item["bbox_height"],
                    item.get("confidence", 0),
                ),
                reverse=True,
            )[0]
        else:
            fallback_candidates = sorted(fallback_candidates, key=lambda item: item["foot_video"][1])
            target = fallback_candidates[0] if player_half == "top" else fallback_candidates[-1]
        return target.get("court_position")

    def apply_ai_court_position_default(self, event_obj, details):
        if not isinstance(details, dict):
            return {}
        changes = {}
        current_position = details.get("court_position")
        if not current_position or current_position == "待定":
            suggestion = self._suggest_court_position_for_event(event_obj)
            if suggestion:
                details["court_position"] = suggestion
                current_position = suggestion
                changes["court_position"] = suggestion
                self._set_person_detector_status(f"可用：建议 {suggestion}")
                print(f"YOLO位置默认: {event_obj.get('event_id', '')} -> {suggestion}")

        if event_obj.get("type") == "SHOT":
            current_major = details.get("major")
            default_major = self._default_shot_major_from_position(current_position)
            if default_major and (not current_major or current_major == "待定"):
                details["major"] = default_major
                changes["major"] = default_major
                print(f"位置默认大类: {event_obj.get('event_id', '')} -> {default_major}")

        return changes

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

        self.current_frame_num = -1
        self.current_rgb_frame = None
        self.current_frame_size = None

        # 2. 先处理标注恢复/加载，避免视频线程回调和大事件树刷新同时争用主线程。
        did_load_file = self._load_session_annotation(video_path)
        if not did_load_file:
            if not self._initialize_new_session_annotations(video_path):
                return

        # 3. 启动新的后台视频线程。
        self._start_video_worker(video_path)

    def _start_video_worker(self, video_path):
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

    def _load_session_annotation(self, video_path):
        annotation_path = video_path + ".json"
        backup_path = video_path + ".autosave.json"
        should_load_backup = False

        if os.path.exists(backup_path):
            # 如果主文件不存在，或备份文件比主文件更新，则提示加载备份
            if not os.path.exists(annotation_path) or \
               os.path.getmtime(backup_path) > os.path.getmtime(annotation_path):
                reply = QMessageBox.question(self, "恢复文件",
                                             "检测到上次有未保存的工作，是否从自动备份中恢复？",
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if reply == QMessageBox.StandardButton.Yes:
                    should_load_backup = True

        if should_load_backup:
            print(f"从备份文件中恢复: {backup_path}")
            return self.load_annotations(backup_path)
        if os.path.exists(annotation_path):
            print(f"自动加载主标注文件: {annotation_path}")
            return self.load_annotations(annotation_path)
        return False

    def _initialize_new_session_annotations(self, video_path):
        print("未找到任何标注文件，将为新会话初始化。")

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            QMessageBox.critical(self, "视频错误", "无法读取视频元数据，请检查文件是否损坏。")
            print(f"读取视频元数据失败: {video_path}")
            cap.release()
            return False
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
        self._sync_court_overlay()

        dialog = MatchSetupDialog(self.annotations['match_info'], self)
        if dialog.exec():
            updated_info = dialog.get_data()
            self.annotations['match_info'].update(updated_info)

        self.update_match_info_ui()
        self._reset_event_tree_view()
        self.refresh_ui_for_current_frame()
        return True

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
        self._sync_court_overlay()
        
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
        self.current_rgb_frame = rgb_array.copy()
        self.current_frame_size = (width, height)
        
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

    def _get_match_players(self):
        match_info = self.annotations.get("match_info", {}) if self.annotations else {}
        player_a = match_info.get("player_a") or self.player_a_name
        player_b = match_info.get("player_b") or self.player_b_name
        return player_a, player_b

    def _is_valid_match_player(self, player_name):
        player_a, player_b = self._get_match_players()
        return player_name in {player_a, player_b}

    def _prompt_serving_player(self, title):
        player_a, player_b = self._get_match_players()
        if not player_a or not player_b or player_a == player_b:
            QMessageBox.warning(self, "发球方信息缺失", "请先在比赛信息中设置两名不同的球员。")
            return None
        dialog = ServePlayerDialog(player_a, player_b, self)
        dialog.setWindowTitle(title)
        if dialog.exec():
            return dialog.serving_player
        return None

    def _last_rally_winner_before_index(self, event_index):
        events = self.annotations.get("events", []) if self.annotations else []
        for event in reversed(events[:max(0, event_index)]):
            if event.get("type") != "RALLY_END":
                continue
            winner = event.get("details", {}).get("winner")
            if self._is_valid_match_player(winner):
                return winner
        return None

    def _last_rally_winner_before_frame(self, frame_num):
        events = self.annotations.get("events", []) if self.annotations else []
        for event in reversed(events):
            if event.get("type") != "RALLY_END":
                continue
            event_frame = event.get("frame")
            if event_frame is None or event_frame > frame_num:
                continue
            winner = event.get("details", {}).get("winner")
            if self._is_valid_match_player(winner):
                return winner
        return None

    def _is_first_rally_start_index(self, rally_start_index):
        events = self.annotations.get("events", []) if self.annotations else []
        for index, event in enumerate(events):
            if event.get("type") == "RALLY_START":
                return index == rally_start_index
        return False

    def _get_rally_start_index_for_event(self, event_obj):
        if not isinstance(event_obj, dict):
            return -1
        event_index = self._get_event_index(event_obj) if hasattr(self, "_get_event_index") else -1
        if event_index < 0:
            return -1
        if event_obj.get("type") == "RALLY_START":
            return event_index
        events = self.annotations.get("events", [])
        for index in range(event_index, -1, -1):
            if events[index].get("type") == "RALLY_START":
                return index
        return -1

    def _resolve_new_rally_serving_player(self):
        previous_winner = self._last_rally_winner_before_frame(self.current_frame_num)
        if previous_winner:
            return previous_winner, "previous_winner"
        serving_player = self._prompt_serving_player("第1局第1回合，请选择发球方")
        return serving_player, "manual" if serving_player else ""

    def ensure_serving_player_for_event(self, event_obj):
        if not self.annotations or event_obj.get("type") not in ["RALLY_START", "SHOT"]:
            return True
        rally_start_index = self._get_rally_start_index_for_event(event_obj)
        if rally_start_index < 0:
            return True

        events = self.annotations.get("events", [])
        rally_start_event = events[rally_start_index]
        details = rally_start_event.setdefault("details", {})
        current_server = details.get("serving_player")
        current_source = details.get("serving_player_source")

        previous_winner = self._last_rally_winner_before_index(rally_start_index)
        if previous_winner:
            serving_player = previous_winner
            source = "previous_winner"
        elif self._is_first_rally_start_index(rally_start_index):
            if self._is_valid_match_player(current_server) and current_source == "manual":
                return True
            serving_player = self._prompt_serving_player("第1局第1回合，请选择发球方")
            source = "manual"
        elif self._is_valid_match_player(current_server):
            return True
        else:
            QMessageBox.warning(self, "发球方信息缺失", "无法自动确定发球方，请手动选择。")
            serving_player = self._prompt_serving_player("选择发球方")
            source = "manual"

        if not serving_player:
            return False

        changed = current_server != serving_player or current_source != source
        if not changed:
            return True

        details["serving_player"] = serving_player
        details["serving_player_source"] = source
        updated_events = [rally_start_event]
        updated_events.extend(self.reevaluate_players_in_rally(rally_start_index))
        if hasattr(self, "_update_event_items"):
            self._update_event_items(updated_events)
        self.set_dirty()
        print(f"发球方已确认: {rally_start_event.get('event_id', '')} -> {serving_player}")
        return True

    def add_rally_start_event(self):
        """
        添加一个回合开始事件。
        整场第一个回合手动选择发球方，后续回合使用上一回合赢家。
        """
        if self.current_frame_num < 0: return

        serving_player, serving_player_source = self._resolve_new_rally_serving_player()

        if not serving_player:
            return # 如果用户取消选择，则不添加事件

        # 3. 创建并添加事件
        new_event = {
            "event_id": f"evt_{uuid.uuid4().hex[:6]}",
            "type": "RALLY_START",
            "frame": self.current_frame_num,
            "details": {
                "serving_player": serving_player,
                "serving_player_source": serving_player_source,
                "score_at_start": list(self.annotations['match_info']['current_set_score']),
                "hand": "待定",
                "major": "发球",
                "technique_hand": "待定",
                "minor": "待定",
                "serve_landing": "待定",
                "court_position": "待定",
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
                "hand": "适用",
                "major": "制胜分原因",
                "technique_hand": "",
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

        if not self.ensure_serving_player_for_event(owning_rally_start):
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
                "technique_hand": "待定",
                "minor": "待定",
                "shot_route": "待定",
                "court_position": "待定",
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
        if hasattr(self, "_update_court_side_status_label"):
            self._update_court_side_status_label()

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

    def export_current_annotations_to_xls(self):
        if not self.annotations:
            QMessageBox.information(self, "提示", "没有标注可以导出。")
            return

        video_path = self.annotations.get('video_info', {}).get('path', '')
        if video_path:
            default_path = default_output_path(Path(f"{video_path}.json"))
        else:
            default_path = Path.cwd() / "badminton-json-export.xls"

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出xls",
            str(default_path),
            "Excel-compatible XLS (*.xls);;CSV Files (*.csv);;All Files (*)",
        )
        if not file_path:
            return

        output_path = Path(file_path)
        if not output_path.suffix:
            output_path = output_path.with_suffix(".xls")

        try:
            row_count = write_xls(self.annotations, output_path)
            self.statusBar().showMessage(f"已导出 XLS: {output_path}", 4000)
            QMessageBox.information(self, "导出完成", f"已导出 {row_count} 行。\n{output_path}")
        except PermissionError:
            QMessageBox.warning(self, "导出失败", "无法写入文件：权限不足。\n请检查文件是否被其他程序占用。")
        except OSError as e:
            QMessageBox.warning(self, "导出失败", f"无法写入文件：\n{str(e)}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"导出 XLS 时发生错误：\n{str(e)}")
            print(f"导出 XLS 失败: {e}")

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
            self._sync_court_overlay()
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
                QApplication.processEvents()
                self.refresh_all_ui(scroll_to_bottom=False)
                QApplication.processEvents()
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
