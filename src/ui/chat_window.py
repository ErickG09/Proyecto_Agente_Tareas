# src/ui/chat_window.py
from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets


# ============================ Estilos (QSS) ==========================================

LIGHT_QSS = """
* { font-family: 'Segoe UI', 'Inter', 'Roboto', sans-serif; }

QMainWindow { background: #F5F7FB; }

/* ---- Top Bar ---- */
QFrame#TopBar {
    background: #FFFFFF;
    border-bottom: 1px solid #E6EAF2;
}

QLabel#Title {
    color: #1B2430;
    font-size: 16px;
    font-weight: 800;
}

QLabel#UserBadge {
    color: #1B2430;
    background: #EEF2FF;
    border: 1px solid #D7DBF0;
    padding: 4px 10px;
    border-radius: 10px;
    font-weight: 700;
    font-size: 12px;
}

/* ---- Toolbar buttons ---- */
QToolButton {
    background: #FFFFFF;
    color: #344155;
    border: 1px solid #DDE3EE;
    border-radius: 10px;
    padding: 7px 10px;
}
QToolButton:hover { background: #F3F6FC; }

/* ---- Splitter ---- */
QSplitter::handle {
    background: #E6EAF2;
}
QSplitter::handle:hover {
    background: #D7DBF0;
}

/* ---- Left Sidebar ---- */
QFrame#Sidebar {
    background: #F5F7FB;
    border: none;
}

QScrollArea#SidebarScroll { border: none; background: transparent; }
QWidget#SidebarInner { background: transparent; }

/* "Card" panels */
QFrame#Card {
    background: #FFFFFF;
    border: 1px solid #E6EAF2;
    border-radius: 14px;
}
QLabel#SectionTitle {
    color: #1B2430;
    font-weight: 800;
    font-size: 12px;
}
QLabel#Hint {
    color: #667085;
    font-size: 11px;
}

/* Inputs */
QLineEdit, QComboBox {
    background: #FFFFFF;
    border: 1px solid #DDE3EE;
    border-radius: 10px;
    padding: 8px 10px;
    color: #1B2430;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid #7AA7FF;
}

QComboBox::drop-down { border: 0px; }

QCheckBox { color: #1B2430; }

/* Buttons */
QPushButton {
    background: #FFFFFF;
    color: #1B2430;
    border: 1px solid #DDE3EE;
    border-radius: 12px;
    padding: 10px 14px;
    font-weight: 700;
}
QPushButton:hover { background: #F3F6FC; }

QPushButton#Primary {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #2F6BFF, stop:1 #6B4DFF);
    border: 0;
    color: #FFFFFF;
}
QPushButton#Primary:hover {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #2A5FE5, stop:1 #5F44E5);
}

/* ---- Right Chat Area ---- */
QFrame#ChatArea {
    background: #FFFFFF;
    border: 1px solid #E6EAF2;
    border-radius: 14px;
}

QScrollArea#ChatScroll { border: none; background: transparent; }
QWidget#ChatInner { background: transparent; }

QTextEdit {
    background: #FFFFFF;
    color: #1B2430;
    border: 1px solid #DDE3EE;
    border-radius: 12px;
    padding: 10px;
    selection-background-color: #CFE6FF;
}
"""


# ============================ Burbuja de chat ========================================

