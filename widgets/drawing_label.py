# file: widgets/drawing_label.py

from PyQt6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QListWidget, 
                             QDialogButtonBox, QWidget, QVBoxLayout, QLabel)
from PyQt6.QtGui import QPixmap, QImage, QPainter, QPen, QColor
from PyQt6.QtCore import Qt, QPoint, QRect, QSize, pyqtSignal, QEvent, QObject

TECHNIQUES = {
    "发球": ["发网前", "发平高", "发高远"],
    "后场上手": ["高远", "平高", "吊", "劈吊", "杀"],
    "网前三技术": ["搓放网", "勾球"],
    "中前场/防守反应": ["推", "挑", "推挑", "扑", "抽", "挡", "封网"],
    "制胜分原因": ["受迫性失误", "非受迫性失误", "制胜分"],
}

TECHNIQUE_HANDS = {
    "发球": ["正手", "反手"],
    "后场上手": ["正手", "反手", "头顶"],
    "网前三技术": ["正手", "反手"],
    "中前场/防守反应": ["正手", "反手"],
    "制胜分原因": [],
}

LEGACY_TECHNIQUE_ALIASES = {
    "正手发网前球": ("发球", "正手", "发网前"),
    "反手发网前球": ("发球", "反手", "发网前"),
    "正手发平高球": ("发球", "正手", "发平高"),
    "反手发平高球": ("发球", "反手", "发平高"),
    "正手发高远球": ("发球", "正手", "发高远"),
    "反手发高远球": ("发球", "反手", "发高远"),
    "正手击高球": ("后场上手", "正手", "高远"),
    "反手击高球": ("后场上手", "反手", "高远"),
    "头顶击高球": ("后场上手", "头顶", "高远"),
    "头顶手击高球": ("后场上手", "头顶", "高远"),
    "正手吊球": ("后场上手", "正手", "吊"),
    "反手吊球": ("后场上手", "反手", "吊"),
    "头顶吊球": ("后场上手", "头顶", "吊"),
    "正手杀球": ("后场上手", "正手", "杀"),
    "反手杀球": ("后场上手", "反手", "杀"),
    "头顶杀球": ("后场上手", "头顶", "杀"),
    "正手劈球": ("后场上手", "正手", "劈吊"),
    "反手劈球": ("后场上手", "反手", "劈吊"),
    "头顶劈球": ("后场上手", "头顶", "劈吊"),
    "正手搓球": ("网前三技术", "正手", "搓放网"),
    "反手搓球": ("网前三技术", "反手", "搓放网"),
    "正手放网前球": ("网前三技术", "正手", "搓放网"),
    "反手放网前球": ("网前三技术", "反手", "搓放网"),
    "正手勾球": ("网前三技术", "正手", "勾球"),
    "反手勾球": ("网前三技术", "反手", "勾球"),
    "正手推球": ("中前场/防守反应", "正手", "推"),
    "反手推球": ("中前场/防守反应", "反手", "推"),
    "正手挑球": ("中前场/防守反应", "正手", "挑"),
    "反手挑球": ("中前场/防守反应", "反手", "挑"),
    "正手扑球": ("中前场/防守反应", "正手", "扑"),
    "反手扑球": ("中前场/防守反应", "反手", "扑"),
    "正手抽球": ("中前场/防守反应", "正手", "抽"),
    "反手抽球": ("中前场/防守反应", "反手", "抽"),
    "正手封网": ("中前场/防守反应", "正手", "封网"),
    "反手封网": ("中前场/防守反应", "反手", "封网"),
    "头顶封网": ("中前场/防守反应", "正手", "封网"),
}

VIEWDESCP = ["视角正常", "视角异常", "击球缺帧"]

NOTSUIT = {
    "不适用": ["凑击球", "非常规动作"]
}

# 正反手是一个独立的维度
HAND_TYPES = ["适用", "不适用", "待定"]


class EnterKeyFilter(QObject):
    """事件过滤器类，用于捕获Enter键并接受对话框"""
    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
    
    def eventFilter(self, source, event):
        """过滤Enter键事件"""
        if event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if event.modifiers() == Qt.KeyboardModifier.NoModifier:
                    self.dialog.accept()
                    return True
        return False


