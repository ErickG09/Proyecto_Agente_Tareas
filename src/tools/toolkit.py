from __future__ import annotations

import ast
import math
import operator as op
import os
import re
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt

import requests
import sympy as sp
import pint


# =============================================================================
# 1) CALCULADORA SEGURA (aritmética)
# =============================================================================

_ALLOWED = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Mod: op.mod,
    ast.Pow: op.pow,
    ast.USub: op.neg,
    ast.UAdd: op.pos,
}


def _eval_ast_numexpr(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise ValueError("Constante no numérica.")
    if isinstance(node, ast.BinOp):
        fn = _ALLOWED.get(type(node.op))
        if not fn:
            raise ValueError("Operador no permitido.")
        return float(fn(_eval_ast_numexpr(node.left), _eval_ast_numexpr(node.right)))
    if isinstance(node, ast.UnaryOp):
        fn = _ALLOWED.get(type(node.op))
        if not fn:
            raise ValueError("Operador unario no permitido.")
        return float(fn(_eval_ast_numexpr(node.operand)))
    if isinstance(node, ast.Expr):
        return _eval_ast_numexpr(node.value)
    raise ValueError("Expresión no permitida.")


def calc(expr: str) -> str:
    expr = (expr or "").replace("^", "**").strip()
    if not expr:
        return "Uso: /calc 2*(3+4)^2"
    try:
        node = ast.parse(expr, mode="eval")
        val = _eval_ast_numexpr(node.body)
        v = float(f"{val:.10g}")
        return f"Resultado: **{v}**"
    except Exception as e:
        return f"No pude evaluar la expresión. Detalle: {e}"


# =============================================================================
# 2) WIKIPEDIA (primer resumen)
# =============================================================================

def wiki(query: str, lang: str = "es") -> str:
    query = (query or "").strip()
    if not query:
        return "Uso: /wiki Transformada de Laplace"
    try:
        s = requests.get(
            f"https://{lang}.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "utf8": "1",
                "format": "json",
                "srlimit": 1,
            },
            timeout=10,
        ).json()
        hits = s.get("query", {}).get("search", [])
        if not hits:
            return "No encontré resultados en Wikipedia."

        title = hits[0]["title"]
        p = requests.get(
            f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}",
            timeout=10,
        ).json()
        extract = p.get("extract") or "(sin extracto)"
        url = p.get("content_urls", {}).get("desktop", {}).get("page", "")

        out = f"**{title}** — {extract}"
        if url:
            out += f"\n\nEnlace: {url}"
        return out
    except Exception as e:
        return f"Error al consultar Wikipedia: {e}"


# =============================================================================
# 3) CÁLCULO SIMBÓLICO (SymPy)
# =============================================================================

def _sympify_expr(expr: str, var: str = "x") -> Tuple[sp.Expr, sp.Symbol]:
    x = sp.symbols(var)
    expr = (expr or "").replace("^", "**")
    return sp.sympify(expr, convert_xor=True), x


def deriva(expr: str, var: str = "x") -> str:
    try:
        f, x = _sympify_expr(expr, var)
        df = sp.diff(f, x)
        return f"d/d{var} {sp.simplify(f)} = **{sp.simplify(df)}**"
    except Exception as e:
        return f"Error al derivar: {e}"


def integra(expr: str, var: str = "x") -> str:
    try:
        f, x = _sympify_expr(expr, var)
        F = sp.integrate(f, x)
        return f"∫ {sp.simplify(f)} d{var} = **{sp.simplify(F)} + C**"
    except Exception as e:
        return f"Error al integrar: {e}"


def limite(expr: str, var: str = "x", at: str = "0", direction: Optional[str] = None) -> str:
    try:
        f, x = _sympify_expr(expr, var)
        a = sp.sympify(at)
        lim = sp.limit(f, x, a, dir=direction if direction in ("+", "-") else None)
        dir_txt = {"+" : "⁺", "-" : "⁻"}.get(direction, "")
        return f"lim{dir_txt}_{{{var}→{a}}} {sp.simplify(f)} = **{sp.simplify(lim)}**"
    except Exception as e:
        return f"Error al calcular el límite: {e}"


