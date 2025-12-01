from __future__ import annotations

import json
import os
import random
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, List, Tuple

from PyQt6 import QtCore

from .commands import parse_command, ParsedCommand
from ..tools.toolkit import run_tool, autodetect_tool
from ..memory.db import MemoryDB, QuizQuestionLog


# ================================
# Configuración / Estados
# ================================

@dataclass
class SessionState:
    subject: str = "General"
    topic: str = "-"
    mode: str = "Tutor"            # Tutor | Directo | Repaso | Lab | Quiz
    use_memory: bool = True
    response_size: str = "normal"  # corta | normal | larga


@dataclass
class QuizState:
    active: bool = False
    session_id: Optional[int] = None
    q_index: int = 0  # índice actual (1..N)
    last_correct_index: Optional[int] = None
    last_question_text: str = ""
    last_options: List[str] = None

    def __post_init__(self):
        if self.last_options is None:
            self.last_options = []


# ================================
# Backend
# ================================

class Backend(QtCore.QObject):
    """
    Orquestador central:
      - Maneja comandos (/materia, /tema, tools, /quiz)
      - Decide si usar tools automáticamente
      - Llama a Gemini para responder
      - Usa MemoryDB para persistir y recuperar contexto
    """
    responseReady = QtCore.pyqtSignal(str)
    stateChanged = QtCore.pyqtSignal(dict) 

    def __init__(self, db: MemoryDB, user_name: str = "Invitado"):
        super().__init__()
        self.db = db
        self.user_name = (user_name or "").strip() or "Invitado"
        self.uid = self.db.get_or_create_user(self.user_name)

        self.state = SessionState()
        self.quiz = QuizState()

        self._api_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()

        # Modelo usado
        self._model_name = (os.getenv("GEMINI_MODEL") or "gemini-2.5-flash").strip() or "gemini-2.5-flash"

        self._debug = (os.getenv("BACKEND_DEBUG", "0").strip() == "1")

        self._genai = None
        self._configure_genai()

        self._emit_state()

    # ---------------------------
    # Helpers internos
    # ---------------------------

    @QtCore.pyqtSlot(str)
    def handle_message(self, user_text: str):
        user_text = (user_text or "").strip()
        if not user_text:
            return

        # 0) Comandos
        cmd = parse_command(user_text)
        if cmd:
            self._handle_parsed_command(cmd)
            return

        # 1) 
        auto = autodetect_tool(user_text)
        if auto:
            tool_name, payload = auto
            out = run_tool(tool_name, payload)
            self.responseReady.emit(out)

            tid = self.db.get_or_create_topic(self.state.subject, self.state.topic)
            self.db.log_doubt(self.uid, tid, user_text, out)
            return

        # 2) Quiz activo: interpretar respuesta como A/B/C/D o pedir siguiente
        if self.state.mode.lower() == "quiz" and self.quiz.active:
            qflow = self._quiz_handle_user_input(user_text)
            self.responseReady.emit(qflow)
            return

        # 3) Respuesta normal con LLM + memoria controlada
        if self.state.subject == "General":
            self.state.subject = self._guess_subject(user_text)
        if (self.state.topic or "").strip().lower() in ("-", "", "general"):
            self.state.topic = self._guess_topic(user_text)

        mem_ctx = ""
        if self.state.use_memory:
            mem_ctx = self._memory_context(self.state.subject, self.state.topic, k=3)

        answer = self._ask_gemini(user_text, mem_ctx)

        # 4) Persistir
        tid = self.db.get_or_create_topic(self.state.subject, self.state.topic)
        self.db.log_doubt(self.uid, tid, user_text, answer)

        self.responseReady.emit(answer)
        self._emit_state()

    @QtCore.pyqtSlot(str)
    def change_user(self, name: str):
        name = (name or "").strip() or "Invitado"
        self.user_name = name
        self.uid = self.db.get_or_create_user(name)

        # Restaurar último contexto si existe
        ctx = self.db.last_context_for_user(self.uid)
        if ctx:
            subj, topic, last_q = ctx
            self.state.subject = subj
            self.state.topic = topic
            msg = (
                f"Bienvenido de vuelta, **{name}**.\n"
                f"Última sesión: **{subj} / {topic}**.\n"
                f"Tu última pregunta fue: “{last_q}”."
            )
        else:
            self.state = SessionState()  # reset
            msg = (
                f"Hola, **{name}**.\n"
                "Puedes fijar contexto con:\n"
                "• `/materia Calculo`\n"
                "• `/tema Limites laterales`"
            )

        # reset quiz al cambiar usuario
        self.quiz = QuizState()

        self.responseReady.emit(msg)
        self._emit_state()

    @QtCore.pyqtSlot(str, str)
    def set_context(self, subject: str, topic: str):
        self.state.subject = (subject or "").strip() or "General"
        self.state.topic = (topic or "").strip() or "-"
        self._emit_state()
        self.responseReady.emit(
            f"Contexto actualizado → **Materia:** {self.state.subject} · **Tema:** {self.state.topic}"
        )

    @QtCore.pyqtSlot(str)
    def set_mode(self, mode: str):
        self.state.mode = (mode or "").strip() or "Tutor"
        self._emit_state()

    @QtCore.pyqtSlot(bool)
    def set_use_memory(self, value: bool):
        self.state.use_memory = bool(value)
        self._emit_state()

    @QtCore.pyqtSlot(str)
    def set_response_size(self, size: str):
        size = (size or "").strip().lower()
        self.state.response_size = (
            "corta" if size in ("corta", "short")
            else ("larga" if size in ("larga", "long") else "normal")
        )
        self._emit_state()

    @QtCore.pyqtSlot()
    def quiz_start(self):
        self._start_quiz_flow()

    @QtCore.pyqtSlot()
    def quiz_reset(self):
        self._reset_quiz_flow()

    # ---------------------------
    # Estado UI
    # ---------------------------

    def _handle_parsed_command(self, cmd: ParsedCommand):
        t = cmd.type

        if t == "help":
            self.responseReady.emit(self._help_text(cmd.payload.get("unknown")))
            return

        if t == "set_subject":
            self.state.subject = cmd.payload["subject"]
            self._emit_state()
            self.responseReady.emit(f"Materia: **{self.state.subject}**")
            return

        if t == "set_topic":
            self.state.topic = cmd.payload["topic"]
            self._emit_state()
            self.responseReady.emit(f"Tema: **{self.state.topic}**")
            return

        if t == "quiz_start":
            self._start_quiz_flow()
            return

        if t == "quiz_reset":
            self._reset_quiz_flow()
            return

        if t == "tool":
            name = cmd.payload.get("name")
            out = run_tool(name, cmd.payload)
            self.responseReady.emit(out)

            tid = self.db.get_or_create_topic(self.state.subject, self.state.topic)
            self.db.log_doubt(self.uid, tid, cmd.raw, out)
            return

        self.responseReady.emit("Comando no reconocido. Usa /help")

    def _help_text(self, unknown: Optional[str] = None) -> str:
        base = (
            "Comandos disponibles:\n"
            "• `/materia Calculo`\n"
            "• `/tema Limites laterales`\n"
            "• `/quiz start` | `/quiz reset`\n\n"
            "Tools:\n"
            "• `/calc 2*(3+4)^2`\n"
            "• `/wiki Transformada de Laplace`\n"
            "• `/deriva sin(x)^2 x`  | `/integra e^(2x) x`\n"
            "• `/limite (sin(x))/x x->0 +`\n"
            "• `/resuelve x^2-5x+6=0` | `/simplifica (x^2-1)/(x-1)`\n"
            "• `/u 60 km/h -> m/s`\n"
            "• `/mm Ca(OH)2`\n"
            "• `/suvat u=0 a=2 t=10`\n"
            "• `/stats 1,2,2,3,5`\n"
            "• `/plot y=sin(x)+x^2 x:-2*pi:2*pi`\n"
            "• `/analiza ```python ... ```\n"
        )
        if unknown:
            base = f"No entendí: `{unknown}`\n\n" + base
        return base

    # ---------------------------
    # Gemini client 
    # ---------------------------

    def _configure_genai(self):
        """
        Inicializa google-generativeai si hay API key.
        """
        if not self._api_key:
            self._genai = None
            return
        try:
            import google.generativeai as genai
            genai.configure(api_key=self._api_key)
            self._genai = genai
        except Exception:
            self._genai = None

    def _ask_gemini(self, user_text: str, memory_ctx: str) -> str:
        if not self._genai:
            return (
                " Falta API key en tu .env.\n"
                "Define una de estas:\n"
                "  GEMINI_API_KEY=...\n"
                "  (legacy) GOOGLE_API_KEY=..."
            )

        size_rules = {
            "corta": "Responde en 5–8 líneas.",
            "normal": "Responde en 10–15 líneas.",
            "larga": "Responde en 18–25 líneas (sin paja).",
        }
        size_rule = size_rules.get(self.state.response_size, size_rules["normal"])

        mode_rules = {
            "tutor": (
                "Eres un profesor asesor. Explica paso a paso. "
                "Si es numérico: fórmula → sustitución con unidades → resultado. "
                "Si faltan datos, pide solo lo indispensable."
            ),
            "directo": "Da la respuesta directa y luego 2–4 líneas de verificación.",
            "repaso": "Primero da una definición corta, luego 1 ejemplo mínimo, luego 3 preguntas de auto-chequeo.",
            "lab": "Actúa como guía de laboratorio: procedimiento, supuestos, y qué medir. Evita teoría larga.",
            "quiz": "No expliques de más: haz preguntas tipo examen y corrige.",
        }
        mode_rule = mode_rules.get(self.state.mode.lower(), mode_rules["tutor"])

        prompt = (
            "Eres profesor asesor de ciencias básicas de ingeniería.\n"
            "Sé claro, preciso y útil.\n"
            f"{mode_rule}\n"
            f"{size_rule}\n\n"
            f"Estudiante: {self.user_name}\n"
            f"Materia: {self.state.subject}\n"
            f"Tema: {self.state.topic}\n\n"
            "Memoria (últimas interacciones relevantes):\n"
            f"{memory_ctx or '—'}\n\n"
            "Pregunta:\n"
            f"{user_text}\n"
        )

        try:
            generation_config = {
                "temperature": 0.2,
                "top_p": 0.9,
                "top_k": 40,
                "max_output_tokens": 700,
            }
            model = self._genai.GenerativeModel(self._model_name, generation_config=generation_config)
            resp = model.generate_content(prompt)

            text = self._extract_text_from_response(resp)
            if text:
                return text

            reason = self._extract_finish_reason(resp)
            if reason:
                return (
                    f"No pude generar texto con el modelo (**{self._model_name}**).\n"
                    f"Motivo (finish_reason): {reason}\n"
                    "Tip: prueba con un prompt más específico o cambia GEMINI_MODEL en .env."
                )

            return "No pude generar una respuesta clara. Intenta reformular tu pregunta."
        except Exception as e:
            return (
                f"No pude consultar el modelo (**{self._model_name}**). "
                "Verifica tu API key y el nombre del modelo.\n"
                f"Detalle técnico: {e}"
            )

    def _extract_text_from_response(self, resp: Any) -> str:
        """
        Extracción robusta:
        - Evita depender de resp.text cuando no hay Parts válidos
        - Lee candidates[*].content.parts[*].text
        """
        try:
            txt = getattr(resp, "text", None)
            if isinstance(txt, str) and txt.strip():
                return txt.strip()
        except Exception:
            pass

        try:
            cands = getattr(resp, "candidates", None)
            if not cands:
                return ""
            chunks: List[str] = []
            for cand in cands:
                content = getattr(cand, "content", None)
                parts = getattr(content, "parts", None) if content else None
                if not parts:
                    continue
                for p in parts:
                    t = getattr(p, "text", None)
                    if isinstance(t, str) and t.strip():
                        chunks.append(t.strip())
            return "\n".join(chunks).strip()
        except Exception:
            return ""

    def _extract_finish_reason(self, resp: Any) -> str:
        try:
            cands = getattr(resp, "candidates", None)
            if not cands:
                return ""
            reasons = []
            for cand in cands:
                r = getattr(cand, "finish_reason", None)
                if r is None:
                    continue
                reasons.append(str(r))
            return ", ".join(reasons)
        except Exception:
            return ""

    # ---------------------------
    # Memoria
    # ---------------------------

    def _memory_context(self, subject: str, topic: str, k: int = 3) -> str:
        tid = self.db.get_or_create_topic(subject, topic or "-")
        rows = self.db.recent_doubts(self.uid, tid, limit=k)
        if not rows:
            return ""
        chunks = []
        for ts, q, a in rows:
            a1 = (a or "").replace("\n", " ").strip()
            if len(a1) > 280:
                a1 = a1[:277] + "..."
            chunks.append(f"- [{ts}] P: {q}\n  R: {a1}")
        return "\n".join(chunks)

    # ---------------------------
    # Quiz flow
    # ---------------------------

    def _start_quiz_flow(self):
        # set mode quiz
        self.state.mode = "Quiz"
        self.quiz.active = True
        self.quiz.q_index = 0
        self.quiz.last_correct_index = None
        self.quiz.last_question_text = ""
        self.quiz.last_options = []

        tid = self.db.get_or_create_topic(self.state.subject, self.state.topic)
        self.quiz.session_id = self.db.start_quiz_session(
            user_id=self.uid,
            topic_id=tid,
            difficulty=self.state.response_size,  # corta/normal/larga
            n_questions=10,
        )

        qtxt = self._quiz_generate_next_question()
        self.responseReady.emit(qtxt)
        self._emit_state()

    def _reset_quiz_flow(self):
        if self.quiz.session_id:
            try:
                self.db.finish_quiz_session(self.quiz.session_id)
            except Exception:
                pass
        self.quiz = QuizState()
        self.state.mode = "Tutor"
        self._emit_state()
        self.responseReady.emit("Quiz reiniciado. Si quieres empezar: `/quiz start`")

    def _quiz_handle_user_input(self, user_text: str) -> str:
        t = (user_text or "").strip().lower()

        if t in ("siguiente", "otra", "next"):
            return self._quiz_generate_next_question()

        ans = self._parse_choice(t)
        if ans is None:
            return (
                "Responde con **A, B, C o D** (o escribe **siguiente**).\n"
                "Ejemplo: `B`"
            )

        if self.quiz.last_correct_index is None or not self.quiz.last_question_text:
            return "No tengo una pregunta activa. Escribe **siguiente**."

        is_correct = (ans == self.quiz.last_correct_index)
        correct_letter = "ABCD"[self.quiz.last_correct_index]
        your_letter = "ABCD"[ans]

        if self.quiz.session_id is not None:
            self.db.update_quiz_answer(
                session_id=self.quiz.session_id,
                q_index=self.quiz.q_index,
                user_answer_index=ans,
                is_correct=is_correct,
                explanation="",
            )

        feedback = "Correcto." if is_correct else f"Incorrecto. La correcta era **{correct_letter}**."
        return f"{feedback}\nTu respuesta: **{your_letter}**.\nEscribe **siguiente** para otra pregunta."

    def _parse_choice(self, t: str) -> Optional[int]:
        t = t.strip().upper()
        if t in ("A", "B", "C", "D"):
            return "ABCD".index(t)
        if t in ("1", "2", "3", "4"):
            return int(t) - 1
        return None

    def _quiz_generate_next_question(self) -> str:
        if not self.quiz.session_id:
            return " No pude iniciar quiz (session_id vacío). Usa `/quiz start`."
        if not self.quiz.active:
            return "Quiz no está activo. Usa `/quiz start`."

        # Importante: NO incrementamos q_index hasta que tengamos pregunta válida.
        next_idx = self.quiz.q_index + 1

        payload, meta = self._ask_quiz_payload(next_idx)

        if not payload:
            # Si Gemini falló, hacemos fallback local (para que SIEMPRE funcione el quiz)
            payload = self._fallback_quiz_payload(next_idx)

        question = str(payload.get("question", "")).strip()
        options = payload.get("options", [])
        correct_index = payload.get("correct_index", None)

        if not question or not isinstance(options, list) or len(options) != 4 or correct_index not in (0, 1, 2, 3):
            # Si incluso el fallback vino mal (muy raro), NO avanzamos el contador.
            if self._debug:
                self._dbg(f"[quiz] payload inválido: {payload} meta={meta}")
            return "No pude generar una pregunta válida. Escribe **siguiente** para reintentar."

        # Ahora sí: fijamos índice actual
        self.quiz.q_index = next_idx
        self.quiz.last_question_text = question
        self.quiz.last_options = [str(x) for x in options]
        self.quiz.last_correct_index = int(correct_index)

        # Log en DB
        self.db.log_quiz_question(
            session_id=self.quiz.session_id,
            q=QuizQuestionLog(
                idx=self.quiz.q_index,
                question=question,
                options=self.quiz.last_options,
                correct_index=self.quiz.last_correct_index,
                user_answer_index=None,
                is_correct=None,
                explanation=str(payload.get("explanation", "") or ""),
            ),
        )

        a, b, c, d = self.quiz.last_options
        return (
            f"📝 **Quiz #{self.quiz.q_index}**  ({self.state.subject} · {self.state.topic})\n\n"
            f"**{question}**\n\n"
            f"A) {a}\n"
            f"B) {b}\n"
            f"C) {c}\n"
            f"D) {d}\n\n"
            "Responde con **A/B/C/D**."
        )

    def _ask_quiz_payload(self, next_idx: int) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        """
        Intenta obtener pregunta desde Gemini en JSON estricto.
        Si falla el parseo, hace 1 intento de “reparación a JSON”.
        Devuelve: (payload|None, meta_debug)
        """
        meta: Dict[str, Any] = {"source": "gemini", "finish_reason": "", "raw_preview": ""}

        if not self._genai:
            meta["source"] = "no_genai"
            return None, meta

        size = "normal" if self.state.response_size not in ("corta", "larga") else self.state.response_size
        difficulty_hint = {"corta": "fácil", "normal": "media", "larga": "difícil"}.get(size, "media")

        # Semilla suave para variación (sin meter prompts enormes)
        seed = f"{self.user_name}:{self.state.subject}:{self.state.topic}:{self.quiz.session_id}:{next_idx}"

        prompt = (
            "Devuelve SOLO un JSON válido (sin markdown, sin texto extra).\n"
            "Esquema:\n"
            "{\"question\":\"...\",\"options\":[\"...\",\"...\",\"...\",\"...\"],\"correct_index\":2,\"explanation\":\"...\"}\n\n"
            f"Materia: {self.state.subject}\n"
            f"Tema: {self.state.topic}\n"
            f"Dificultad: {difficulty_hint}\n"
            f"Seed: {seed}\n\n"
            "Reglas:\n"
            "- options EXACTAMENTE 4 strings\n"
            "- correct_index 0..3\n"
            "- explanation 1–2 líneas\n"
        )

        try:
            generation_config = {
                "temperature": 0.35,
                "top_p": 0.9,
                "top_k": 40,
                "max_output_tokens": 420,  # un poco más para evitar truncado de JSON
            }
            model = self._genai.GenerativeModel(self._model_name, generation_config=generation_config)
            resp = model.generate_content(prompt)

            meta["finish_reason"] = self._extract_finish_reason(resp) or ""
            text = self._extract_text_from_response(resp)
            meta["raw_preview"] = (text or "")[:260].replace("\n", " ")

            data = self._extract_json_object(text)
            if isinstance(data, dict) and self._validate_quiz_payload(data):
                return data, meta

            # 2) intento “reparar a JSON”
            if text:
                repaired = self._repair_to_quiz_json(text, difficulty_hint=difficulty_hint)
                meta["raw_preview"] = (repaired or meta["raw_preview"])[:260].replace("\n", " ")
                data2 = self._extract_json_object(repaired)
                if isinstance(data2, dict) and self._validate_quiz_payload(data2):
                    meta["source"] = "gemini_repaired"
                    return data2, meta

            return None, meta
        except Exception as e:
            meta["source"] = "gemini_error"
            meta["error"] = str(e)
            return None, meta

    def _validate_quiz_payload(self, d: Dict[str, Any]) -> bool:
        try:
            q = str(d.get("question", "")).strip()
            opts = d.get("options", [])
            ci = d.get("correct_index", None)
            if not q:
                return False
            if not isinstance(opts, list) or len(opts) != 4:
                return False
            if ci not in (0, 1, 2, 3):
                return False
            # Asegurar strings
            for o in opts:
                if not str(o).strip():
                    return False
            return True
        except Exception:
            return False

    def _repair_to_quiz_json(self, raw_text: str, *, difficulty_hint: str) -> str:
        """
        Convierte cualquier salida mediocre a JSON válido (2do intento corto y rígido).
        """
        if not self._genai:
            return raw_text

        prompt = (
            "Convierte el siguiente texto en UN SOLO JSON válido del esquema:\n"
            "{\"question\":\"...\",\"options\":[\"...\",\"...\",\"...\",\"...\"],\"correct_index\":2,\"explanation\":\"...\"}\n\n"
            "Reglas:\n"
            "- Devuelve SOLO JSON\n"
            "- options EXACTAMENTE 4\n"
            "- correct_index 0..3\n"
            "- explanation 1–2 líneas\n\n"
            f"Dificultad: {difficulty_hint}\n\n"
            "Texto:\n"
            f"{raw_text}\n"
        )

        try:
            generation_config = {
                "temperature": 0.0,
                "top_p": 1.0,
                "top_k": 1,
                "max_output_tokens": 420,
            }
            model = self._genai.GenerativeModel(self._model_name, generation_config=generation_config)
            resp = model.generate_content(prompt)
            return self._extract_text_from_response(resp) or raw_text
        except Exception:
            return raw_text

    def _extract_json_object(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Extrae el primer objeto JSON {...} del texto.
        Mucho más tolerante (quita ```json, espacios, etc.)
        """
        if not text:
            return None

        t = text.strip()

        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.I).strip()
        t = re.sub(r"\s*```$", "", t).strip()

        # intento directo
        try:
            obj = json.loads(t)
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass

        # buscar primer {...}
        m = re.search(r"\{[\s\S]*\}", t)
        if not m:
            return None

        candidate = m.group(0).strip()

        # segundo intento
        try:
            obj = json.loads(candidate)
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None

    # ---------------------------
    # Fallback local (para que Quiz nunca falle)
    # ---------------------------

    def _fallback_quiz_payload(self, next_idx: int) -> Dict[str, Any]:
        """
        Genera una pregunta “determinística” local cuando Gemini falla.
        (No depende de internet, ni de formato del modelo.)
        """
        # semilla estable por sesión/pregunta
        seed_val = f"{self.quiz.session_id}:{next_idx}:{self.state.subject}:{self.state.topic}".encode("utf-8")
        rnd = random.Random(seed_val)

        subj = (self.state.subject or "General").lower()

        if "cálculo" in subj or "calculo" in subj:
            a = rnd.randint(1, 6)
            b = rnd.randint(0, 8)
            n = rnd.choice([2, 3, 4])
            question = f"Deriva: f(x) = {a}x^{n} + {b}x"
            correct = f"{a*n}x^{n-1} + {b}"
            wrong1 = f"{a*n}x^{n+1} + {b}"
            wrong2 = f"{a}x^{n-1} + {b}"
            wrong3 = f"{a*n}x^{n-1} - {b}"
            options = [correct, wrong1, wrong2, wrong3]
            correct_index = 0

        elif "álgebra" in subj or "algebra" in subj:
            x = rnd.randint(-3, 4)
            y = rnd.randint(-3, 4)
            z = rnd.randint(-3, 4)
            question = f"Calcula el producto punto: v·w si v=({x},{y}) y w=({y},{z})."
            correct_val = x*y + y*z
            options = [str(correct_val), str(correct_val + 2), str(correct_val - 3), str(correct_val + 5)]
            correct_index = 0

        elif "física" in subj or "fisica" in subj:
            u = rnd.randint(0, 10)
            a = rnd.randint(1, 5)
            t = rnd.randint(2, 8)
            v = u + a * t
            question = f"Movimiento uniformemente acelerado: si u={u} m/s, a={a} m/s² y t={t} s, ¿cuál es v?"
            options = [f"{v} m/s", f"{v+a} m/s", f"{max(0, v-a)} m/s", f"{v+t} m/s"]
            correct_index = 0

        elif "probabilidad" in subj or "estad" in subj:
            data = [rnd.randint(1, 9) for _ in range(5)]
            mean = sum(data) / len(data)
            question = f"¿Cuál es la media de los datos {data}?"
            options = [f"{mean:.2f}", f"{(mean+1):.2f}", f"{(mean-1):.2f}", f"{(mean+0.5):.2f}"]
            correct_index = 0

        elif "química" in subj or "quimica" in subj:
            # estequiometría básica
            question = "¿Cuántos moles hay en 18 g de H₂O? (M(H₂O)=18 g/mol)"
            options = ["1 mol", "0.5 mol", "2 mol", "18 mol"]
            correct_index = 0

        else:
            # General
            question = "¿Cuál de estas opciones describe mejor una derivada?"
            options = [
                "Tasa de cambio instantánea",
                "Área bajo la curva",
                "Promedio de un conjunto de datos",
                "Producto cruz entre vectores",
            ]
            correct_index = 0

        # Mezclar opciones manteniendo índice correcto
        pairs = list(enumerate(options))
        rnd.shuffle(pairs)
        new_options = [p[1] for p in pairs]
        new_correct_index = [i for i, p in enumerate(pairs) if p[0] == correct_index][0]

        return {
            "question": question,
            "options": new_options,
            "correct_index": new_correct_index,
            "explanation": "Generado localmente (respaldo) por fallo de la IA.",
        }

    # ---------------------------
    # Guessing simple (si no se fija contexto)
    # ---------------------------

    def _guess_subject(self, text: str) -> str:
        t = text.lower()
        if any(w in t for w in ["deriv", "integral", "límite", "limite", "serie", "teorema fundamental"]):
            return "Cálculo"
        if any(w in t for w in ["matriz", "vector", "autovalor", "autovector", "diagonalizar"]):
            return "Álgebra Lineal"
        if any(w in t for w in ["fuerza", "velocidad", "aceleración", "aceleracion", "newton", "circuito", "ohm", "voltaje"]):
            return "Física"
        if any(w in t for w in ["mol", "reacción", "reaccion", "estequiometría", "estequiometria", "ácido", "acido", "base", "ph"]):
            return "Química"
        if any(w in t for w in ["probabilidad", "estadística", "estadistica", "media", "varianza", "distribución", "distribucion"]):
            return "Probabilidad y Estadística"
        if any(w in t for w in ["programación", "programacion", "código", "codigo", "algoritmo", "complejidad", "python"]):
            return "Programación"
        return "General"

    def _guess_topic(self, text: str) -> str:
        keys = [
            "límite", "limite", "derivada", "integral", "series",
            "matriz", "vector", "autovalor", "autovector",
            "ley de ohm", "segunda ley de newton",
            "ph", "estequiometría", "estequiometria",
            "distribución normal", "distribucion normal", "varianza", "regresión", "regresion",
            "complejidad", "algoritmo",
        ]
        t = text.lower()
        for k in keys:
            if k in t:
                return k
        return " ".join(text.split()[:5]).strip() or "general"

    # ---------------------------
    # Emitir estado UI
    # ---------------------------

    def _emit_state(self):
        try:
            self.stateChanged.emit(
                {
                    "user": self.user_name,
                    "subject": self.state.subject,
                    "topic": self.state.topic,
                    "mode": self.state.mode,
                    "use_memory": self.state.use_memory,
                    "response_size": self.state.response_size,
                    "quiz_active": self.quiz.active,
                }
            )
        except Exception:
            pass

    # ---------------------------
    # Debug
    # ---------------------------

    def _dbg(self, msg: str):
        if self._debug:
            try:
                print(msg)
            except Exception:
                pass
