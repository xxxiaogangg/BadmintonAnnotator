# file: mixins/event_tree_mixin.py

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QAbstractItemView, QTreeWidgetItem, QTreeWidgetItemIterator, QMessageBox

from core.data_model import COURT_SIDE_ASSIGNMENT_VERSION, normalize_court_side_assignment
from widgets.drawing_label import (
    RallyEndReasonDialog,
    ServeTechniqueSelectionDialog,
    ShotTechniqueSelectionDialog,
)
from widgets.serve_player_dialog import CourtSideAssignmentDialog


class EventTreeMixin:
    def _create_event_detail_dialog(self, event_type, details):
        if event_type == "RALLY_START":
            return ServeTechniqueSelectionDialog(details, self)
        if event_type == "SHOT":
            return ShotTechniqueSelectionDialog(details, self)
        if event_type == "RALLY_END":
            return RallyEndReasonDialog(details, self)
        return None

    def _format_rally_end_text(self, details):
        winner = details.get("winner", "")
        reason = details.get("minor")
        if reason and reason != "待定":
            return f"得分: {winner} | 原因: {reason}"
        return f"得分: {winner}"

    def _format_technique_text(self, details):
        hand = details.get("hand", "待定")

        extra_parts = []
        serve_landing = details.get("serve_landing")
        if serve_landing and serve_landing != "待定":
            extra_parts.append(f"落点:{serve_landing}")
        shot_route = details.get("shot_route")
        if shot_route and shot_route != "待定":
            extra_parts.append(f"线路:{shot_route}")
        court_position = details.get("court_position")
        if court_position and court_position != "待定":
            extra_parts.append(f"位置:{court_position}")

        if hand != "适用":
            base_text = str(hand) if hand else "待定"
            return " | ".join([base_text] + extra_parts) if extra_parts else base_text

        minor = details.get("minor", "待定")
        if not minor or minor == "待定":
            return " | ".join(["待定"] + extra_parts) if extra_parts else "待定"

        technique_hand = details.get("technique_hand", "")
        if technique_hand and technique_hand != "待定":
            technique_text = f"{technique_hand}{minor}"
        else:
            technique_text = minor

        if extra_parts:
            return " | ".join([technique_text] + extra_parts)
        return technique_text

    def _reset_event_tree_view(self):
        """清空事件树并重置缓存，适用于无标注时的快速刷新"""
        if hasattr(self, "event_tree"):
            self.event_tree.setUpdatesEnabled(False)
            self.event_tree.clear()
            self.event_tree.setUpdatesEnabled(True)
        self.event_items = {}
        self.event_by_id = {}
        self.update_review_stats()

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
        all_items = {}  # key: event_id, value: QTreeWidgetItem

        events = self.annotations.get('events', [])
        self.event_by_id = {
            e.get('event_id'): e for e in events if isinstance(e, dict) and e.get('event_id')
        }

        set_counter = 0
        orphan_rally_counter = 0
        rally_counter_map = {}
        current_set_item = None
        current_set_id = None
        current_rally_item = None

        for event in events:
            event_id = event.get('event_id')
            event_type = event.get('type')
            if not event_id or not event_type:
                continue

            if event_type == 'SET_START':
                set_counter += 1
                current_set_id = event_id
                current_set_item = QTreeWidgetItem(self.event_tree)
                current_set_item.setText(0, f"🌳 第 {set_counter} 局")
                current_rally_item = None
                rally_counter_map[current_set_id] = 0
                item = current_set_item

            elif event_type == 'RALLY_START':
                if current_set_item:
                    rally_counter_map[current_set_id] += 1
                    rally_num = rally_counter_map[current_set_id]
                    item = QTreeWidgetItem(current_set_item)
                    item.setText(0, f"🏸 回合 {rally_num}")
                else:
                    orphan_rally_counter += 1
                    item = QTreeWidgetItem(self.event_tree)
                    item.setText(0, f"🏸 回合 {orphan_rally_counter}")
                current_rally_item = item
                details = event.get('details', {})
                score_at_start = details.get('score_at_start', [0, 0])
                score_str = f"{score_at_start[0]}-{score_at_start[1]}"
                item.setText(0, f"{item.text(0)} (比分 {score_str})")
                serving_player = details.get('serving_player', '待定')
                technique_display = self._format_technique_text(details)
                view_desc = details.get('view_desc', '视角正常')
                item.setText(1, f"{serving_player}: {technique_display}-{view_desc}")

            elif event_type in ['SHOT', 'RALLY_END']:
                if current_rally_item:
                    item = QTreeWidgetItem(current_rally_item)
                elif current_set_item:
                    item = QTreeWidgetItem(current_set_item)
                else:
                    item = QTreeWidgetItem(self.event_tree)
                details = event.get('details', {})
                if event_type == 'SHOT':
                    item.setText(0, f"🎾 击球 (帧: {event.get('frame')})")
                    technique_display = self._format_technique_text(details)
                    view_desc = details.get('view_desc', '视角正常')
                    item.setText(1, f"{details.get('player', '待定')}: {technique_display}-{view_desc}")
                else:
                    item.setText(0, f"🏁 回合结束 (帧: {event.get('frame')})")
                    item.setText(1, self._format_rally_end_text(details))

            elif event_type == 'SET_END':
                if current_set_item:
                    item = QTreeWidgetItem(current_set_item)
                else:
                    item = QTreeWidgetItem(self.event_tree)
                item.setText(0, f"🏆 局结束 (帧: {event.get('frame')})")
                final_score = event.get('details', {}).get('final_score')
                if isinstance(final_score, list) and len(final_score) == 2:
                    item.setText(1, f"最终比分: {final_score[0]}-{final_score[1]}")
                    if current_set_item:
                        current_set_item.setText(1, f"最终比分: {final_score[0]}-{final_score[1]}")
            else:
                item = QTreeWidgetItem(self.event_tree)

            item.setData(0, Qt.ItemDataRole.UserRole, event.get('frame'))
            item.setData(0, Qt.ItemDataRole.UserRole + 1, event_id)
            all_items[event_id] = item

        # 2. 所有节点都创建完毕后，一次性恢复展开状态
        for event_id, item in all_items.items():
            if event_id in expanded_ids:
                item.setExpanded(True)

        # 更新全局引用，供审阅模块使用
        self.event_items = all_items

        if len(events) < 5000:
            self.event_tree.resizeColumnToContents(0)
        else:
            self.event_tree.setColumnWidth(0, 180)

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
        if not self.video_worker:
            return

        frame_num = None
        event_id = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if not event_id:
            return

        # 更新最后选中的事件ID，用于连续调整功能
        self.last_selected_event_id = event_id
        if self.shot_loop_enabled:
            self._update_shot_loop_bounds()

        # 找到被点击的事件对象
        clicked_event = self._get_event_by_id(event_id)
        if not clicked_event:
            return

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
            #     self.toggle_play_pause()

    def on_event_tree_item_double_clicked(self, item, column):
        """当事件树中的一项被双击时，用于编辑 SHOT 或 RALLY_END 或 RALLY_START 事件的细节"""
        event_id = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if not event_id:
            return
        self._edit_event_detail_by_id(event_id)

    def _has_valid_court_side_assignment(self):
        assignment = normalize_court_side_assignment(
            self.annotations.get("court_side_assignment"),
            self.annotations.get("match_info", {}),
        )
        self.annotations["court_side_assignment"] = assignment
        return assignment is not None

    def _ensure_court_side_assignment_for_event(self, event_type):
        if event_type not in ["RALLY_START", "SHOT"]:
            return True
        if self._has_valid_court_side_assignment():
            return True

        player_a = self.annotations.get("match_info", {}).get("player_a") or self.player_a_name
        player_b = self.annotations.get("match_info", {}).get("player_b") or self.player_b_name
        if not player_a or not player_b or player_a == player_b:
            QMessageBox.warning(self, "站位信息缺失", "请先在比赛信息中设置两名不同的球员。")
            return False

        dialog = CourtSideAssignmentDialog(player_a, player_b, self)
        if not dialog.exec() or not dialog.assignment:
            return False

        self.annotations["court_side_assignment"] = {
            "version": COURT_SIDE_ASSIGNMENT_VERSION,
            "initial_top_player": dialog.assignment["initial_top_player"],
            "initial_bottom_player": dialog.assignment["initial_bottom_player"],
            "source": "manual",
        }
        if hasattr(self, "_update_court_side_status_label"):
            self._update_court_side_status_label()
        self.set_dirty()
        return True

    def _get_event_index(self, target_event):
        target_event_id = target_event.get("event_id") if isinstance(target_event, dict) else None
        for index, event in enumerate(self.annotations.get("events", [])):
            if event is target_event:
                return index
            if target_event_id and event.get("event_id") == target_event_id:
                return index
        return -1

    def _get_set_number_for_event(self, target_event):
        event_index = self._get_event_index(target_event)
        if event_index < 0:
            return 1
        set_count = 0
        for event in self.annotations.get("events", [])[:event_index + 1]:
            if event.get("type") == "SET_START":
                set_count += 1
        return max(1, set_count)

    def _get_rally_start_for_event(self, target_event):
        if not isinstance(target_event, dict):
            return None
        if target_event.get("type") == "RALLY_START":
            return target_event
        event_index = self._get_event_index(target_event)
        if event_index < 0:
            return None
        events = self.annotations.get("events", [])
        for event in reversed(events[:event_index + 1]):
            if event.get("type") == "RALLY_START":
                return event
        return None

    def _is_court_side_swapped_for_event(self, target_event):
        set_number = self._get_set_number_for_event(target_event)
        if set_number == 2:
            return True
        if set_number == 3:
            rally_start = self._get_rally_start_for_event(target_event)
            score = rally_start.get("details", {}).get("score_at_start", []) if rally_start else []
            if isinstance(score, list) and len(score) >= 2:
                return max(score[0], score[1]) >= 11
        return False

    def _resolve_player_court_half(self, target_event, player_name=None):
        assignment = normalize_court_side_assignment(
            self.annotations.get("court_side_assignment"),
            self.annotations.get("match_info", {}),
        )
        if not assignment:
            return None
        if player_name is None:
            details = target_event.get("details", {}) if isinstance(target_event, dict) else {}
            player_name = details.get("serving_player") or details.get("player")
        if not player_name:
            return None

        top_player = assignment.get("initial_top_player")
        bottom_player = assignment.get("initial_bottom_player")
        if self._is_court_side_swapped_for_event(target_event):
            top_player, bottom_player = bottom_player, top_player
        if player_name == top_player:
            return "top"
        if player_name == bottom_player:
            return "bottom"
        return None

    def _edit_event_detail_by_id(self, event_id):
        if not event_id:
            return

        self.last_selected_event_id = event_id
        if self.shot_loop_enabled:
            self._update_shot_loop_bounds()

        clicked_event = self._get_event_by_id(event_id)
        if not clicked_event:
            return

        event_type = clicked_event['type']

        if event_type not in ['RALLY_START', 'SHOT', 'RALLY_END']:
            return
        if self._tech_dialog_open:
            return
        if not self._ensure_court_side_assignment_for_event(event_type):
            return
        if hasattr(self, "ensure_serving_player_for_event"):
            if not self.ensure_serving_player_for_event(clicked_event):
                return

        self._tech_dialog_open = True
        try:
            details_for_dialog = clicked_event.setdefault('details', {})
            if hasattr(self, "apply_ai_court_position_default"):
                changes = self.apply_ai_court_position_default(clicked_event, details_for_dialog)
                if changes:
                    self._update_event_item_text(clicked_event)
                    self.set_dirty()
            dialog = self._create_event_detail_dialog(event_type, details_for_dialog)
            if not dialog:
                return
            if self._should_default_detail_status_to_applicable(event_type, dialog):
                dialog.set_status("适用")
            result = dialog.exec()
        finally:
            self._tech_dialog_open = False

        if result:
            selection = dialog.get_selection()
            if selection:
                clicked_event['details'].update(selection)
                if clicked_event['type'] in ['RALLY_END', 'SET_START']:
                    self.recalculate_scores()
                print(f"已更新事件 {event_id} 的细节。")
                next_event_id = self._get_next_event_id(event_id)
                target_event_id = next_event_id or event_id
                updated = self._update_event_item_text(clicked_event)
                if not updated:
                    self.refresh_all_ui(scroll_to_event_id=target_event_id)
                self._select_event_in_tree(target_event_id)
                self.event_tree.setFocus()
                self.set_dirty()

                if self.video_worker and target_event_id:
                    target_event = self._get_event_by_id(target_event_id)
                    if target_event and 'frame' in target_event:
                        self.video_worker.seek(target_event['frame'])

        self.update_review_stats()

    def _should_default_detail_status_to_applicable(self, event_type, dialog):
        return (
            event_type in ["RALLY_START", "SHOT"]
            and hasattr(self, 'right_page_combo')
            and self.right_page_combo.currentIndex() == 1
            and hasattr(dialog, "set_status")
        )

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

    def delete_selected_event(self):
        """删除事件，并对齐Set和Rally的删除逻辑"""
        selected_item = self.event_tree.currentItem()
        if not selected_item:
            return

        event_id = selected_item.data(0, Qt.ItemDataRole.UserRole + 1)
        if not event_id:
            return

        events = self.annotations['events']
        event_to_delete = next((e for e in events if e['event_id'] == event_id), None)
        if not event_to_delete:
            return

        indices_to_delete = []
        rally_to_re_evaluate_index = -1
        event_type = event_to_delete['type']

        if event_type == 'RALLY_START' or event_type == 'SET_START':
            # --- 删除整个回合 或 整个局 ---
            unit = "回合" if event_type == 'RALLY_START' else "局"
            reply = QMessageBox.question(self, f"确认删除{unit}",
                                         f"这将删除整个{unit}及其内部的所有事件，是否继续？",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                return

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

        if not indices_to_delete:
            return

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
        self.refresh_all_ui()  # 不带参数，保持当前视图
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

    def _get_event_by_id(self, event_id):
        """根据事件ID获取事件对象，优先使用缓存"""
        if not event_id:
            return None
        if hasattr(self, "event_by_id") and self.event_by_id:
            event = self.event_by_id.get(event_id)
            if event:
                return event
        events = self.annotations.get('events', [])
        return next((e for e in events if e.get('event_id') == event_id), None)

    def _get_next_event_id(self, current_event_id):
        """返回事件列表中当前事件的下一条ID，若没有则返回None"""
        events = self.annotations.get('events', [])
        for idx, e in enumerate(events):
            if e.get('event_id') == current_event_id:
                if idx + 1 < len(events):
                    return events[idx + 1].get('event_id')
                break
        return None

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
        self._edit_event_detail_by_id(event_id)

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

    def _update_event_item_text(self, event):
        """仅更新单条事件在事件树中的显示文本，避免全量刷新"""
        if not event or not hasattr(self, "event_items"):
            return False
        event_id = event.get("event_id")
        if not event_id:
            return False
        item = self.event_items.get(event_id)
        if not item:
            return False
        was_expanded = item.isExpanded()

        event_type = event.get("type")
        details = event.get("details", {})

        if event_type == "SHOT":
            item.setText(0, f"🎾 击球 (帧: {event.get('frame')})")
            technique_display = self._format_technique_text(details)
            view_desc = details.get("view_desc", "视角正常")
            item.setText(1, f"{details.get('player', '待定')}: {technique_display}-{view_desc}")
            return True

        if event_type == "RALLY_START":
            score_at_start = details.get("score_at_start", [0, 0])
            score_str = f"{score_at_start[0]}-{score_at_start[1]}"
            current_title = item.text(0)
            prefix = current_title.split("(比分")[0].strip() if "(比分" in current_title else "🏸 回合"
            item.setText(0, f"{prefix} (比分 {score_str})")
            serving_player = details.get("serving_player", "待定")
            technique_display = self._format_technique_text(details)
            view_desc = details.get("view_desc", "视角正常")
            item.setText(1, f"{serving_player}: {technique_display}-{view_desc}")
            item.setExpanded(was_expanded)
            return True

        if event_type == "RALLY_END":
            item.setText(0, f"🏁 回合结束 (帧: {event.get('frame')})")
            item.setText(1, self._format_rally_end_text(details))
            item.setExpanded(was_expanded)
            return True

        if event_type == "SET_END":
            item.setText(0, f"🏆 局结束 (帧: {event.get('frame')})")
            final_score = details.get("final_score")
            if isinstance(final_score, list) and len(final_score) == 2:
                item.setText(1, f"最终比分: {final_score[0]}-{final_score[1]}")
            item.setExpanded(was_expanded)
            return True

        return False

    def _update_event_items(self, events):
        """批量更新事件树条目文本"""
        if not events:
            return
        for event in events:
            self._update_event_item_text(event)

    def _find_set_start_index(self, events, event_index):
        """向前查找所属局的起点（SET_START）索引"""
        for i in range(event_index, -1, -1):
            if events[i].get("type") == "SET_START":
                return i
        return -1

    def _rebuild_set_subtree(self, set_start_index):
        """仅重建某一局（SET_START 到下一个 SET_START 之间）的事件树子节点"""
        events = self.annotations.get("events", [])
        if not events or set_start_index < 0 or set_start_index >= len(events):
            return False
        set_event = events[set_start_index]
        if set_event.get("type") != "SET_START":
            return False
        set_event_id = set_event.get("event_id")
        if not set_event_id:
            return False

        set_item = self.event_items.get(set_event_id)
        if not set_item:
            return False

        # 记录子树展开状态
        expanded_ids = set()

        def collect_expanded(item):
            if item.isExpanded():
                item_id = item.data(0, Qt.ItemDataRole.UserRole + 1)
                if item_id:
                    expanded_ids.add(item_id)
            for i in range(item.childCount()):
                collect_expanded(item.child(i))

        collect_expanded(set_item)

        # 找到该局的结束索引
        end_index = len(events)
        for i in range(set_start_index + 1, len(events)):
            if events[i].get("type") == "SET_START":
                end_index = i
                break

        # 清理旧的子节点与映射
        for event in events[set_start_index + 1:end_index]:
            event_id = event.get("event_id")
            if event_id in self.event_items:
                del self.event_items[event_id]
        set_item.takeChildren()

        rally_counter = 0
        current_rally_item = None
        final_score = None

        for event in events[set_start_index + 1:end_index]:
            event_id = event.get("event_id")
            event_type = event.get("type")
            if not event_id or not event_type:
                continue

            if event_type == "RALLY_START":
                rally_counter += 1
                item = QTreeWidgetItem(set_item)
                item.setText(0, f"🏸 回合 {rally_counter}")
                current_rally_item = item
                details = event.get("details", {})
                score_at_start = details.get("score_at_start", [0, 0])
                score_str = f"{score_at_start[0]}-{score_at_start[1]}"
                item.setText(0, f"{item.text(0)} (比分 {score_str})")
                serving_player = details.get("serving_player", "待定")
                technique_display = self._format_technique_text(details)
                view_desc = details.get("view_desc", "视角正常")
                item.setText(1, f"{serving_player}: {technique_display}-{view_desc}")

            elif event_type in ["SHOT", "RALLY_END"]:
                parent_item = current_rally_item if current_rally_item else set_item
                item = QTreeWidgetItem(parent_item)
                details = event.get("details", {})
                if event_type == "SHOT":
                    item.setText(0, f"🎾 击球 (帧: {event.get('frame')})")
                    technique_display = self._format_technique_text(details)
                    view_desc = details.get("view_desc", "视角正常")
                    item.setText(1, f"{details.get('player', '待定')}: {technique_display}-{view_desc}")
                else:
                    item.setText(0, f"🏁 回合结束 (帧: {event.get('frame')})")
                    item.setText(1, self._format_rally_end_text(details))

            elif event_type == "SET_END":
                item = QTreeWidgetItem(set_item)
                item.setText(0, f"🏆 局结束 (帧: {event.get('frame')})")
                final_score = event.get("details", {}).get("final_score")
                if isinstance(final_score, list) and len(final_score) == 2:
                    item.setText(1, f"最终比分: {final_score[0]}-{final_score[1]}")

            else:
                item = QTreeWidgetItem(set_item)

            item.setData(0, Qt.ItemDataRole.UserRole, event.get("frame"))
            item.setData(0, Qt.ItemDataRole.UserRole + 1, event_id)
            self.event_items[event_id] = item

        if isinstance(final_score, list) and len(final_score) == 2:
            set_item.setText(1, f"最终比分: {final_score[0]}-{final_score[1]}")
        else:
            set_item.setText(1, "")

        # 恢复展开状态
        for event_id in expanded_ids:
            item = self.event_items.get(event_id)
            if item:
                item.setExpanded(True)

        return True

    def _refresh_score_related_items(self):
        """刷新与比分相关的事件显示（RALLY_START/SET_END）"""
        if not hasattr(self, "event_items"):
            return
        events = self.annotations.get("events", [])
        for idx, event in enumerate(events):
            event_type = event.get("type")
            if event_type == "RALLY_START":
                self._update_event_item_text(event)
            elif event_type == "SET_END":
                self._update_event_item_text(event)
                parent_event = next(
                    (e for e in reversed(events[:idx]) if e.get("type") == "SET_START"),
                    None,
                )
                if parent_event:
                    parent_item = self.event_items.get(parent_event.get("event_id"))
                    final_score = event.get("details", {}).get("final_score")
                    if parent_item and isinstance(final_score, list) and len(final_score) == 2:
                        parent_item.setText(1, f"最终比分: {final_score[0]}-{final_score[1]}")

    def _insert_event_item(self, event):
        """追加单条事件到事件树（仅适用于事件在时间线末尾）"""
        if not event or not hasattr(self, "event_tree"):
            return None

        events = self.annotations.get("events", [])
        if not events:
            return None

        event_id = event.get("event_id")
        event_type = event.get("type")
        if not event_id or not event_type:
            return None

        parent_item = None
        if event_type in ["RALLY_START", "SET_END"]:
            parent_event = next((e for e in reversed(events) if e.get("type") == "SET_START"), None)
            if parent_event:
                parent_item = self.event_items.get(parent_event.get("event_id"))
        elif event_type in ["SHOT", "RALLY_END"]:
            parent_event = next((e for e in reversed(events) if e.get("type") == "RALLY_START"), None)
            if not parent_event:
                return None
            parent_item = self.event_items.get(parent_event.get("event_id"))
            if not parent_item:
                return None

        if parent_item:
            parent_item.setExpanded(True)
            item = QTreeWidgetItem(parent_item)
        else:
            item = QTreeWidgetItem(self.event_tree)

        item.setData(0, Qt.ItemDataRole.UserRole, event.get("frame"))
        item.setData(0, Qt.ItemDataRole.UserRole + 1, event_id)
        if not hasattr(self, "event_items"):
            self.event_items = {}
        self.event_items[event_id] = item

        if event_type == "SET_START":
            set_count = sum(1 for e in events if e.get("type") == "SET_START")
            item.setText(0, f"🌳 第 {set_count} 局")
        elif event_type == "RALLY_START":
            parent_event = next((e for e in reversed(events) if e.get("type") == "SET_START"), None)
            if parent_event:
                start_index = events.index(parent_event)
                rally_num = sum(1 for e in events[start_index:] if e.get("type") == "RALLY_START")
                item.setText(0, f"🏸 回合 {rally_num}")
            else:
                item.setText(0, "🏸 回合")
            self._update_event_item_text(event)
        else:
            self._update_event_item_text(event)

        if event_type == "SET_END" and parent_item:
            final_score = event.get("details", {}).get("final_score")
            if isinstance(final_score, list) and len(final_score) == 2:
                parent_item.setText(1, f"最终比分: {final_score[0]}-{final_score[1]}")
        if hasattr(self, "event_tree") and len(events) < 5000:
            self.event_tree.resizeColumnToContents(0)
        return item
