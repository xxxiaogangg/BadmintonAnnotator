# file: main.py (在顶部 import 部分添加 QDialog, QDialogButtonBox)

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QPushButton)

class ServePlayerDialog(QDialog):
    """一个简单的对话框，用于选择发球方"""
    def __init__(self, player_a, player_b, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择发球方")
        layout = QVBoxLayout(self)
        self.serving_player = None

        btn_a = QPushButton(player_a)
        btn_b = QPushButton(player_b)

        btn_a.clicked.connect(lambda: self.select_player(player_a))
        btn_b.clicked.connect(lambda: self.select_player(player_b))

        layout.addWidget(btn_a)
        layout.addWidget(btn_b)

    def select_player(self, player_name):
        self.serving_player = player_name
        self.accept()

class WinnerSelectionDialog(QDialog):
    """一个简单的对话框，用于选择本回合的得分方"""
    def __init__(self, player_a, player_b, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择得分方")
        layout = QVBoxLayout(self)
        self.winner = None

        btn_a = QPushButton(f"{player_a} 得分")
        btn_b = QPushButton(f"{player_b} 得分")

        btn_a.clicked.connect(lambda: self.select_winner(player_a))
        btn_b.clicked.connect(lambda: self.select_winner(player_b))

        layout.addWidget(btn_a)
        layout.addWidget(btn_b)

    def select_winner(self, player_name):
        self.winner = player_name
        self.accept()