def resuelve(eq: str, var: str = "x") -> str:
    try:
        x = sp.symbols(var)
        s = (eq or "").replace("^", "**").strip()
        if not s:
            return "Uso: /resuelve x^2-4=0"
        if "=" in s:
            left, right = s.split("=", 1)
            sol = sp.solve(sp.Eq(sp.sympify(left), sp.sympify(right)), x)
        else:
            sol = sp.solve(sp.sympify(s), x)
        return f"Soluciones en {var}: **{sol}**"
    except Exception as e:
        return f"Error al resolver: {e}"


def simplifica(expr: str) -> str:
    try:
        f = sp.sympify((expr or "").replace("^", "**"))
        return f"Simplificado: **{sp.simplify(f)}**"
    except Exception as e:
        return f"Error al simplificar: {e}"


# =============================================================================
# 4) UNIDADES (pint)
# =============================================================================

_ureg = pint.UnitRegistry()
_ureg.default_format = "~P"


def convierte(expr: str) -> str:
    try:
        s = (expr or "").strip()
        if "->" not in s:
            return "Uso: /u 60 km/h -> m/s"
        left, right = s.split("->", 1)
        q = _ureg(left.strip())
        q_to = q.to(right.strip())
        return f"{q} = **{q_to}**"
    except Exception as e:
        return f"Error en conversión de unidades: {e}"


# =============================================================================
# 5) QUÍMICA: MASA MOLAR (fórmulas sencillas con paréntesis)
# =============================================================================

_ATOMIC_MASS: Dict[str, float] = {
    "H": 1.008, "He": 4.0026, "Li": 6.94, "Be": 9.0122, "B": 10.81,
    "C": 12.011, "N": 14.007, "O": 15.999, "F": 18.998, "Ne": 20.180,
    "Na": 22.990, "Mg": 24.305, "Al": 26.982, "Si": 28.085, "P": 30.974,
    "S": 32.06, "Cl": 35.45, "Ar": 39.948,
    "K": 39.098, "Ca": 40.078, "Sc": 44.956, "Ti": 47.867, "V": 50.942,
    "Cr": 51.996, "Mn": 54.938, "Fe": 55.845, "Co": 58.933, "Ni": 58.693,
    "Cu": 63.546, "Zn": 65.38, "Br": 79.904, "Ag": 107.868, "I": 126.904, "Ba": 137.327,
    "Sr": 87.62, "Sn": 118.71, "Pb": 207.2, "Hg": 200.59
}


class _Tok:
    def __init__(self, type_: str, value: str):
        self.type = type_
        self.value = value


def _tokenize_formula(s: str) -> List[_Tok]:
    tokens: List[_Tok] = []
    i = 0
    while i < len(s):
        c = s[i]
        if c.isspace():
            i += 1
            continue
        if c == "(":
            tokens.append(_Tok("LP", "(")); i += 1; continue
        if c == ")":
            tokens.append(_Tok("RP", ")")); i += 1; continue
        if c.isdigit():
            j = i
            while j < len(s) and s[j].isdigit():
                j += 1
            tokens.append(_Tok("NUM", s[i:j])); i = j; continue
        if c.isalpha():
            j = i + 1
            if j < len(s) and s[j].islower():
                j += 1
            tokens.append(_Tok("EL", s[i:j])); i = j; continue
        raise ValueError(f"Símbolo no válido en fórmula: '{c}'")
    return tokens


def _parse_group(tokens: List[_Tok], pos: int = 0) -> Tuple[Dict[str, int], int]:
    counts: Dict[str, int] = {}
    i = pos
    while i < len(tokens):
        t = tokens[i]
        if t.type == "EL":
            elem = t.value
            i += 1
            mult = 1
            if i < len(tokens) and tokens[i].type == "NUM":
                mult = int(tokens[i].value); i += 1
            counts[elem] = counts.get(elem, 0) + mult
        elif t.type == "LP":
            sub, j = _parse_group(tokens, i + 1)
            i = j
            if i >= len(tokens) or tokens[i].type != "RP":
                raise ValueError("Paréntesis no balanceados.")
            i += 1
            mult = 1
            if i < len(tokens) and tokens[i].type == "NUM":
                mult = int(tokens[i].value); i += 1
            for k, v in sub.items():
                counts[k] = counts.get(k, 0) + v * mult
        elif t.type == "RP":
            return counts, i
        else:
            raise ValueError("Token inesperado.")
    return counts, i


