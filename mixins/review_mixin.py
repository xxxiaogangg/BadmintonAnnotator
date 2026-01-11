# file: mixins/review_mixin.py

class ReviewMixin:
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