class ChatBubble(QtWidgets.QFrame):
    """Burbuja para 'assistant' o 'user'."""
    def __init__(self, text: str, role: str = "assistant", parent=None):
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)

        is_assistant = (role == "assistant")
        bg = "#FFFFFF" if is_assistant else "#EEF2FF"
        border = "#E6EAF2" if is_assistant else "#D7DBF0"

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        container = QtWidgets.QFrame()
        container.setStyleSheet(
            f"QFrame {{background:{bg}; border:1px solid {border}; border-radius:14px;}}"
            "QLabel {color:#1B2430; padding:8px;}"
        )
        v = QtWidgets.QVBoxLayout(container)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)

        label = QtWidgets.QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(label)

        who = QtWidgets.QLabel("Profesor Asesor" if is_assistant else "Tú")
        who.setStyleSheet("color:#667085; font-size:11px;")
        v.addWidget(who, alignment=QtCore.Qt.AlignmentFlag.AlignRight)

        if is_assistant:
            layout.addWidget(container, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
            layout.addStretch()
        else:
            layout.addStretch()
            layout.addWidget(container, 0, QtCore.Qt.AlignmentFlag.AlignRight)


# ============================ Input ====================================

class ChatInput(QtWidgets.QTextEdit):
    sendRequested = QtCore.pyqtSignal()

    def keyPressEvent(self, e: QtGui.QKeyEvent):
        if e.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            if e.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier:
                return super().keyPressEvent(e)
            self.sendRequested.emit()
            return
        return super().keyPressEvent(e)


# ============================ Ventana principal ======================================

class ChatWindow(QtWidgets.QMainWindow):
    """
    UI completa. Señales:
      - sendMessage(str)
      - changeUser(str)
      - requestUserList()
    """

    sendMessage = QtCore.pyqtSignal(str)
    changeUser = QtCore.pyqtSignal(str)
    requestUserList = QtCore.pyqtSignal()

    def __init__(self, *, title: str = "Profesor Asesor — Chat"):
        super().__init__()
        self.setWindowTitle(title)
        self.resize(1200, 760)
        self.setStyleSheet(LIGHT_QSS)

        self._current_user = "Sin sesión"
        self._build_ui()
        self._connect_signals()

    # ---------------- UI ----------------

    def _build_ui(self):
        central = QtWidgets.QWidget()
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # ===== Top bar =====
        top = QtWidgets.QFrame()
        top.setObjectName("TopBar")
        ht = QtWidgets.QHBoxLayout(top)
        ht.setContentsMargins(16, 12, 16, 12)
        ht.setSpacing(10)

        self.lbl_title = QtWidgets.QLabel("Profesor Asesor")
        self.lbl_title.setObjectName("Title")
        ht.addWidget(self.lbl_title)

        ht.addStretch()

        self.lbl_user_badge = QtWidgets.QLabel("Sin sesión")
        self.lbl_user_badge.setObjectName("UserBadge")
        ht.addWidget(self.lbl_user_badge)

        self.btn_toggle_panel = QtWidgets.QToolButton()
        self.btn_toggle_panel.setText("Panel")
        self.btn_toggle_panel.setToolTip("Mostrar/Ocultar panel izquierdo")
        ht.addWidget(self.btn_toggle_panel)

        self.btn_clear = QtWidgets.QToolButton()
        self.btn_clear.setText("Limpiar")
        ht.addWidget(self.btn_clear)

        root.addWidget(top)

        # ===== Main split: left sidebar / right chat =====
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)

        # ---- Left: Sidebar (scrollable) ----
        self.sidebar = QtWidgets.QFrame()
        self.sidebar.setObjectName("Sidebar")

        side_layout = QtWidgets.QVBoxLayout(self.sidebar)
        side_layout.setContentsMargins(12, 12, 12, 12)
        side_layout.setSpacing(10)

        self.sidebar_scroll = QtWidgets.QScrollArea()
        self.sidebar_scroll.setObjectName("SidebarScroll")
        self.sidebar_scroll.setWidgetResizable(True)

        self.sidebar_inner = QtWidgets.QWidget()
        self.sidebar_inner.setObjectName("SidebarInner")
        self.sidebar_v = QtWidgets.QVBoxLayout(self.sidebar_inner)
        self.sidebar_v.setContentsMargins(0, 0, 0, 0)
        self.sidebar_v.setSpacing(10)

        # Cards
        self._card_user()
        self._card_context()
        self._card_mode()
        self._card_quiz()

        self.sidebar_v.addStretch()
        self.sidebar_scroll.setWidget(self.sidebar_inner)
        side_layout.addWidget(self.sidebar_scroll)

        # ---- Right: Chat Area ----
        self.chat_area = QtWidgets.QFrame()
        self.chat_area.setObjectName("ChatArea")

        chat_root = QtWidgets.QVBoxLayout(self.chat_area)
        chat_root.setContentsMargins(12, 12, 12, 12)
        chat_root.setSpacing(10)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setObjectName("ChatScroll")
        self.scroll.setWidgetResizable(True)

        self.chat_container = QtWidgets.QWidget()
        self.chat_container.setObjectName("ChatInner")
        self.chat_layout = QtWidgets.QVBoxLayout(self.chat_container)
        self.chat_layout.setContentsMargins(8, 8, 8, 8)
        self.chat_layout.setSpacing(8)
        self.chat_layout.addStretch()

        self.scroll.setWidget(self.chat_container)
        chat_root.addWidget(self.scroll, 1)

        # Input (inside chat card)
        bottom = QtWidgets.QFrame()
        hb = QtWidgets.QHBoxLayout(bottom)
        hb.setContentsMargins(0, 0, 0, 0)
        hb.setSpacing(10)

        self.txt_input = ChatInput()
        self.txt_input.setMinimumHeight(78)
        self.txt_input.setPlaceholderText("Escribe tu pregunta…  (Shift+Enter = salto de línea)")
        hb.addWidget(self.txt_input, 1)

        self.btn_send = QtWidgets.QPushButton("Enviar")
        self.btn_send.setObjectName("Primary")
        self.btn_send.setFixedHeight(44)
        self.btn_send.setMinimumWidth(120)
        hb.addWidget(self.btn_send)

        chat_root.addWidget(bottom, 0)

        # Add to splitter
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.chat_area)

        # Default sizes (left ~360px, right rest)
        self.splitter.setSizes([380, 820])

        root.addWidget(self.splitter, 1)
        self.setCentralWidget(central)

    # ---------------- Cards (Sidebar) ----------------

    def _make_card(self, title: str) -> tuple[QtWidgets.QFrame, QtWidgets.QVBoxLayout]:
        card = QtWidgets.QFrame()
        card.setObjectName("Card")
        v = QtWidgets.QVBoxLayout(card)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(10)

        lbl = QtWidgets.QLabel(title)
        lbl.setObjectName("SectionTitle")
        v.addWidget(lbl)
        return card, v

    def _card_user(self):
        card, v = self._make_card("Usuario")

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        self.le_user = QtWidgets.QLineEdit()
        self.le_user.setPlaceholderText("Nombre para iniciar sesión…")
        self.le_user.setClearButtonEnabled(True)
        grid.addWidget(self.le_user, 0, 0, 1, 3)

        self.btn_login = QtWidgets.QPushButton("Entrar")
        self.btn_login.setObjectName("Primary")
        grid.addWidget(self.btn_login, 0, 3, 1, 1)

        self.cb_users = QtWidgets.QComboBox()
        self.cb_users.setMinimumWidth(220)
        grid.addWidget(self.cb_users, 1, 0, 1, 2)

        self.btn_switch = QtWidgets.QPushButton("Cambiar")
        grid.addWidget(self.btn_switch, 1, 2, 1, 1)

        self.btn_refresh_users = QtWidgets.QToolButton()
        self.btn_refresh_users.setText("Actualizar usuarios")
        grid.addWidget(self.btn_refresh_users, 1, 3, 1, 1)

        v.addLayout(grid)

        hint = QtWidgets.QLabel("Tip: Enter en el input para entrar rápido.")
        hint.setObjectName("Hint")
        v.addWidget(hint)

        self.sidebar_v.addWidget(card)

    def _card_context(self):
        card, v = self._make_card("Contexto")

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        self.le_subject = QtWidgets.QLineEdit()
        self.le_subject.setPlaceholderText("Materia (ej. Cálculo)")
        grid.addWidget(self.le_subject, 0, 0, 1, 2)

        self.le_topic = QtWidgets.QLineEdit()
        self.le_topic.setPlaceholderText("Tema (ej. Límites laterales)")
        grid.addWidget(self.le_topic, 1, 0, 1, 2)

        self.btn_apply_context = QtWidgets.QPushButton("Aplicar")
        self.btn_apply_context.setObjectName("Primary")
        grid.addWidget(self.btn_apply_context, 2, 0, 1, 1)

        self.btn_reset_context = QtWidgets.QPushButton("Reset")
        grid.addWidget(self.btn_reset_context, 2, 1, 1, 1)

        v.addLayout(grid)

        hint = QtWidgets.QLabel("Esto guía al asesor y reduce respuestas genéricas.")
        hint.setObjectName("Hint")
        v.addWidget(hint)

        self.sidebar_v.addWidget(card)

    def _card_mode(self):
        card, v = self._make_card("Modo")

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        self.cb_mode = QtWidgets.QComboBox()
        self.cb_mode.addItems(["Tutor", "Directo", "Repaso", "Lab", "Quiz"])
        grid.addWidget(self.cb_mode, 0, 0, 1, 2)

        self.chk_memory = QtWidgets.QCheckBox("Usar memoria (SQLite)")
        self.chk_memory.setChecked(True)
        grid.addWidget(self.chk_memory, 1, 0, 1, 1)

        self.cb_size = QtWidgets.QComboBox()
        self.cb_size.addItems(["corta", "normal", "larga"])
        grid.addWidget(self.cb_size, 1, 1, 1, 1)

        v.addLayout(grid)

        hint = QtWidgets.QLabel("El modo controla límites/estructura. (Quiz se usa con el bloque de abajo.)")
        hint.setObjectName("Hint")
        v.addWidget(hint)

        self.sidebar_v.addWidget(card)

    def _card_quiz(self):
        card, v = self._make_card("Quiz")

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(10)

        self.btn_quiz_start = QtWidgets.QPushButton("Iniciar quiz")
        self.btn_quiz_start.setObjectName("Primary")
        row.addWidget(self.btn_quiz_start, 2)

        self.btn_quiz_reset = QtWidgets.QPushButton("Reiniciar quiz")
        row.addWidget(self.btn_quiz_reset, 1)

        v.addLayout(row)

        hint = QtWidgets.QLabel("En quiz: responde A/B/C/D o escribe “siguiente”.")
        hint.setObjectName("Hint")
        v.addWidget(hint)

        self.sidebar_v.addWidget(card)

    # ---------------- Signals ----------------

    def _connect_signals(self):
        # Chat
        self.btn_send.clicked.connect(self._on_send_clicked)
        self.txt_input.sendRequested.connect(self._on_send_clicked)
        self.btn_clear.clicked.connect(self.clear_chat)

        self.btn_toggle_panel.clicked.connect(self._toggle_panel)

        # Usuario
        self.btn_login.clicked.connect(self._on_login_clicked)
        self.btn_switch.clicked.connect(self._on_switch_clicked)
        self.btn_refresh_users.clicked.connect(self.requestUserList.emit)
        self.le_user.returnPressed.connect(self._on_login_clicked)

        # Contexto
        self.btn_apply_context.clicked.connect(self._on_apply_context)
        self.btn_reset_context.clicked.connect(self._on_reset_context)

        # Modo / Memoria / Tamaño
        self.cb_mode.currentTextChanged.connect(self._on_mode_changed)
        self.chk_memory.toggled.connect(self._on_memory_toggled)
        self.cb_size.currentTextChanged.connect(self._on_size_changed)

        # Quiz: comandos
        self.btn_quiz_start.clicked.connect(lambda: self._send_system_command("/quiz start"))
        self.btn_quiz_reset.clicked.connect(lambda: self._send_system_command("/quiz reset"))

    # ---------------- API pública ----------------

    def append_user(self, text: str):
        self._append_bubble(text, role="user")

    def append_assistant(self, text: str):
        self._append_bubble(text, role="assistant")

    def clear_chat(self):
        for i in reversed(range(self.chat_layout.count() - 1)):
            w = self.chat_layout.itemAt(i).widget()
            if w:
                w.setParent(None)

    def set_header_title(self, text: str):
        self.lbl_title.setText(text)

    def set_current_user(self, name: str):
        self._current_user = name or "Sin sesión"
        self.lbl_user_badge.setText(self._current_user)

    def set_users(self, users: list[str]):
        self.cb_users.blockSignals(True)
        self.cb_users.clear()
        self.cb_users.addItems(users or [])
        self.cb_users.blockSignals(False)

    def apply_state(self, state: dict):
        """
        Conecta esto a backend.stateChanged para reflejar estado actual.
        """
        try:
            user = state.get("user")
            if user:
                self.set_current_user(user)

            subj = state.get("subject")
            if subj is not None:
                self.le_subject.setText(subj)

            topic = state.get("topic")
            if topic is not None:
                self.le_topic.setText(topic)

            mode = state.get("mode")
            if mode:
                idx = self.cb_mode.findText(mode)
                if idx >= 0:
                    self.cb_mode.blockSignals(True)
                    self.cb_mode.setCurrentIndex(idx)
                    self.cb_mode.blockSignals(False)

            use_mem = state.get("use_memory")
            if use_mem is not None:
                self.chk_memory.blockSignals(True)
                self.chk_memory.setChecked(bool(use_mem))
                self.chk_memory.blockSignals(False)

            size = state.get("response_size")
            if size:
                idx2 = self.cb_size.findText(size)
                if idx2 >= 0:
                    self.cb_size.blockSignals(True)
                    self.cb_size.setCurrentIndex(idx2)
                    self.cb_size.blockSignals(False)
        except Exception:
            pass

    # ---------------- lógica interna ----------------

    def _append_bubble(self, text: str, role: str):
        idx = self.chat_layout.count() - 1
        self.chat_layout.insertWidget(idx, ChatBubble(text, role))
        QtCore.QTimer.singleShot(
            0,
            lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()),
        )

    def _on_send_clicked(self):
        text = self.txt_input.toPlainText().strip()
        if not text:
            return
        self.append_user(text)
        self.txt_input.clear()
        self.sendMessage.emit(text)

    def _toggle_panel(self):
        visible = not self.sidebar.isVisible()
        self.sidebar.setVisible(visible)
        # Si lo vuelves a mostrar, refresca usuarios
        if visible:
            self.requestUserList.emit()
            QtCore.QTimer.singleShot(0, self.le_user.setFocus)

    def _on_login_clicked(self):
        name = self.le_user.text().strip()
        if not name:
            self.le_user.setFocus()
            return
        self.changeUser.emit(name)
        self.le_user.clear()
        self.set_current_user(name)

    def _on_switch_clicked(self):
        name = self.cb_users.currentText().strip()
        if not name:
            return
        self.changeUser.emit(name)
        self.set_current_user(name)

    def _on_apply_context(self):
        subj = self.le_subject.text().strip()
        topic = self.le_topic.text().strip()
        if subj:
            self._send_system_command(f"/materia {subj}")
        if topic:
            self._send_system_command(f"/tema {topic}")

    def _on_reset_context(self):
        self.le_subject.setText("General")
        self.le_topic.setText("-")
        self._send_system_command("/materia General")
        self._send_system_command("/tema -")

    def _on_mode_changed(self, mode: str):
        # Reservado para cuando implementes comando /modo o estado en backend.
        # No hacemos side effects automáticos para que no sea “mágico”.
        pass

    def _on_memory_toggled(self, checked: bool):
        # Reservado para comando /mem on|off o state setter en backend.
        pass

    def _on_size_changed(self, size: str):
        # Reservado para comando /size corta|normal|larga o state setter en backend.
        pass

    def _send_system_command(self, cmd: str):
        """
        Envía un comando sin mostrarlo como burbuja de usuario (para que UI se vea pro).
        """
        if cmd:
            self.sendMessage.emit(cmd)