def _count_formula(formula: str) -> Dict[str, int]:
    toks = _tokenize_formula(formula)
    counts, pos = _parse_group(toks, 0)
    if pos != len(toks):
        raise ValueError("Fórmula mal parseada.")
    return counts


def masa_molar(formula: str) -> str:
    try:
        f = (formula or "").strip()
        if not f:
            return "Uso: /mm Ca(OH)2"
        counts = _count_formula(f)
        total = 0.0
        missing: List[str] = []
        for elem, n in counts.items():
            if elem not in _ATOMIC_MASS:
                missing.append(elem)
            else:
                total += _ATOMIC_MASS[elem] * n
        if missing:
            return f"Elementos no soportados en tabla local: {', '.join(sorted(missing))}."
        return f"⚗️ M_{f} = **{total:.4f} g/mol**"
    except Exception as e:
        return f"Error al interpretar la fórmula: {e}"


# =============================================================================
# 6) FÍSICA: SUVAT (solver básico)
# =============================================================================

def suvat(
    u: Optional[float] = None,
    v: Optional[float] = None,
    a: Optional[float] = None,
    t: Optional[float] = None,
    s: Optional[float] = None,
) -> str:
    known = {k: val for k, val in {"u": u, "v": v, "a": a, "t": t, "s": s}.items() if val is not None}
    if len(known) < 3:
        return "Proporciona al menos 3 variables. Ej: /suvat u=0 v=20 a=5"

    try:
        U, V, A, T, S = u, v, a, t, s

        # v = u + a t
        if V is None and U is not None and A is not None and T is not None:
            V = U + A * T
        if U is None and V is not None and A is not None and T is not None:
            U = V - A * T
        if A is None and V is not None and U is not None and T is not None:
            A = (V - U) / T
        if T is None and V is not None and U is not None and A is not None and A != 0:
            T = (V - U) / A

        # s = u t + 1/2 a t^2
        if S is None and U is not None and T is not None and A is not None:
            S = U * T + 0.5 * A * T * T
        if U is None and S is not None and T is not None and A is not None and T != 0:
            U = (S - 0.5 * A * T * T) / T
        if A is None and S is not None and U is not None and T is not None and T != 0:
            A = 2 * (S - U * T) / (T * T)
        if T is None and S is not None and U is not None and A is not None:
            if A == 0:
                if U != 0:
                    T = S / U
            else:
                aa, bb, cc = 0.5 * A, U, -S
                disc = bb * bb - 4 * aa * cc
                if disc >= 0:
                    r1 = (-bb + math.sqrt(disc)) / (2 * aa)
                    r2 = (-bb - math.sqrt(disc)) / (2 * aa)
                    T = r1 if r1 >= 0 else r2

        # v^2 = u^2 + 2 a s
        if V is None and U is not None and A is not None and S is not None:
            val = U * U + 2 * A * S
            V = math.sqrt(val) if val >= 0 else None
        if U is None and V is not None and A is not None and S is not None:
            val = V * V - 2 * A * S
            U = math.sqrt(val) if val >= 0 else None
        if A is None and V is not None and U is not None and S is not None and S != 0:
            A = (V * V - U * U) / (2 * S)
        if S is None and V is not None and U is not None and A is not None and A != 0:
            S = (V * V - U * U) / (2 * A)

        out = []
        for name, val, unit in (("u", U, "m/s"), ("v", V, "m/s"), ("a", A, "m/s^2"), ("t", T, "s"), ("s", S, "m")):
            if val is not None:
                out.append(f"{name} = {val:.6g} {unit}")
        return "🏎️ Cinemática (SUVAT):\n" + "\n".join(out) if out else "No se pudo resolver con esos datos."
    except Exception as e:
        return f"Error en solver SUVAT: {e}"


