# src/core/commands.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Literal

CommandType = Literal[
    "help",
    "set_subject",
    "set_topic",
    "quiz_start",
    "quiz_reset",
    "tool",  # /calc, /deriva, /u, etc.
]

ToolName = Literal[
    "calc",
    "wiki",
    "deriva",
    "integra",
    "limite",
    "resuelve",
    "simplifica",
    "u",
    "mm",
    "suvat",
    "stats",
    "plot",
    "analiza",
]


@dataclass(frozen=True)
class ParsedCommand:
    type: CommandType
    payload: Dict[str, Any]
    raw: str


def parse_command(text: str) -> Optional[ParsedCommand]:
    """
    Parsea comandos tipo:
      /help
      /materia Calculo
      /tema Limites laterales
      /quiz start | /quiz reset

      Tools:
      /calc 2*(3+4)^2
      /wiki Transformada de Laplace
      /deriva sin(x)^2 x
      /integra e^(2x) x
      /limite (sin(x))/x x->0 +
      /u 60 km/h -> m/s
      /mm Ca(OH)2
      /suvat u=0 a=2 t=10
      /stats 1,2,3,4
      /plot y=sin(x)+x^2 x:-2*pi:2*pi
      /analiza ```python ... ```
    Devuelve None si no es comando (no inicia con '/').
    """
    t = (text or "").strip()
    if not t.startswith("/"):
        return None

    # /help, /ayuda
    if re.match(r"^/(help|ayuda)\s*$", t, flags=re.I):
        return ParsedCommand(type="help", payload={}, raw=t)

    # /materia X
    m = re.match(r"^/materia\s+(.+)$", t, flags=re.I)
    if m:
        return ParsedCommand(
            type="set_subject",
            payload={"subject": m.group(1).strip()},
            raw=t,
        )

    # /tema X
    m = re.match(r"^/tema\s+(.+)$", t, flags=re.I)
    if m:
        return ParsedCommand(
            type="set_topic",
            payload={"topic": m.group(1).strip()},
            raw=t,
        )

    # /quiz start|reset
    m = re.match(r"^/quiz\s+(start|reset)\s*$", t, flags=re.I)
    if m:
        action = m.group(1).lower()
        return ParsedCommand(
            type="quiz_start" if action == "start" else "quiz_reset",
            payload={},
            raw=t,
        )

    # ===================== TOOLS =====================

    # /calc ...
    m = re.match(r"^/calc\s+(.+)$", t, flags=re.I)
    if m:
        return _tool("calc", {"expr": m.group(1).strip()}, t)

    # /wiki ...
    m = re.match(r"^/wiki\s+(.+)$", t, flags=re.I)
    if m:
        return _tool("wiki", {"query": m.group(1).strip(), "lang": "es"}, t)

    # /deriva expr [var]
    m = re.match(r"^/deriva\s+(.+?)(?:\s+([a-zA-Z]))?\s*$", t, flags=re.I)
    if m:
        return _tool("deriva", {"expr": m.group(1).strip(), "var": (m.group(2) or "x")}, t)

    # /integra expr [var]
    m = re.match(r"^/integra\s+(.+?)(?:\s+([a-zA-Z]))?\s*$", t, flags=re.I)
    if m:
        return _tool("integra", {"expr": m.group(1).strip(), "var": (m.group(2) or "x")}, t)

    # /limite expr <var>-><at> [+-]
    # Acepta:
    #   /limite (sin(x))/x x->0 +
    #   /limite (sin(x))/x x -> 0 +
    m = re.match(
        r"^/limite\s+(.+?)\s+([a-zA-Z])\s*->\s*([^ ]+)(?:\s+([+-]))?\s*$",
        t,
        flags=re.I,
    )
    if m:
        return _tool(
            "limite",
            {"expr": m.group(1).strip(), "var": m.group(2), "at": m.group(3), "dir": m.group(4)},
            t,
        )

    # /resuelve ...
    m = re.match(r"^/resuelve\s+(.+)$", t, flags=re.I)
    if m:
        return _tool("resuelve", {"eq": m.group(1).strip(), "var": "x"}, t)

    # /simplifica ...
    m = re.match(r"^/simplifica\s+(.+)$", t, flags=re.I)
    if m:
        return _tool("simplifica", {"expr": m.group(1).strip()}, t)

    # /u 9.81 m/s^2 -> ft/s^2
    m = re.match(r"^/u\s+(.+)$", t, flags=re.I)
    if m:
        return _tool("u", {"expr": m.group(1).strip()}, t)

    # /mm Ca(OH)2
    m = re.match(r"^/mm\s+([A-Za-z0-9()]+)\s*$", t, flags=re.I)
    if m:
        return _tool("mm", {"formula": m.group(1).strip()}, t)

    # /suvat u=0 a=2 t=10
    if t.lower().startswith("/suvat"):
        pairs = re.findall(
            r"(u|v|a|t|s)\s*=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)",
            t,
            flags=re.I,
        )
        vals = {k.lower(): float(v) for k, v in pairs}
        return _tool("suvat", {"values": vals}, t)

    # /stats 1,2,2,3,5
    m = re.match(r"^/stats\s+(.+)$", t, flags=re.I)
    if m:
        return _tool("stats", {"values": m.group(1).strip()}, t)

    # /plot y=sin(x)+x^2 x:-2*pi:2*pi
    m = re.match(r"^/plot\s+y=(.+?)\s+x:([^ ]+)\s*$", t, flags=re.I)
    if m:
        return _tool("plot", {"expr": m.group(1).strip(), "xspec": m.group(2).strip()}, t)

    # /analiza ```python ... ```
    m = re.match(r"^/analiza\s+```(?:python)?\n([\s\S]+?)\n```\s*$", t, flags=re.I)
    if m:
        return _tool("analiza", {"code": m.group(1)}, t)

    # /analiza <una línea>
    m = re.match(r"^/analiza\s+(.+)$", t, flags=re.I)
    if m:
        return _tool("analiza", {"code": m.group(1)}, t)

    # Si empieza con "/" pero no reconocemos:
    return ParsedCommand(type="help", payload={"unknown": t}, raw=t)


def _tool(name: ToolName, payload: Dict[str, Any], raw: str) -> ParsedCommand:
    return ParsedCommand(type="tool", payload={"name": name, **payload}, raw=raw)