class TechniqueSelectionDialog(QDialog):
    # ... (从 annotator_v0.6.3.py 完整复制 TechniqueSelectionDialog 类的所有代码) ...
    """
    一个用于选择技术动作的自定义对话框
    """
    def __init__(self, current_selection, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择技术动作")
        self.setMinimumWidth(650)

        layout = QHBoxLayout(self)

        # 1. 创建五个列表（状态/大类/手法方位/小类/视角）
        self.hand_list = QListWidget()
        self.major_list = QListWidget()
        self.technique_hand_list = QListWidget()
        self.minor_list = QListWidget()
        self.view_list = QListWidget()
        
        # 为每个列表控件安装事件过滤器，确保Enter键能正确触发对话框接受
        # 保存过滤器引用，确保它在对话框生命周期内有效
        self.enter_filter = EnterKeyFilter(self)
        self.hand_list.installEventFilter(self.enter_filter)
        self.major_list.installEventFilter(self.enter_filter)
        self.technique_hand_list.installEventFilter(self.enter_filter)
        self.minor_list.installEventFilter(self.enter_filter)
        self.view_list.installEventFilter(self.enter_filter)
        
        # 也为对话框本身安装事件过滤器，确保无论焦点在哪里都能捕获Enter键
        self.installEventFilter(self.enter_filter)
        
        def add_column(title, list_widget):
            column = QWidget()
            column_layout = QVBoxLayout(column)
            column_layout.setContentsMargins(0, 0, 0, 0)
            label = QLabel(title)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column_layout.addWidget(label)
            column_layout.addWidget(list_widget)
            layout.addWidget(column)

        add_column("状态", self.hand_list)
        add_column("大类", self.major_list)
        add_column("手法/方位", self.technique_hand_list)
        add_column("动作", self.minor_list)
        add_column("视角", self.view_list)
        
        # 2. 填充初始数据
        self.hand_list.addItems(HAND_TYPES)
        self.major_list.addItems(TECHNIQUES.keys())
        self.view_list.addItems(VIEWDESCP)
        
        # 3. 连接信号以实现级联更新（状态变化时切换数据源，大类变化时更新手法/小类）
        self.hand_list.currentItemChanged.connect(self.on_hand_changed)
        self.major_list.currentItemChanged.connect(self.update_technique_lists)
        
        # 4. 创建OK和Cancel按钮
        button_box_widget = QWidget()
        v_layout = QVBoxLayout(button_box_widget)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        # 设置OK按钮为默认按钮，使Enter键自动触发
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button:
            ok_button.setDefault(True)
            ok_button.setAutoDefault(True)
        v_layout.addStretch()
        v_layout.addWidget(buttons)
        layout.addWidget(button_box_widget)
        
        # 5. 设置初始选中项
        self.set_current_selection(current_selection)
        # 初始焦点在第一列
        self.hand_list.setFocus()

    def keyPressEvent(self, event):
        """支持 左右切换列，上下选择项，回车确认"""
        key = event.key()
        modifiers = event.modifiers()

        # 当前焦点在哪一列
        focus_widget = self.focusWidget()
        columns = [self.hand_list, self.major_list, self.technique_hand_list, self.minor_list, self.view_list]
        try:
            col_index = columns.index(focus_widget) if focus_widget in columns else 0
        except ValueError:
            col_index = 0

        # 左右键切换列
        if key == Qt.Key.Key_Right:
            if col_index < len(columns) - 1:
                columns[col_index + 1].setFocus()
            return
        if key == Qt.Key.Key_Left:
            if col_index > 0:
                columns[col_index - 1].setFocus()
            return

        # 上下键在当前列移动
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            listw = columns[col_index]
            row = listw.currentRow()
            if row < 0 and listw.count() > 0:
                listw.setCurrentRow(0)
            else:
                if key == Qt.Key.Key_Up and row > 0:
                    listw.setCurrentRow(row - 1)
                elif key == Qt.Key.Key_Down and row < listw.count() - 1:
                    listw.setCurrentRow(row + 1)
            return

        # 回车确认
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.accept()
            return

        # 其他交给父类
        super().keyPressEvent(event)

    def on_hand_changed(self, current_item):
        """当适用/不适用/待定切换时，切换数据源并重置左右列表"""
        hand_value = current_item.text() if current_item else HAND_TYPES[0]
        self._refresh_major_and_minor(hand_value)

    def _get_data_source(self, hand_value):
        """根据 hand 选择返回对应的数据源"""
        return NOTSUIT if hand_value == "不适用" else TECHNIQUES

    def _split_legacy_technique(self, major, minor):
        """兼容旧数据中“正手杀”这类合并在小类里的写法。"""
        if not minor:
            return None

        alias = LEGACY_TECHNIQUE_ALIASES.get(minor)
        if alias:
            return alias

        if major in TECHNIQUES:
            for technique_hand in TECHNIQUE_HANDS.get(major, []):
                if minor.startswith(technique_hand):
                    action = minor[len(technique_hand):]
                    if action in TECHNIQUES.get(major, []):
                        return major, technique_hand, action

        for candidate_major, technique_hands in TECHNIQUE_HANDS.items():
            for technique_hand in technique_hands:
                if minor.startswith(technique_hand):
                    action = minor[len(technique_hand):]
                    if action in TECHNIQUES.get(candidate_major, []):
                        return candidate_major, technique_hand, action
        return None

    def _normalize_technique_selection(self, selection, data_source):
        current_major = selection.get('major')
        current_minor = selection.get('minor')
        current_technique_hand = selection.get('technique_hand')

        legacy = self._split_legacy_technique(current_major, current_minor)
        if legacy:
            legacy_major, legacy_hand, legacy_minor = legacy
            if legacy_major in data_source:
                current_major = legacy_major
                current_technique_hand = legacy_hand
                current_minor = legacy_minor

        if current_major not in data_source:
            current_major = None

        available_hands = TECHNIQUE_HANDS.get(current_major, [])
        if current_technique_hand not in available_hands:
            current_technique_hand = available_hands[0] if available_hands else None

        if current_minor not in data_source.get(current_major, []):
            current_minor = None

        return current_major, current_technique_hand, current_minor

    def _update_technique_lists_with_data(
        self,
        current_item,
        data_source,
        selected_minor=None,
        selected_technique_hand=None,
    ):
        """使用指定数据源更新手法/方位和小类列表，并可选恢复之前的选中项"""
        self.technique_hand_list.clear()
        self.minor_list.clear()
        if not current_item:
            return
        major_tech = current_item.text()
        technique_hands = TECHNIQUE_HANDS.get(major_tech, [])
        self.technique_hand_list.addItems(technique_hands)
        if selected_technique_hand:
            for i in range(self.technique_hand_list.count()):
                if self.technique_hand_list.item(i).text() == selected_technique_hand:
                    self.technique_hand_list.setCurrentRow(i)
                    break
        elif technique_hands:
            self.technique_hand_list.setCurrentRow(0)

        minor_techs = data_source.get(major_tech, [])
        self.minor_list.addItems(minor_techs)
        if selected_minor:
            for i in range(self.minor_list.count()):
                if self.minor_list.item(i).text() == selected_minor:
                    self.minor_list.setCurrentRow(i)
                    break
        elif minor_techs:
            self.minor_list.setCurrentRow(0)

    def update_technique_lists(self, current_item):
        """当大类变化时，更新手法/方位和小类列表（随状态切换数据源）"""
        hand_value = self.hand_list.currentItem().text() if self.hand_list.currentItem() else HAND_TYPES[0]
        data_source = self._get_data_source(hand_value)
        self._update_technique_lists_with_data(current_item, data_source)

    def update_minor_list(self, current_item):
        self.update_technique_lists(current_item)
            
    def set_current_selection(self, selection):
        """根据传入的字典，设置列表的默认选中项"""
        if not selection:
            selection = {}
        
        # 设置hand_list：优先使用传入的hand值，否则默认"适用"
        hand_value = selection.get('hand') if selection.get('hand') in HAND_TYPES else HAND_TYPES[0]
        if self.hand_list.count() > 0:
            self.hand_list.setCurrentRow(HAND_TYPES.index(hand_value))
        # 按状态刷新列表，并恢复大类/手法/小类的选中状态
        self._refresh_major_and_minor(hand_value, selection)

    def _refresh_major_and_minor(self, hand_value, selection=None):
        """根据hand选择刷新大类/小类列表，并在需要时恢复选中项"""
        selection = selection or {}
        data_source = self._get_data_source(hand_value)
        current_major, current_technique_hand, current_minor = self._normalize_technique_selection(
            selection,
            data_source,
        )
        current_view = selection.get('view_desc', VIEWDESCP[0])

        # 暂停信号，避免重复触发
        self.major_list.blockSignals(True)
        self.technique_hand_list.blockSignals(True)
        self.minor_list.blockSignals(True)
        self.view_list.blockSignals(True)

        self.major_list.clear()
        self.technique_hand_list.clear()
        self.minor_list.clear()
        self.view_list.clear()

        majors = list(data_source.keys())
        self.major_list.addItems(majors)
        self.view_list.addItems(VIEWDESCP)

        if majors:
            target_major_row = 0
            if current_major in majors:
                target_major_row = majors.index(current_major)
            self.major_list.setCurrentRow(target_major_row)
            current_item = self.major_list.item(target_major_row)
            self._update_technique_lists_with_data(
                current_item,
                data_source,
                current_minor,
                current_technique_hand,
            )

        self.major_list.blockSignals(False)
        self.technique_hand_list.blockSignals(False)
        self.minor_list.blockSignals(False)
        self.view_list.blockSignals(False)

        # 视角列表恢复选中
        if self.view_list.count() > 0:
            target_view_row = VIEWDESCP.index(current_view) if current_view in VIEWDESCP else 0
            self.view_list.setCurrentRow(target_view_row)

    def get_selection(self):
        """返回用户最终选择的结果"""
        hand = self.hand_list.currentItem().text() if self.hand_list.currentItem() else None
        major = self.major_list.currentItem().text() if self.major_list.currentItem() else None
        technique_hand = self.technique_hand_list.currentItem().text() if self.technique_hand_list.currentItem() else None
        minor = self.minor_list.currentItem().text() if self.minor_list.currentItem() else None
        view_desc = self.view_list.currentItem().text() if self.view_list.currentItem() else VIEWDESCP[0]
        data_source = self._get_data_source(hand) if hand else TECHNIQUES
        
        # 如果没有选择hand，返回None
        if not hand:
            return None
        
        # 不适用：使用NOTSUIT的数据源，要求至少选择原因（minor）
        if hand == "不适用":
            # major列表只有“不适用”一项，但仍使用当前选中值以保持一致性
            selected_major = major if major in data_source else "不适用"
            if minor:
                return {
                    "hand": hand,
                    "major": selected_major,
                    "technique_hand": "",
                    "minor": minor,
                    "view_desc": view_desc,
                }
            # 如果没有可选项（理论上不会发生），兜底返回hand
            if self.minor_list.count() == 0:
                return {
                    "hand": hand,
                    "major": selected_major,
                    "technique_hand": "",
                    "minor": selected_major,
                    "view_desc": view_desc,
                }
            return None

        # 适用：必须选择具体的大类和小类
        if hand == "适用":
            if not all([major, minor]):
                return None  # 如果有未选择项，则返回None
            technique_hands = TECHNIQUE_HANDS.get(major, [])
            if technique_hands and technique_hand not in technique_hands:
                return None
            return {
                "hand": hand,
                "major": major,
                "technique_hand": technique_hand if technique_hands else "",
                "minor": minor,
                "view_desc": view_desc
            }

        # 待定：允许选择技术动作，未选则回退为“待定”
        if hand == "待定":
            if major and minor:
                technique_hands = TECHNIQUE_HANDS.get(major, [])
                return {
                    "hand": hand,
                    "major": major,
                    "technique_hand": technique_hand if technique_hand in technique_hands else "",
                    "minor": minor,
                    "view_desc": view_desc,
                }
            return {
                "hand": hand,
                "major": "待定",
                "technique_hand": "待定",
                "minor": "待定",
                "view_desc": view_desc,
            }
        
        # 兜底：其他情况返回None
        return None

class DrawingLabel(QLabel):
    # --- 信号定义 (保持不变) ---
    new_rect_drawn = pyqtSignal(QRect)
    new_point_drawn = pyqtSignal(QPoint)
    object_selected = pyqtSignal(str)
    object_moved = pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.draw_mode = "select"
        self.action_state = "idle"
        self.objects = []
        self.selected_object_id = None
        self.action_start_pos_ui = None
        self.selected_obj_original_geom_video = None
        self.preview_rect_ui = None
        self.resize_handle_rect_ui = QRect()
        self.resize_handle_size = 10
        self.original_video_width = 1
        self.original_video_height = 1
        self.setMouseTracking(True)

    def set_draw_mode(self, mode):
        self.draw_mode = mode
        if mode == "box": self.setCursor(Qt.CursorShape.CrossCursor)
        elif mode == "point": self.setCursor(Qt.CursorShape.PointingHandCursor)
        else: self.setCursor(Qt.CursorShape.ArrowCursor)

    def load_frame_annotations(self, objects):
        self.objects = objects
        self.update()

    def set_selected_object(self, object_id):
        if self.selected_object_id != object_id:
            self.selected_object_id = object_id
            self.update()

    def mousePressEvent(self, event):
        """完全遵循 v0.6.3 的逻辑，但优化了点选优先级"""
        if event.button() != Qt.MouseButton.LeftButton:
            return
        
        self.action_start_pos_ui = event.pos()

        if self.draw_mode == "select":
            # 1. 检查是否点中缩放手柄 (最高优先级)
            if self.selected_object_id and self.resize_handle_rect_ui.contains(self.action_start_pos_ui):
                self.action_state = "resizing"
                for obj in self.objects:
                    if obj['id'] == self.selected_object_id:
                        self.selected_obj_original_geom_video = QRect(*obj['bbox'])
                        break
                return

            # <<< ================== 核心优化：调整点选测试逻辑 ================== >>>
            
            # 2. 进行点选测试 (Hit Test)，优先检查点，再检查框
            clicked_point_video = self.ui_coord_to_video_coord_point(self.action_start_pos_ui)
            found_id = None

            # 2a. 首先，专门遍历一次所有“点”对象
            for obj in self.objects:
                if obj['type'] == 'point':
                    p_obj = QPoint(*obj['coords'])
                    if (p_obj - clicked_point_video).manhattanLength() < 15: # 增加容差，更容易点中
                        found_id = obj['id']
                        break # 只要点中一个点，就立刻停止，不再检查任何其他对象
            
            # 2b. 如果没有点中任何“点”，才开始检查“框”对象
            if not found_id:
                for obj in reversed(self.objects): # 从上层往下找
                    if obj['type'] == 'box':
                        r_obj = QRect(*obj['bbox'])
                        if r_obj.contains(clicked_point_video):
                            found_id = obj['id']
                            break
            
            # <<< ================== 优化结束 ================== >>>
            
            self.object_selected.emit(found_id if found_id else "")
            
            # 3. 如果选中了对象，则进入拖拽状态
            if found_id:
                self.action_state = "dragging"
                for obj in self.objects:
                    if obj['id'] == found_id:
                        if obj['type'] == 'box':
                            self.selected_obj_original_geom_video = QRect(*obj['bbox'])
                        elif obj['type'] == 'point':
                            self.selected_obj_original_geom_video = QPoint(*obj['coords'])
                        break

        elif self.draw_mode == "box":
            self.action_state = "drawing"
            self.preview_rect_ui = QRect(self.action_start_pos_ui, self.action_start_pos_ui)
            self.update()

        elif self.draw_mode == "point":
            self.new_point_drawn.emit(self.action_start_pos_ui)

    def mouseMoveEvent(self, event):
        """结合了自我刷新和绘制预览的逻辑"""
        current_pos_ui = event.pos()
        
        # 如果鼠标没按下，不执行任何操作
        if not self.action_start_pos_ui: return

        # --- 拖动/缩放的自我刷新逻辑 ---
        if self.action_state == "resizing" and self.selected_obj_original_geom_video:
            original_geom = self.selected_obj_original_geom_video
            target_br_video = self.ui_coord_to_video_coord_point(current_pos_ui)
            new_width = target_br_video.x() - original_geom.x()
            new_height = target_br_video.y() - original_geom.y()
            
            if new_width > 5 and new_height > 5:
                new_bbox = [original_geom.x(), original_geom.y(), new_width, new_height]
                for obj in self.objects:
                    if obj['id'] == self.selected_object_id:
                        obj['bbox'] = new_bbox
                        break
                self.update()
                self.object_moved.emit(self.selected_object_id, new_bbox)

        elif self.action_state == "dragging" and self.selected_obj_original_geom_video:
            delta_ui = current_pos_ui - self.action_start_pos_ui
            x_scale = self.original_video_width / self.width()
            y_scale = self.original_video_height / self.height()
            delta_video = QPoint(int(delta_ui.x() * x_scale), int(delta_ui.y() * y_scale))
            
            original_geom = self.selected_obj_original_geom_video
            if isinstance(original_geom, QRect):
                new_pos = original_geom.topLeft() + delta_video
                new_bbox = [new_pos.x(), new_pos.y(), original_geom.width(), original_geom.height()]
                for obj in self.objects:
                    if obj['id'] == self.selected_object_id:
                        obj['bbox'] = new_bbox
                        break
                self.update()
                self.object_moved.emit(self.selected_object_id, new_bbox)
            elif isinstance(original_geom, QPoint):
                new_pos = original_geom + delta_video
                new_coords = [new_pos.x(), new_pos.y()]
                for obj in self.objects:
                    if obj['id'] == self.selected_object_id:
                        obj['coords'] = new_coords
                        break
                self.update()
                self.object_moved.emit(self.selected_object_id, new_coords)
        
        # --- 绘制预览的逻辑 (现在可以被正确执行了) ---
        elif self.action_state == "drawing":
            self.preview_rect_ui.setBottomRight(current_pos_ui)
            self.update()

    def mouseReleaseEvent(self, event):
        """完全遵循 v0.6.3 的逻辑来完成动作和重置"""
        if event.button() == Qt.MouseButton.LeftButton:
            if self.action_state == "drawing":
                if self.preview_rect_ui:
                    final_rect_ui = self.preview_rect_ui.normalized()
                    if final_rect_ui.width() > 5 and final_rect_ui.height() > 5:
                        self.new_rect_drawn.emit(final_rect_ui)
            
            # 统一重置所有状态
            self.action_state = "idle"
            self.action_start_pos_ui = None
            self.selected_obj_original_geom_video = None
            self.preview_rect_ui = None
            self.update()
    
    # paintEvent 和坐标转换函数，请使用我们上一轮修复了“变白”问题的版本
    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.pixmap(): return
        
        painter = QPainter(self)
        
        for obj in self.objects:
            is_selected = (obj['id'] == self.selected_object_id)
            if obj['type'] == 'box':
                bbox = obj['bbox']
                rect_video = QRect(*bbox) # 使用解包更安全
                rect_ui = self.video_coord_to_ui_coord_rect(rect_video)
                
                pen = QPen(QColor(255, 0, 0), 3) if is_selected else QPen(QColor(0, 255, 0), 2)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(rect_ui)
                
                if is_selected:
                    self.resize_handle_rect_ui = QRect(
                        rect_ui.bottomRight() - QPoint(self.resize_handle_size, self.resize_handle_size),
                        QSize(self.resize_handle_size, self.resize_handle_size))
                    painter.setBrush(Qt.GlobalColor.white)
                    painter.drawRect(self.resize_handle_rect_ui)
            elif obj['type'] == 'point':
                coords = obj['coords']
                point_video = QPoint(*coords)
                point_ui = self.video_coord_to_ui_coord_point(point_video)
                pen = QPen(QColor(255, 0, 0), 4) if is_selected else QPen(QColor(255, 255, 0), 2)
                painter.setPen(pen)
                painter.drawLine(point_ui.x() - 8, point_ui.y(), point_ui.x() + 8, point_ui.y())
                painter.drawLine(point_ui.x(), point_ui.y() - 8, point_ui.x(), point_ui.y() + 8)

        if self.action_state == "drawing" and self.preview_rect_ui:
            preview_pen = QPen(QColor(255, 0, 0), 1, Qt.PenStyle.DashLine)
            painter.setPen(preview_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.preview_rect_ui)
            
    # --- 坐标转换函数 (保持不变) ---
    def set_video_dimensions(self, w, h): 
        self.original_video_width, self.original_video_height = w, h
    
    def ui_coord_to_video_coord_rect(self, ui_rect):
        """将UI坐标矩形转换为视频坐标矩形，带边界检查"""
        if self.width() == 0 or self.height() == 0 or self.original_video_width == 0 or self.original_video_height == 0:
            return QRect(0, 0, 0, 0)
        x_scale = self.original_video_width / self.width()
        y_scale = self.original_video_height / self.height()
        return QRect(int(ui_rect.x() * x_scale), int(ui_rect.y() * y_scale), 
                     int(ui_rect.width() * x_scale), int(ui_rect.height() * y_scale))
    
    def video_coord_to_ui_coord_rect(self, video_rect):
        """将视频坐标矩形转换为UI坐标矩形，带边界检查"""
        if self.original_video_width == 0 or self.original_video_height == 0:
            return QRect(0, 0, 0, 0)
        x_scale = self.width() / self.original_video_width if self.original_video_width > 0 else 1.0
        y_scale = self.height() / self.original_video_height if self.original_video_height > 0 else 1.0
        return QRect(int(video_rect.x() * x_scale), int(video_rect.y() * y_scale), 
                     int(video_rect.width() * x_scale), int(video_rect.height() * y_scale))
    
    def ui_coord_to_video_coord_point(self, ui_point):
        """将UI坐标点转换为视频坐标点，带边界检查"""
        if self.width() == 0 or self.height() == 0 or self.original_video_width == 0 or self.original_video_height == 0:
            return QPoint(0, 0)
        x_scale = self.original_video_width / self.width()
        y_scale = self.original_video_height / self.height()
        return QPoint(int(ui_point.x() * x_scale), int(ui_point.y() * y_scale))
    
    def video_coord_to_ui_coord_point(self, video_point):
        """将视频坐标点转换为UI坐标点，带边界检查"""
        if self.original_video_width == 0 or self.original_video_height == 0:
            return QPoint(0, 0)
        x_scale = self.width() / self.original_video_width if self.original_video_width > 0 else 1.0
        y_scale = self.height() / self.original_video_height if self.original_video_height > 0 else 1.0
        return QPoint(int(video_point.x() * x_scale), int(video_point.y() * y_scale))
    
class DrawingLabel1(QLabel):
    # --- 信号定义 (保持不变) ---
    new_rect_drawn = pyqtSignal(QRect)
    new_point_drawn = pyqtSignal(QPoint)
    object_selected = pyqtSignal(str)
    object_moved = pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        # --- 状态变量 ---
        self.draw_mode = "select"
        self.action_state = "idle"  # 当前动作: idle, drawing, dragging, resizing
        
        # --- 数据 ---
        self.objects = []
        self.selected_object_id = None
        
        # --- 拖拽/缩放/绘制所需变量 ---
        self.action_start_pos_ui = None
        self.selected_obj_original_geom_video = None
        self.preview_rect_ui = None
        self.resize_handle_rect_ui = QRect()

        # --- 辅助变量 ---
        self.resize_handle_size = 10
        self.original_video_width = 1
        self.original_video_height = 1
        self.setMouseTracking(True)

    def set_draw_mode(self, mode):
        self.draw_mode = mode
        if mode == "box": self.setCursor(Qt.CursorShape.CrossCursor)
        elif mode == "point": self.setCursor(Qt.CursorShape.PointingHandCursor)
        else: self.setCursor(Qt.CursorShape.ArrowCursor)

    def load_frame_annotations(self, objects):
        self.objects = objects
        self.update()

    def set_selected_object(self, object_id):
        if self.selected_object_id != object_id:
            self.selected_object_id = object_id
            self.update()

    # <<< ================== 以下是 v0.6.3 逻辑的精确复刻 ================== >>>
    
    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        
        self.action_start_pos_ui = event.pos()

        if self.draw_mode == "select":
            # 1. 检查是否点中缩放手柄 (最高优先级)
            if self.selected_object_id and self.resize_handle_rect_ui.contains(self.action_start_pos_ui):
                self.action_state = "resizing"
                # 记录原始几何信息是必须的
                for obj in self.objects:
                    if obj['id'] == self.selected_object_id:
                        bbox = obj['bbox']
                        self.selected_obj_original_geom_video = QRect(bbox[0], bbox[1], bbox[2], bbox[3])
                        break
                return

            # 2. 进行点选测试 (Hit Test) - 统一在视频坐标系下进行
            clicked_point_video = self.ui_coord_to_video_coord_point(self.action_start_pos_ui)
            found_id = None
            for obj in reversed(self.objects): # 从上层往下找
                if obj['type'] == 'box':
                    r_obj = QRect(obj['bbox'][0], obj['bbox'][1], obj['bbox'][2], obj['bbox'][3])
                    if r_obj.contains(clicked_point_video):
                        found_id = obj['id']
                        break
                elif obj['type'] == 'point':
                    p_obj = QPoint(obj['coords'][0], obj['coords'][1])
                    if (p_obj - clicked_point_video).manhattanLength() < 10: # 容差
                        found_id = obj['id']
                        break
            
            self.object_selected.emit(found_id if found_id else "")
            
            # 3. 如果选中了对象，则进入拖拽状态
            if found_id:
                self.action_state = "dragging"
                for obj in self.objects:
                    if obj['id'] == found_id:
                        if obj['type'] == 'box':
                            bbox = obj['bbox']
                            self.selected_obj_original_geom_video = QRect(bbox[0], bbox[1], bbox[2], bbox[3])
                        elif obj['type'] == 'point':
                            coords = obj['coords']
                            self.selected_obj_original_geom_video = QPoint(coords[0], coords[1])
                        break

        elif self.draw_mode == "box":
            self.action_state = "drawing"
            self.preview_rect_ui = QRect(self.action_start_pos_ui, self.action_start_pos_ui)
            self.update()

        elif self.draw_mode == "point":
            self.new_point_drawn.emit(self.action_start_pos_ui)

    def mouseMoveEvent(self, event):
        current_pos_ui = event.pos()
        
        # 仅在拖拽/缩放时处理
        if self.action_state not in ["dragging", "resizing"]:
            # (可选：可以把之前的动态光标代码放在这里)
            return
        
        # 确保我们有有效的起始数据
        if not self.action_start_pos_ui or not self.selected_obj_original_geom_video:
            return

        if self.action_state == "resizing":
            original_geom = self.selected_obj_original_geom_video
            target_br_video = self.ui_coord_to_video_coord_point(current_pos_ui)
            
            new_width = target_br_video.x() - original_geom.x()
            new_height = target_br_video.y() - original_geom.y()
            
            if new_width > 5 and new_height > 5:
                new_bbox = [original_geom.x(), original_geom.y(), new_width, new_height]
                
                # 更新内部对象用于实时预览，并发出信号
                for obj in self.objects:
                    if obj['id'] == self.selected_object_id:
                        obj['bbox'] = new_bbox
                        break
                self.update()
                self.object_moved.emit(self.selected_object_id, new_bbox)

        elif self.action_state == "dragging":
            delta_ui = current_pos_ui - self.action_start_pos_ui
            x_scale = self.original_video_width / self.width()
            y_scale = self.original_video_height / self.height()
            delta_video = QPoint(int(delta_ui.x() * x_scale), int(delta_ui.y() * y_scale))
            
            original_geom = self.selected_obj_original_geom_video
            if isinstance(original_geom, QRect):
                new_pos = original_geom.topLeft() + delta_video
                new_bbox = [new_pos.x(), new_pos.y(), original_geom.width(), original_geom.height()]
                
                for obj in self.objects:
                    if obj['id'] == self.selected_object_id:
                        obj['bbox'] = new_bbox
                        break
                self.update()
                self.object_moved.emit(self.selected_object_id, new_bbox)

            elif isinstance(original_geom, QPoint):
                new_pos = original_geom + delta_video
                new_coords = [new_pos.x(), new_pos.y()]

                for obj in self.objects:
                    if obj['id'] == self.selected_object_id:
                        obj['coords'] = new_coords
                        break
                self.update()
                self.object_moved.emit(self.selected_object_id, new_coords)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.action_state == "drawing":
                # 检查 self.preview_rect_ui 是否存在
                if self.preview_rect_ui:
                    final_rect_ui = self.preview_rect_ui.normalized()
                    if final_rect_ui.width() > 5 and final_rect_ui.height() > 5:
                        self.new_rect_drawn.emit(final_rect_ui)
            
            # 统一重置所有状态
            self.action_state = "idle"
            self.action_start_pos_ui = None
            self.selected_obj_original_geom_video = None
            self.preview_rect_ui = None
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.pixmap(): return
        
        painter = QPainter(self)
        
        # 绘制所有已存在的对象
        for obj in self.objects:
            is_selected = (obj['id'] == self.selected_object_id)
            if obj['type'] == 'box':
                bbox = obj['bbox']
                rect_video = QRect(bbox[0], bbox[1], bbox[2], bbox[3])
                rect_ui = self.video_coord_to_ui_coord_rect(rect_video)
                
                pen = QPen(QColor(255, 0, 0), 3) if is_selected else QPen(QColor(0, 255, 0), 2)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush) # 确保不填充
                painter.drawRect(rect_ui)
                
                if is_selected:
                    # 这个值的计算和赋值只在这里发生，是正确的
                    self.resize_handle_rect_ui = QRect(
                        rect_ui.bottomRight() - QPoint(self.resize_handle_size, self.resize_handle_size),
                        QSize(self.resize_handle_size, self.resize_handle_size))
                    painter.setBrush(Qt.GlobalColor.white) # 临时使用画刷
                    painter.drawRect(self.resize_handle_rect_ui)
            elif obj['type'] == 'point':
                coords = obj['coords']
                point_video = QPoint(coords[0], coords[1])
                point_ui = self.video_coord_to_ui_coord_point(point_video)
                pen = QPen(QColor(255, 0, 0), 4) if is_selected else QPen(QColor(255, 255, 0), 2)
                painter.setPen(pen)
                painter.drawLine(point_ui.x() - 8, point_ui.y(), point_ui.x() + 8, point_ui.y())
                painter.drawLine(point_ui.x(), point_ui.y() - 8, point_ui.x(), point_ui.y() + 8)

        # 绘制新框的预览
        if self.action_state == "drawing" and self.preview_rect_ui:
            preview_pen = QPen(QColor(255, 0, 0), 1, Qt.PenStyle.DashLine)
            painter.setPen(preview_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush) # 确保预览框不填充
            painter.drawRect(self.preview_rect_ui)
    
    # --- 坐标转换函数 (保持不变) ---
    def set_video_dimensions(self, w, h): self.original_video_width, self.original_video_height = w, h
    def ui_coord_to_video_coord_rect(self, ui_rect):
        if self.width() == 0 or self.height() == 0 or self.original_video_width == 0 or self.original_video_height == 0:
            return QRect(0, 0, 0, 0)
        x_scale = self.original_video_width / self.width()
        y_scale = self.original_video_height / self.height()
        return QRect(int(ui_rect.x() * x_scale), int(ui_rect.y() * y_scale), int(ui_rect.width() * x_scale), int(ui_rect.height() * y_scale))
    def video_coord_to_ui_coord_rect(self, video_rect):
        if self.original_video_width == 0 or self.original_video_height == 0:
            return QRect(0, 0, 0, 0)
        x_scale = self.width() / self.original_video_width
        y_scale = self.height() / self.original_video_height
        return QRect(int(video_rect.x() * x_scale), int(video_rect.y() * y_scale), int(video_rect.width() * x_scale), int(video_rect.height() * y_scale))
    def ui_coord_to_video_coord_point(self, ui_point):
        if self.width() == 0 or self.height() == 0 or self.original_video_width == 0 or self.original_video_height == 0:
            return QPoint(0, 0)
        x_scale = self.original_video_width / self.width()
        y_scale = self.original_video_height / self.height()
        return QPoint(int(ui_point.x() * x_scale), int(ui_point.y() * y_scale))
    def video_coord_to_ui_coord_point(self, video_point):
        if self.original_video_width == 0 or self.original_video_height == 0:
            return QPoint(0, 0)
        x_scale = self.width() / self.original_video_width
        y_scale = self.height() / self.original_video_height
        return QPoint(int(video_point.x() * x_scale), int(video_point.y() * y_scale))