# =============================================================================
# 7) ESTADÍSTICA
# =============================================================================

def stats_lista(values: str) -> str:
    try:
        vals = np.array([float(x) for x in re.split(r"[,\s]+", (values or "").strip()) if x])
        if len(vals) == 0:
            return "Uso: /stats 1,2,2,3,5"
        msg = [
            f"n = {len(vals)}",
            f"media = {np.mean(vals):.6g}",
            f"mediana = {np.median(vals):.6g}",
            f"desv.est. = {np.std(vals, ddof=1):.6g}" if len(vals) > 1 else "desv.est. = N/A",
            f"min = {np.min(vals):.6g}",
            f"max = {np.max(vals):.6g}",
            f"Q1 = {np.quantile(vals, 0.25):.6g}",
            f"Q3 = {np.quantile(vals, 0.75):.6g}",
        ]
        return "📊 Estadísticos básicos:\n" + "\n".join(msg)
    except Exception as e:
        return f"Error al calcular estadísticas: {e}"


# =============================================================================
# 8) GRÁFICA y=f(x)
# =============================================================================

def plot(expr: str, xspec: str = "x:-5:5") -> str:
    """
    xspec:
      x:min:max
      x:min:step:max
    """
    try:
        expr = (expr or "").strip()
        parts = [p.strip() for p in (xspec or "").split(":")]
        if len(parts) not in (3, 4):
            return "Formato x inválido. Usa x:min:max o x:min:step:max"

        var = parts[0]
        if len(parts) == 3:
            a_s, b_s = parts[1], parts[2]
            step = None
        else:
            a_s, step_s, b_s = parts[1], parts[2], parts[3]
            step = float(sp.N(sp.sympify(step_s)))

        a = float(sp.N(sp.sympify(a_s)))
        b = float(sp.N(sp.sympify(b_s)))
        if a == b:
            return "El rango en x no puede ser igual."

        locals_map = {"pi": sp.pi, "e": sp.E, "sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "log": sp.log, "sqrt": sp.sqrt, "exp": sp.exp}
        expr_norm = expr.replace("^", "**").replace("ln(", "log(").replace("sen(", "sin(")

        x = sp.symbols(var)
        f_sym = sp.sympify(expr_norm, locals=locals_map)
        f = sp.lambdify(x, f_sym, modules=["numpy"])

        if step is None:
            xs = np.linspace(a, b, 800)
        else:
            npts = max(2, int(abs((b - a) / step)) + 1)
            xs = np.linspace(a, b, npts)

        ys = np.asarray(f(xs))
        if np.iscomplexobj(ys):
            if np.max(np.abs(np.imag(ys))) < 1e-9:
                ys = np.real(ys)
            else:
                ys = np.abs(ys)

        os.makedirs("plots", exist_ok=True)
        fpath = os.path.join("plots", f"plot_{uuid.uuid4().hex[:8]}.png")

        plt.figure()
        plt.plot(xs, ys)
        plt.xlabel(var)
        plt.ylabel("y")
        plt.title(f"y = {expr}")
        plt.grid(True, alpha=0.25)
        plt.tight_layout()
        plt.savefig(fpath, dpi=120)
        plt.close()

        return f"🖼️ Gráfica guardada en: {fpath}"
    except Exception as e:
        return f"Error al graficar: {e}"


# =============================================================================
# 9) ANÁLISIS ESTÁTICO DE CÓDIGO (sin ejecutar)
# =============================================================================

def _cyclomatic(tree: ast.AST) -> int:
    count = 1
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.IfExp)):
            count += 1
        if isinstance(node, ast.BoolOp):
            count += max(0, len(getattr(node, "values", [])) - 1)
        if isinstance(node, (ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp)):
            count += 1
    return count


