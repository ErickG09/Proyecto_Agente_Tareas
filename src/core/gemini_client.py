from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional, Dict


@dataclass(frozen=True)
class GenConfig:
    # El modelo por defecto puede ser sobreescrito por .env o en cada llamada
    model: str = "gemini-2.5-flash"
    temperature: float = 0.2
    top_p: float = 0.9
    top_k: int = 40
    max_output_tokens: int = 700
    default_thinking_budget: Optional[int] = 0


class GeminiClient:
    """
    - Lee API key desde GEMINI_API_KEY.
    - Lee modelo desde GEMINI_MODEL si está presente.
    - No revienta si response.text no existe (parts vacíos).
    - Maneja caso común: finish_reason=MAX_TOKENS y respuesta vacía -> retry 1 vez.
    """

    def __init__(self, api_key: str, config: Optional[GenConfig] = None):
        self.api_key = (api_key or "").strip()
        self.config = config or GenConfig()

        try:
            from google import genai
        except Exception as e:
            raise RuntimeError(
                "No encontré el SDK 'google-genai'. Instálalo con:\n"
                "  pip install -U google-genai\n"
                f"Detalle: {e}"
            )

        self._genai = genai
        self._client = genai.Client(api_key=self.api_key)

    @staticmethod
    def from_env(config: Optional[GenConfig] = None) -> "GeminiClient":
        key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
        if not key:
            raise RuntimeError(
                "Falta API key. Define una de estas variables en tu .env:\n"
                "  GEMINI_API_KEY=...\n"
                "  (o legacy) GOOGLE_API_KEY=..."
            )

        # Modelo configurable por .env
        env_model = (os.getenv("GEMINI_MODEL") or "").strip()
        base = config or GenConfig()
        if env_model:
            base = GenConfig(
                model=env_model,
                temperature=base.temperature,
                top_p=base.top_p,
                top_k=base.top_k,
                max_output_tokens=base.max_output_tokens,
                default_thinking_budget=base.default_thinking_budget,
            )

        return GeminiClient(api_key=key, config=base)

    def generate_text(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
        thinking_budget: Optional[int] = None,
        model: Optional[str] = None,
    ) -> str:
        """
        Genera texto. Si el SDK devuelve respuesta vacía/bloqueada, regresa mensaje legible.
        Implementa retry 1 vez cuando finish_reason indica MAX_TOKENS y no hay texto.
        """
        selected_model = (model or self.config.model).strip()
        cfg = self._build_config(
            system=system,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            thinking_budget=thinking_budget,
        )

        try:
            response = self._client.models.generate_content(
                model=selected_model,
                contents=prompt,
                config=cfg,
            )

            text = self._safe_extract_text(response)
            if text:
                return text.strip()

            finish = self._safe_finish_reason(response)
            usage = self._safe_usage(response)

            # Retry 1 vez si es MAX_TOKENS y no hubo texto (caso frecuente)
            if self._is_max_tokens(finish):
                retry_max = int((max_output_tokens or self.config.max_output_tokens) * 2)
                retry_max = max(256, min(retry_max, 4096))  # límites razonables
                retry_cfg = self._build_config(
                    system=system,
                    temperature=temperature,
                    max_output_tokens=retry_max,
                    thinking_budget=0,  # clave: evitar que "thinking" se coma el presupuesto
                )
                try:
                    response2 = self._client.models.generate_content(
                        model=selected_model,
                        contents=prompt,
                        config=retry_cfg,
                    )
                    text2 = self._safe_extract_text(response2)
                    if text2:
                        return text2.strip()
                    finish2 = self._safe_finish_reason(response2)
                    usage2 = self._safe_usage(response2)
                    return (
                        "No pude obtener texto: el modelo llegó al límite de tokens y devolvió contenido vacío.\n"
                        f"finish_reason={finish2}\n"
                        f"usage={usage2}\n"
                        "Sugerencias:\n"
                        "- Reduce el prompt (especialmente instrucciones largas).\n"
                        "- Usa respuestas 'corta' en tu UI.\n"
                        "- Deja thinking_budget=0 para Quiz/outputs estructurados."
                    )
                except Exception:
                    pass

            # Caso general: vacío o bloqueado
            return (
                "No pude obtener una respuesta de texto (la API devolvió contenido vacío o bloqueado).\n"
                f"finish_reason={finish}\n"
                f"usage={usage}\n"
                "Tip: intenta reformular, reducir el prompt o bajar el output."
            )

        except Exception as e:
            return (
                f"No pude consultar el modelo ({selected_model}).\n"
                f"Detalle técnico: {e}"
            )

    # ---------------------------- helpers ----------------------------

    def _build_config(
        self,
        *,
        system: Optional[str],
        temperature: Optional[float],
        max_output_tokens: Optional[int],
        thinking_budget: Optional[int],
    ):
        from google.genai import types  # type: ignore

        # Si el caller no manda thinking_budget, toma el default del config
        if thinking_budget is None:
            thinking_budget = self.config.default_thinking_budget

        kwargs: Dict[str, Any] = {
            "system_instruction": system if system else None,
            "temperature": self.config.temperature if temperature is None else float(temperature),
            "top_p": self.config.top_p,
            "top_k": self.config.top_k,
            "max_output_tokens": self.config.max_output_tokens
            if max_output_tokens is None
            else int(max_output_tokens),
        }

        # thinking_config no siempre existe en todas las versiones del SDK
        if thinking_budget is not None:
            try:
                kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=int(thinking_budget))
            except Exception:
                # Si tu versión no soporta thinking_config, simplemente lo omitimos
                pass

        return types.GenerateContentConfig(**kwargs)

    def _safe_extract_text(self, response: Any) -> str:
        # 1) Camino “bonito”: response.text (a veces truena o viene None)
        try:
            txt = getattr(response, "text", None)
            if isinstance(txt, str) and txt.strip():
                return txt
        except Exception:
            pass

        # 2) Camino robusto: candidates -> content -> parts -> text
        candidates = getattr(response, "candidates", None) or []
        for cand in candidates:
            content = getattr(cand, "content", None)
            if not content:
                continue
            parts = getattr(content, "parts", None) or []
            chunks: list[str] = []
            for p in parts:
                t = getattr(p, "text", None)
                if isinstance(t, str) and t.strip():
                    chunks.append(t)
            if chunks:
                return "\n".join(chunks)

        return ""

    def _safe_finish_reason(self, response: Any) -> str:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return "none"
        fr = getattr(candidates[0], "finish_reason", None)
        if fr is None:
            return "unknown"
        # A veces viene como enum/str/int
        try:
            s = str(fr)
        except Exception:
            s = "unknown"
        return s

    def _is_max_tokens(self, finish_reason: str) -> bool:
        fr = (finish_reason or "").upper()
        # Dependiendo del SDK puede ser "MAX_TOKENS", "FinishReason.MAX_TOKENS" o "2"
        return ("MAX_TOKENS" in fr) or (fr.strip() == "2")

    def _safe_usage(self, response: Any) -> Dict[str, Any]:
        usage = getattr(response, "usage_metadata", None)
        if not usage:
            return {}
        out: Dict[str, Any] = {}
        for k in (
            "prompt_token_count",
            "candidates_token_count",
            "total_token_count",
            "thoughts_token_count",
        ):
            v = getattr(usage, k, None)
            if v is not None:
                out[k] = v
        return out
