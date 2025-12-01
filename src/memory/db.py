from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_DB_PATH = "asesor_memoria.sqlite3"


@dataclass
class QuizQuestionLog:
    idx: int
    question: str
    options: List[str]
    correct_index: int
    user_answer_index: Optional[int]
    is_correct: Optional[bool]
    explanation: str


class MemoryDB:
    """
    Persistencia SQLite:
      - users (estudiantes)
      - topics (materia + tema)
      - doubts (Q&A por usuario y tema)
      - quiz_sessions, quiz_questions (práctica evaluable)
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._init_db()

    # -------------------------- DB init / connection --------------------------

    def _conn(self) -> sqlite3.Connection:
        # check_same_thread=False por si lo usas desde QThread
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _init_db(self):
        conn = self._conn()
        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            topic TEXT NOT NULL,
            UNIQUE(subject, topic)
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS doubts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            topic_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(topic_id) REFERENCES topics(id)
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS quiz_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            topic_id INTEGER NOT NULL,
            difficulty TEXT NOT NULL,
            n_questions INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(topic_id) REFERENCES topics(id)
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS quiz_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            q_index INTEGER NOT NULL,
            question TEXT NOT NULL,
            options_json TEXT NOT NULL,
            correct_index INTEGER NOT NULL,
            user_answer_index INTEGER,
            is_correct INTEGER,
            explanation TEXT,
            FOREIGN KEY(session_id) REFERENCES quiz_sessions(id)
        );
        """)

        # Índices
        cur.execute("CREATE INDEX IF NOT EXISTS idx_doubts_user ON doubts(user_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_doubts_topic ON doubts(topic_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_quiz_sess_user_topic ON quiz_sessions(user_id, topic_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_quiz_q_session ON quiz_questions(session_id);")

        conn.commit()
        conn.close()

    # ------------------------------ Users / Topics ------------------------------

    def get_or_create_user(self, name: str) -> int:
        name = (name or "").strip() or "Invitado"
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE name=?;", (name,))
        row = cur.fetchone()
        if row:
            uid = int(row[0])
        else:
            cur.execute("INSERT INTO users (name) VALUES (?);", (name,))
            conn.commit()
            uid = int(cur.lastrowid)
        conn.close()
        return uid

    def get_user_id(self, name: str) -> Optional[int]:
        name = (name or "").strip()
        if not name:
            return None
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE name=?;", (name,))
        row = cur.fetchone()
        conn.close()
        return int(row[0]) if row else None

    def list_users(self) -> List[str]:
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("SELECT name FROM users ORDER BY LOWER(name) ASC;")
        rows = [r[0] for r in cur.fetchall()]
        conn.close()
        return rows

    def rename_user(self, old_name: str, new_name: str) -> bool:
        old_name = (old_name or "").strip()
        new_name = (new_name or "").strip()
        if not old_name or not new_name:
            return False
        conn = self._conn()
        cur = conn.cursor()
        try:
            cur.execute("UPDATE users SET name=? WHERE name=?;", (new_name, old_name))
            conn.commit()
            ok = cur.rowcount > 0
            return ok
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def delete_user(self, name: str) -> bool:
        """
        Elimina solo el usuario (mantiene dudas/quizzes para auditoría/historial).
        """
        name = (name or "").strip()
        if not name:
            return False
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE name=?;", (name,))
        conn.commit()
        deleted = cur.rowcount > 0
        conn.close()
        return deleted

    def get_or_create_topic(self, subject: str, topic: str) -> int:
        subject = (subject or "").strip() or "General"
        topic = (topic or "").strip() or "-"
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("SELECT id FROM topics WHERE subject=? AND topic=?;", (subject, topic))
        row = cur.fetchone()
        if row:
            tid = int(row[0])
        else:
            cur.execute("INSERT INTO topics (subject, topic) VALUES (?, ?);", (subject, topic))
            conn.commit()
            tid = int(cur.lastrowid)
        conn.close()
        return tid

    # ---------------------------------- Doubts ----------------------------------

    def log_doubt(self, user_id: int, topic_id: int, question: str, answer: str) -> int:
        conn = self._conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO doubts (user_id, topic_id, question, answer, timestamp)
            VALUES (?, ?, ?, ?, ?);
            """,
            (user_id, topic_id, question or "", answer or "", datetime.utcnow().isoformat()),
        )
        conn.commit()
        did = int(cur.lastrowid)
        conn.close()
        return did

    def recent_doubts(self, user_id: int, topic_id: int, limit: int = 10) -> List[Tuple[str, str, str]]:
        conn = self._conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT timestamp, question, answer
            FROM doubts
            WHERE user_id=? AND topic_id=?
            ORDER BY timestamp DESC
            LIMIT ?;
            """,
            (user_id, topic_id, int(limit)),
        )
        rows = cur.fetchall()
        conn.close()
        return [(str(ts), str(q), str(a)) for (ts, q, a) in rows]

    def last_context_for_user(self, user_id: int) -> Optional[Tuple[str, str, str]]:
        """
        Devuelve (subject, topic, last_question) de la última duda del usuario.
        """
        conn = self._conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT t.subject, t.topic, d.question
            FROM doubts d
            JOIN topics t ON t.id = d.topic_id
            WHERE d.user_id=?
            ORDER BY d.timestamp DESC
            LIMIT 1;
            """,
            (user_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return str(row[0]), str(row[1]), str(row[2])
        return None

    # ---------------------------------- Quizzes ----------------------------------

    def start_quiz_session(self, user_id: int, topic_id: int, difficulty: str, n_questions: int) -> int:
        difficulty = (difficulty or "").strip() or "normal"
        conn = self._conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO quiz_sessions (user_id, topic_id, difficulty, n_questions, started_at)
            VALUES (?, ?, ?, ?, ?);
            """,
            (user_id, topic_id, difficulty, int(n_questions), datetime.utcnow().isoformat()),
        )
        conn.commit()
        sid = int(cur.lastrowid)
        conn.close()
        return sid

    def finish_quiz_session(self, session_id: int):
        conn = self._conn()
        cur = conn.cursor()
        cur.execute(
            "UPDATE quiz_sessions SET finished_at=? WHERE id=?;",
            (datetime.utcnow().isoformat(), int(session_id)),
        )
        conn.commit()
        conn.close()

    def log_quiz_question(self, session_id: int, q: QuizQuestionLog) -> int:
        conn = self._conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO quiz_questions
            (session_id, q_index, question, options_json, correct_index,
             user_answer_index, is_correct, explanation)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                int(session_id),
                int(q.idx),
                q.question or "",
                json.dumps(q.options or [], ensure_ascii=False),
                int(q.correct_index),
                int(q.user_answer_index) if q.user_answer_index is not None else None,
                1 if q.is_correct is True else (0 if q.is_correct is False else None),
                q.explanation or "",
            ),
        )
        conn.commit()
        qid = int(cur.lastrowid)
        conn.close()
        return qid

    def update_quiz_answer(
        self,
        session_id: int,
        q_index: int,
        user_answer_index: int,
        is_correct: bool,
        explanation: str = "",
    ) -> bool:
        conn = self._conn()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE quiz_questions
            SET user_answer_index=?, is_correct=?, explanation=COALESCE(NULLIF(?, ''), explanation)
            WHERE session_id=? AND q_index=?;
            """,
            (
                int(user_answer_index),
                1 if is_correct else 0,
                explanation or "",
                int(session_id),
                int(q_index),
            ),
        )
        conn.commit()
        ok = cur.rowcount > 0
        conn.close()
        return ok

    def topic_stats(self, user_id: int, topic_id: int) -> Dict[str, Any]:
        """
        Totales y exactitud (accuracy histórico) del tema basado en quiz_questions.
        """
        conn = self._conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*), SUM(is_correct)
            FROM quiz_questions
            WHERE session_id IN (
                SELECT id FROM quiz_sessions WHERE user_id=? AND topic_id=?
            );
            """,
            (int(user_id), int(topic_id)),
        )
        total, correct = cur.fetchone()
        conn.close()

        total = int(total or 0)
        correct = int(correct or 0)
        acc = (correct / total * 100.0) if total > 0 else 0.0
        return {"total": total, "correct": correct, "accuracy": acc}

    def progress_blocks(self, user_id: int, topic_id: int, block_size: int = 5) -> List[Tuple[int, float]]:
        """
        Accuracy por bloques de N preguntas, en orden cronológico.
        Devuelve [(bloque, accuracy%), ...]
        """
        conn = self._conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT q.is_correct
            FROM quiz_questions q
            JOIN quiz_sessions s ON s.id = q.session_id
            WHERE s.user_id=? AND s.topic_id=?
            ORDER BY s.started_at ASC, q.q_index ASC;
            """,
            (int(user_id), int(topic_id)),
        )
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return []

        values = []
        for (v,) in rows:
            if v is None:
                values.append(0)  #
            else:
                values.append(int(v))

        out: List[Tuple[int, float]] = []
        b = 1
        bs = max(1, int(block_size))
        for i in range(0, len(values), bs):
            chunk = values[i : i + bs]
            acc = (sum(chunk) / len(chunk) * 100.0) if chunk else 0.0
            out.append((b, acc))
            b += 1
        return out
