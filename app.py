from __future__ import annotations

import sys
from PyQt6 import QtCore, QtWidgets
from dotenv import load_dotenv

from src.ui.chat_window import ChatWindow
from src.core.backend import Backend
from src.memory.db import MemoryDB


def main() -> int:
    load_dotenv()

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Profesor Asesor — Asistente (Gemini + SQLite)")

    # ===== Instancias principales =====
    db = MemoryDB()
    win = ChatWindow(title="Profesor Asesor — Asistente")

    # Mensaje de bienvenida (UI)
    win.append_assistant(
        "¡Bienvenido! Soy tu **Profesor Asesor**.\n\n"
        "Sugerencias rápidas:\n"
        "• Fija contexto con el panel: **Materia** y **Tema**\n"
        "• Comandos: `/help`, `/materia ...`, `/tema ...`, `/quiz start`\n"
        "• Tools: `/calc`, `/deriva`, `/u`, `/mm`, etc.\n\n"
        "Tip: En **Quiz**, responde **A/B/C/D** o escribe **siguiente**."
    )

    # ===== Backend en hilo =====
    thread = QtCore.QThread()
    backend = Backend(db=db, user_name="Invitado")
    backend.moveToThread(thread)

    # ===== Conexiones Chat =====
    win.sendMessage.connect(backend.handle_message)
    backend.responseReady.connect(win.append_assistant)

    # Sync estado backend -> UI (modo, materia, tema, etc.)
    backend.stateChanged.connect(win.apply_state)

    # ===== Conexiones Usuario =====
    win.changeUser.connect(backend.change_user)
    win.requestUserList.connect(lambda: win.set_users(db.list_users()))

    # Estado inicial UI
    win.set_current_user("Invitado")
    win.set_users(db.list_users())

    # ===== Shutdown limpio =====
    def _shutdown():
        thread.quit()
        thread.wait(1500)

    app.aboutToQuit.connect(_shutdown)

    thread.start()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
