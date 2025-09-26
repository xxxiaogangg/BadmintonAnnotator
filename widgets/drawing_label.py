# file: widgets/drawing_label.py

from PyQt6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QListWidget, 
                             QDialogButtonBox, QWidget, QVBoxLayout, QLabel)
from PyQt6.QtGui import QPixmap, QImage, QPainter, QPen, QColor
from PyQt6.QtCore import Qt, QPoint, QRect, QSize, pyqtSignal

TECHNIQUES = {
    "发球": ["正手发网前球", "反手发网前球", "正手发平高球", "反手发平高球", "正手发高远球", "反手发高远球"],
    "搓放球": ["正手搓球", "反手搓球", "正手放网前球", "反手放网前球"],
    "推扑球": ["正手推球", "反手推球", "正手扑球", "反手扑球"],
    "吊球": ["正手吊球", "反手吊球", "头顶吊球"],
    "挑球": ["正手挑球", "反手挑球"],
    "搓放网": ["搓球", "放网前球"],
    "勾球": ["正手勾球", "反手勾球"],
    "抽球": ["正手抽球", "反手抽球"],
    "高球": ["正手击高球", "头顶手击高球", "反手击高球"],
    "杀球": ["正手杀球", "反手杀球", "头顶杀球"],
    "劈球": ["正手劈球", "反手劈球", "头顶劈球"],
    "封网": ["正手封网", "反手封网", "头顶封网"],
    "得分方式/失误原因": [
        "进攻得分", "对手进攻失误", "对手发球失误", "对手非受迫性失误", 
        "发球直接得分", "防守得分", "多拍相持得分", "其他"
    ],
}

# 正反手是一个独立的维度
HAND_TYPES = ["不适用"]

class TechniqueSelectionDialog(QDialog):
    # ... (从 annotator_v0.6.3.py 完整复制 TechniqueSelectionDialog 类的所有代码) ...
    """
    一个用于选择技术动作的自定义对话框
    """
    def __init__(self, current_selection, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择技术动作")
        self.setMinimumWidth(500)

        layout = QHBoxLayout(self)

        # 1. 创建三个列表
        self.hand_list = QListWidget()
        self.major_list = QListWidget()
        self.minor_list = QListWidget()
        
        layout.addWidget(self.hand_list)
        layout.addWidget(self.major_list)
        layout.addWidget(self.minor_list)
        
        # 2. 填充初始数据
        self.hand_list.addItems(HAND_TYPES)
        self.major_list.addItems(TECHNIQUES.keys())
        
        # 3. 连接信号以实现级联更新
        self.major_list.currentItemChanged.connect(self.update_minor_list)
        
        # 4. 创建OK和Cancel按钮
        button_box_widget = QWidget()
        v_layout = QVBoxLayout(button_box_widget)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v_layout.addStretch()
        v_layout.addWidget(buttons)
        layout.addWidget(button_box_widget)
        
        # 5. 设置初始选中项
        self.set_current_selection(current_selection)

    def update_minor_list(self, current_item):
        """当大类变化时，更新小类列表"""
        self.minor_list.clear()
        if current_item:
            major_tech = current_item.text()
            minor_techs = TECHNIQUES.get(major_tech, [])
            self.minor_list.addItems(minor_techs)
            
    def set_current_selection(self, selection):
        """根据传入的字典，设置列表的默认选中项"""
        # ... (通过循环和比较文本来找到并设置 QListWidget 的 currentRow)
        for i in range(self.hand_list.count()):
            if self.hand_list.item(i).text() == selection.get('hand'):
                self.hand_list.setCurrentRow(i)
                break
        # ... (同样逻辑用于 major_list 和 minor_list)

    def get_selection(self):
        """返回用户最终选择的结果"""
        hand = self.hand_list.currentItem().text() if self.hand_list.currentItem() else None
        major = self.major_list.currentItem().text() if self.major_list.currentItem() else None
        minor = self.minor_list.currentItem().text() if self.minor_list.currentItem() else None
        
        if not all([hand, major, minor]):
            return None # 如果有未选择项，则返回None
        
        return {
            "hand": hand,
            "major": major,
            "minor": minor
        }

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
    def set_video_dimensions(self, w, h): self.original_video_width, self.original_video_height = w, h
    def ui_coord_to_video_coord_rect(self, ui_rect):
        x_scale = self.original_video_width / self.width(); y_scale = self.original_video_height / self.height()
        return QRect(int(ui_rect.x() * x_scale), int(ui_rect.y() * y_scale), int(ui_rect.width() * x_scale), int(ui_rect.height() * y_scale))
    def video_coord_to_ui_coord_rect(self, video_rect):
        x_scale = self.width() / self.original_video_width; y_scale = self.height() / self.original_video_height
        return QRect(int(video_rect.x() * x_scale), int(video_rect.y() * y_scale), int(video_rect.width() * x_scale), int(video_rect.height() * y_scale))
    def ui_coord_to_video_coord_point(self, ui_point):
        x_scale = self.original_video_width / self.width(); y_scale = self.original_video_height / self.height()
        return QPoint(int(ui_point.x() * x_scale), int(ui_point.y() * y_scale))
    def video_coord_to_ui_coord_point(self, video_point):
        x_scale = self.width() / self.original_video_width; y_scale = self.height() / self.original_video_height
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
        x_scale = self.original_video_width / self.width(); y_scale = self.original_video_height / self.height()
        return QRect(int(ui_rect.x() * x_scale), int(ui_rect.y() * y_scale), int(ui_rect.width() * x_scale), int(ui_rect.height() * y_scale))
    def video_coord_to_ui_coord_rect(self, video_rect):
        x_scale = self.width() / self.original_video_width; y_scale = self.height() / self.original_video_height
        return QRect(int(video_rect.x() * x_scale), int(video_rect.y() * y_scale), int(video_rect.width() * x_scale), int(video_rect.height() * y_scale))
    def ui_coord_to_video_coord_point(self, ui_point):
        x_scale = self.original_video_width / self.width(); y_scale = self.original_video_height / self.height()
        return QPoint(int(ui_point.x() * x_scale), int(ui_point.y() * y_scale))
    def video_coord_to_ui_coord_point(self, video_point):
        x_scale = self.width() / self.original_video_width; y_scale = self.height() / self.original_video_height
        return QPoint(int(video_point.x() * x_scale), int(video_point.y() * y_scale))