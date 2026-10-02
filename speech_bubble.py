"""Painted manga speech balloon, attached to a pet without taking focus."""
import math

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QHBoxLayout, QWidget


class SpeechBubble(QWidget):
    dismissed = pyqtSignal()

    def __init__(self, pet, configure_mouse_only):
        super().__init__(pet)
        self.pet = pet
        configure_mouse_only(self)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName("speechBubble")
        self.notification_id = None
        self.tail_on_bottom = True
        self.tail_x = 170
        self.layout_box = QVBoxLayout(self)
        self.layout_box.setSpacing(8)
        header = QHBoxLayout()
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setStyleSheet("color: #99557f; font-weight: 700; font-size: 12px;")
        self.title.setMinimumWidth(0)
        header.addWidget(self.title, 1)
        self.queue_badge = QLabel()
        self.queue_badge.setObjectName("notificationQueueBadge")
        self.queue_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.queue_badge.setMinimumWidth(24)
        self.queue_badge.setFixedHeight(24)
        self.queue_badge.setStyleSheet("background: #e4495b; color: white; border-radius: 12px;"
                                      "font-size: 12px; font-weight: 700; padding: 0 6px;")
        self.queue_badge.hide()
        header.addWidget(self.queue_badge)
        self.close_button = QPushButton("×")
        self.close_button.setToolTip("关闭当前通知，有排队消息时显示下一条")
        self.close_button.setAccessibleName("关闭当前通知")
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_button.setFixedSize(24, 24)
        self.close_button.setStyleSheet("QPushButton { border: none; border-radius: 12px; color: #895874;"
                            "background: #f6dcea; font-size: 19px; }"
                            "QPushButton:hover { background: #efbdd7; }")
        self.close_button.clicked.connect(self.dismiss)
        header.addWidget(self.close_button)
        self.layout_box.addLayout(header)

        self.body = QTextBrowser()
        self.body.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.body.setReadOnly(True)
        self.body.setOpenLinks(False)
        self.body.setOpenExternalLinks(False)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.body.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.body.setFont(QFont("Sans Serif", 11))
        self.body.setStyleSheet("QTextBrowser { border: none; background: transparent; color: #46354e; }"
                               "QScrollBar:vertical { width: 5px; background: transparent; }"
                               "QScrollBar::handle:vertical { background: #d9a7c6; min-height: 20px; border-radius: 2px; }"
                               "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
                               "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }")
        self.layout_box.addWidget(self.body)
        self.footer = QLabel()
        self.footer.setStyleSheet("color: #a07e98; font-size: 10px;")
        self.layout_box.addWidget(self.footer)

    def present(self, notification, queued, *, body_only=False):
        self.notification_id = notification.id
        screen = self.pet.screen() or QApplication.primaryScreen()
        area = screen.availableGeometry()
        self.setFixedWidth(min(360, max(180, area.width() - 20)))
        self.title.setText("" if body_only else "✦ " + notification.title)
        self.title.setVisible(not body_only)
        self.close_button.setVisible(not body_only)
        self.footer.setVisible(not body_only)
        # Plain text prevents agent messages from loading HTML or remote content.
        self.body.setPlainText(notification.message)
        self.body.document().setTextWidth(self.width() - 58)
        max_body = min(220, max(40, area.height() - 135))
        self.body.setFixedHeight(min(max_body, max(40, math.ceil(self.body.document().size().height()) + 6)))
        self.set_queue_count(queued)
        if body_only:
            self.queue_badge.hide()
        self.layout_box.setContentsMargins(22, 17, 22, 31)
        self.setFixedHeight(self.layout_box.sizeHint().height())
        self.reposition()
        self.show()
        self.body.verticalScrollBar().setValue(0)

    def set_queue_count(self, queued):
        self.queue_badge.setText(str(queued))
        self.queue_badge.setToolTip(f"还有 {queued} 条消息排队，关闭当前消息后显示下一条")
        self.queue_badge.setAccessibleName(f"排队消息：{queued} 条")
        self.queue_badge.setVisible(queued > 0)
        self.footer.setText("点击 × 查看下一条 · 滚轮阅读长消息" if queued else "点击 × 关闭 · 滚轮阅读长消息")

    def reposition(self):
        area = self.pet.screen().availableGeometry()
        anchor_x = self.pet.x() + self.pet.width() // 2
        above = self.pet.y() - self.height() + 8
        below = self.pet.y() + self.pet.height() - 8
        self.tail_on_bottom = above >= area.top() + 6 or below + self.height() > area.bottom() - 6
        top = above if self.tail_on_bottom else below
        top = max(area.top() + 6, min(top, area.bottom() - self.height() - 6))
        left = max(area.left() + 6, min(anchor_x - self.width() // 2, area.right() - self.width() - 6))
        self.tail_x = max(35, min(self.width() - 35, anchor_x - left))
        self.layout_box.setContentsMargins(22, 17 if self.tail_on_bottom else 31,
                                           22, 31 if self.tail_on_bottom else 17)
        self.move(QPoint(left, top))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        top = 5 if self.tail_on_bottom else 20
        panel = QRectF(5, top, self.width() - 14, self.height() - 29)
        path = QPainterPath()
        path.addRoundedRect(panel, 20, 20)
        tail = QPainterPath()
        edge = panel.bottom() if self.tail_on_bottom else panel.top()
        tail.moveTo(self.tail_x - 13, edge - (2 if self.tail_on_bottom else -2))
        tail.lineTo(self.tail_x + 2, edge + (17 if self.tail_on_bottom else -17))
        tail.lineTo(self.tail_x + 15, edge - (2 if self.tail_on_bottom else -2))
        tail.closeSubpath()
        path = path.united(tail)
        painter.fillPath(path.translated(3, 4), QColor(80, 45, 90, 42))
        gradient = QLinearGradient(panel.topLeft(), panel.bottomRight())
        gradient.setColorAt(0, QColor("#fffdf9"))
        gradient.setColorAt(1, QColor("#fff0f8"))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor("#91658d"), 2.2))
        painter.drawPath(path)
        painter.setPen(QPen(QColor("#efbfd5"), 2))
        painter.drawArc(QRectF(panel.left() + 7, panel.top() + 7, 20, 20), 90 * 16, 90 * 16)
        painter.setPen(QPen(QColor("#dba2c6"), 1.6))
        center = QPointF(panel.right() - 12, panel.bottom() - 12)
        painter.drawLine(center + QPointF(-4, 0), center + QPointF(4, 0))
        painter.drawLine(center + QPointF(0, -4), center + QPointF(0, 4))

    def closeEvent(self, event):
        event.ignore()
        self.dismiss()

    def dismiss(self):
        if not self.isVisible():
            return
        self.hide()
        self.dismissed.emit()
