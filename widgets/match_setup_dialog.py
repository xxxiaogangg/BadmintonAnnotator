# file: widgets/match_setup_dialog.py

from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QComboBox)

class MatchSetupDialog(QDialog):
    def __init__(self, current_info=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置比赛信息")

        layout = QFormLayout(self)

        self.event_name_input = QLineEdit(current_info.get("event_name", ""))
        self.event_level_input = QLineEdit(current_info.get("event_level", ""))
        
        self.match_stage_input = QComboBox()
        stages = ["小组赛", "1/8决赛", "1/4决赛", "半决赛", "决赛", "其他"]
        self.match_stage_input.addItems(stages)
        current_stage = current_info.get("match_stage")
        if current_stage in stages:
            self.match_stage_input.setCurrentText(current_stage)

        self.player_a_input = QLineEdit(current_info.get("player_a", "球员A"))
        self.player_b_input = QLineEdit(current_info.get("player_b", "球员B"))

        layout.addRow("赛事名称:", self.event_name_input)
        layout.addRow("赛事级别:", self.event_level_input)
        layout.addRow("比赛阶段:", self.match_stage_input)
        layout.addRow("球员A:", self.player_a_input)
        layout.addRow("球员B:", self.player_b_input)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_data(self):
        """返回用户输入的字典数据"""
        return {
            "event_name": self.event_name_input.text(),
            "event_level": self.event_level_input.text(),
            "match_stage": self.match_stage_input.currentText(),
            "player_a": self.player_a_input.text(),
            "player_b": self.player_b_input.text(),
        }
    
    

