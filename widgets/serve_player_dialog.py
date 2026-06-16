# file: widgets/serve_player_dialog.py

from PyQt6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

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


class CourtSideAssignmentDialog(QDialog):
    """选择第1局开局时两名球员的上下半场。"""
    def __init__(self, player_a, player_b, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置第1局开局站位")
        self.setMinimumWidth(360)
        self.assignment = None

        layout = QVBoxLayout(self)
        prompt = QLabel("请选择第1局开局时，画面上方和下方分别是谁。")
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

        btn_a_top = QPushButton(f"{player_a} 在上 / {player_b} 在下")
        btn_b_top = QPushButton(f"{player_b} 在上 / {player_a} 在下")

        btn_a_top.clicked.connect(lambda: self.select_assignment(player_a, player_b))
        btn_b_top.clicked.connect(lambda: self.select_assignment(player_b, player_a))

        layout.addWidget(btn_a_top)
        layout.addWidget(btn_b_top)

    def select_assignment(self, top_player, bottom_player):
        self.assignment = {
            "initial_top_player": top_player,
            "initial_bottom_player": bottom_player,
        }
        self.accept()