def analizar_codigo(code: str) -> str:
    try:
        tree = ast.parse(code or "")
        lines = len([ln for ln in (code or "").splitlines() if ln.strip()])
        funcs = sum(isinstance(n, ast.FunctionDef) for n in ast.walk(tree))
        classes = sum(isinstance(n, ast.ClassDef) for n in ast.walk(tree))
        imports = sum(isinstance(n, (ast.Import, ast.ImportFrom)) for n in ast.walk(tree))
        cyclo = _cyclomatic(tree)

        return (
            "🧩 Análisis estático del código:\n"
            f"- líneas (no vacías): {lines}\n"
            f"- funciones: {funcs}\n"
            f"- clases: {classes}\n"
            f"- imports: {imports}\n"
            f"- complejidad ciclomatica (aprox): {cyclo}\n"
        )
    except Exception as e:
        return f"Error al analizar el código: {e}"


# =============================================================================
# API UNIFICADA: run_tool + autodetect_tool
# =============================================================================

def run_tool(name: str, payload: Dict[str, Any]) -> str:
    """
    Ejecuta un tool por nombre (usado por commands/backend).
    """
    name = (name or "").strip().lower()

    if name == "calc":
        return calc(payload.get("expr", ""))
    if name == "wiki":
        return wiki(payload.get("query", ""), payload.get("lang", "es"))
    if name == "deriva":
        return deriva(payload.get("expr", ""), payload.get("var", "x"))
    if name == "integra":
        return integra(payload.get("expr", ""), payload.get("var", "x"))
    if name == "limite":
        return limite(payload.get("expr", ""), payload.get("var", "x"), payload.get("at", "0"), payload.get("dir"))
    if name == "resuelve":
        return resuelve(payload.get("eq", ""), payload.get("var", "x"))
    if name == "simplifica":
        return simplifica(payload.get("expr", ""))
    if name == "u":
        return convierte(payload.get("expr", ""))
    if name == "mm":
        return masa_molar(payload.get("formula", ""))
    if name == "suvat":
        vals = payload.get("values", {}) or {}
        return suvat(
            u=vals.get("u"), v=vals.get("v"), a=vals.get("a"), t=vals.get("t"), s=vals.get("s")
        )
    if name == "stats":
        return stats_lista(payload.get("values", ""))
    if name == "plot":
        return plot(payload.get("expr", ""), payload.get("xspec", "x:-5:5"))
    if name == "analiza":
        return analizar_codigo(payload.get("code", ""))

    return "Tool no reconocido."


def autodetect_tool(user_text: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Detección rápida para usar tools sin comandos.
    Devuelve (tool_name, payload) o None.
    """
    t = (user_text or "").strip().lower()

    # conversión unidades: "convierte 60 km/h a m/s"
    m = re.search(r"(convierte|convertir|pasar)\s+(.+?)\s+(a|en)\s+(.+)$", t)
    if m:
        left = m.group(2).strip()
        right = m.group(4).strip()
        return "u", {"expr": f"{left} -> {right}"}

    # masa molar: "masa molar de Ca(OH)2"
    m = re.search(r"masa\s+molar\s+de\s+([A-Za-z0-9()]+)", t)
    if m:
        return "mm", {"formula": m.group(1).strip()}

    # suvat: "u=0 a=2 t=10"
    if any(k in t for k in ["u=", "v=", "a=", "t=", "s="]) and ("m/s" in t or "cinetica" in t or "suvat" in t):
        pairs = re.findall(r"(u|v|a|t|s)\s*=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", t)
        vals = {k.lower(): float(v) for k, v in pairs}
        if len(vals) >= 3:
            return "suvat", {"values": vals}

    # estadísticas: "media de 1,2,3"
    if "media" in t and re.search(r"\d", t):
        nums = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", t)
        if len(nums) >= 2:
            return "stats", {"values": ",".join(nums)}

    # cálculo seguro: expresiones tipo "2*(3+4)^2"
    if re.fullmatch(r"[0-9\.\s\+\-\*\/\^\(\)%]+", t) and any(opc in t for opc in ["+", "-", "*", "/", "^"]):
        return "calc", {"expr": user_text}

    return None
