"""Edit relative idle weights and preview their actual selection probabilities."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QDoubleSpinBox, QHeaderView,
                             QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout)

from idle_weights import MAX_IDLE_WEIGHT, default_idle_weights


class IdleWeightsDialog(QDialog):
    def __init__(self, animation, parent=None):
        super().__init__(parent)
        self.setWindowTitle("待机组出现概率权重")
        self.names = list(animation.idle_group)
        self.defaults = default_idle_weights(self.names, animation.pet.idle)
        self.weights = dict(animation.idle_weights)
        self.spins = {}
        layout = QVBoxLayout(self)
        hint = QLabel("按权重比例抽取，每播放一轮重新选择。\n"
                      "默认待机占 90%，其他已选表情平分 10%；权重为 0 表示不出现。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.table = QTableWidget(len(self.names), 3)
        self.table.setHorizontalHeaderLabels(["表情", "权重", "出现概率"])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row, name in enumerate(self.names):
            label = QTableWidgetItem(animation.pet.labels.get(name, name))
            label.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 0, label)
            spin = QDoubleSpinBox()
            spin.setRange(0, MAX_IDLE_WEIGHT)
            spin.setDecimals(6)
            spin.setValue(self.weights.get(name, self.defaults[name]))
            spin.setAccessibleName(f"{label.text()}的出现权重")
            spin.valueChanged.connect(lambda value, n=name: self.change_weight(n, value))
            self.spins[name] = spin
            self.table.setCellWidget(row, 1, spin)
            probability = QTableWidgetItem()
            probability.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 2, probability)
        layout.addWidget(self.table)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
                                   | QDialogButtonBox.StandardButton.RestoreDefaults)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).setText("恢复默认")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self.restore_defaults)
        layout.addWidget(buttons)
        self.update_probabilities()
        self.resize(560, min(520, 210 + len(self.names) * 32))

    def change_weight(self, name, value):
        self.weights[name] = value
        self.update_probabilities()

    def update_probabilities(self):
        values = {name: self.weights.get(name, self.defaults[name]) for name in self.names}
        total = sum(values.values())
        for row, name in enumerate(self.names):
            probability = values[name] / total if total else 0.0
            self.table.item(row, 2).setText(f"{probability:.2%}")
        self.summary.setText("全部权重为 0 时显示静止的基础待机姿势。" if not total else "概率按每次动作选择计算。")

    def restore_defaults(self):
        self.weights = {}
        for name, spin in self.spins.items():
            spin.blockSignals(True)
            spin.setValue(self.defaults[name])
            spin.blockSignals(False)
        self.update_probabilities()
