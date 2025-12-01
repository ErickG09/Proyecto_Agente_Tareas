# Agente: Profesor asesor
# Datos del estudiante

- **Nombre:** Erick Guevara Morales
- **Materia:** Agentes Inteligentes 
- **Periodo:** Otoño 2025


![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![PyQt6](https://img.shields.io/badge/UI-PyQt6-41CD52)
![SQLite](https://img.shields.io/badge/DB-SQLite-003B57)
![Gemini](https://img.shields.io/badge/LLM-Gemini-orange)

> **Profesor Asesor** es una aplicación de escritorio para estudiar materias de ingeniería con:
> - Interfaz profesional (panel de control + chat)
> - **IA con Gemini** para explicación guiada (Tutor/Directo/Repaso/Lab/Quiz)
> - **Herramientas** determinísticas (/calc, /deriva, /integra, /u, /stats, /plot…)
> - **Memoria en SQLite** por usuario (historial + contexto reciente)
> - **Quiz** con opción múltiple (Gemini + fallback local)

---

## Características
- **UI en PyQt6**: panel izquierdo (usuario, contexto, modo, memoria, quiz) + chat a la derecha.
- **Sesiones por usuario**: cada usuario tiene su historial y contexto separado.
- **Memoria controlada**: se inyectan las últimas `k` interacciones relevantes como contexto (por defecto `k=3`).
- **Tools integradas**: resultados determinísticos cuando conviene (no es “un chat genérico”).
- **Quiz robusto**:
  - Intenta generar pregunta en JSON estricto con Gemini
  - Si falla, usa un **fallback local** para que nunca se rompa el flujo

---

### Flujo general
1. **UI** emite `sendMessage(text)` → `Backend.handle_message(text)`
2. `Backend` decide:
   - ¿Es **comando** (`/materia`, `/tema`, `/quiz`, tool)?
   - ¿Debe ejecutar una **tool** automáticamente?
   - ¿Está activo el **Quiz**?
   - Si no: **llama a Gemini** con prompt + memoria
3. Respuesta vuelve por `responseReady` y se imprime en la UI.
4. Se guarda el registro en **SQLite** (historial + quiz logs).

---

## Estructura de carpetas (actual)
```txt
PROYECTOFINALAGENTESINTELIGENTES/
│
├─ app.py
├─ .env
├─ asesor_memoria.sqlite3
├─ src/
│  ├─ core/
│  │  ├─ backend.py
│  │  ├─ commands.py
│  │  ├─ gemini_client.py
│  ├─ memory/
│  │  ├─ db.py
│  ├─ tools/
│  │  ├─ toolkit.py
│  ├─ ui/
│  │  ├─ chat_window.py
│  └─ __init__.py
└─ venv/
```

## ¿Qué hace cada archivo?

### `app.py`
- **Punto de entrada**.
- Arranca Qt, crea `MemoryDB`, crea `ChatWindow`, inicia `Backend` en un `QThread` y conecta señales.

### `src/ui/chat_window.py`
- **UI completa**: panel, chat, input, botones.
- Emite señales (`sendMessage`, `changeUser`, `requestUserList`) y renderiza burbujas.

### `src/core/backend.py`
- **Orquestador principal**.
- Parsea comandos (`parse_command`), llama tools (`run_tool`, `autodetect_tool`), ejecuta Quiz, construye prompt y consulta Gemini.
- Guarda historial y logs en SQLite por usuario/tema.

### `src/core/commands.py`
- Parser de comandos tipo `/calc ...`, `/materia ...`, `/quiz start`, etc.

### `src/core/gemini_client.py`
- Cliente robusto opcional para Gemini (extracción segura de `response.text` / `parts`).
- Útil cuando el SDK devuelve respuestas sin `parts` válidos.

### `src/memory/db.py`
- Encapsula SQLite: usuarios, temas, historial, sesiones de quiz, preguntas, respuestas.

### `src/tools/toolkit.py`
- Implementa tools determinísticas y autodetección.
- Ej: cálculo, derivadas, integrales, conversión unidades, stats, plots.



# Alcance y limitaciones

Esta aplicación está diseñada para apoyar el estudio de materias base de ingeniería con un enfoque académico. Incluye explicación guiada con IA, herramientas determinísticas y memoria por usuario.

## Materias objetivo

- Cálculo  
- Física  
- Química  
- Álgebra Lineal  
- Probabilidad y Estadística  
- Programación  

## Limitaciones (por diseño)

- No está pensada como un chat general de conversación libre.  
- No sustituye a un docente: su objetivo es apoyar comprensión, práctica y verificación.  
- El contenido puede ser incorrecto si la pregunta es ambigua, si faltan datos o si el usuario cambia de tema sin fijar contexto.  

## Reglas de uso (contenido académico)

El sistema está orientado a responder preguntas académicas. Para obtener mejores resultados:

- Define materia y tema desde el panel o con comandos (`/materia`, `/tema`).  
- Usa herramientas determinísticas cuando aplique (por ejemplo, cálculo simbólico, unidades, estadística).  
- En modo Quiz, responde únicamente con **A/B/C/D** o **“siguiente”**.


# Pruebas rápidas (verificación funcional)

Estos casos validan el flujo principal de la app.

## 1) Sesión por usuario y memoria separada

1. Inicia sesión con un usuario (ej. “Erick Guevara”).
2. Pregunta algo breve en una materia concreta.
3. Cambia a otro usuario (ej. “Invitado”) y repite.
4. Verifica que el historial y la memoria no se mezclan entre usuarios.

## 2) Tools determinísticas (sin depender de IA)

1. Ejecuta: `/calc 2*(3+4)^2`
2. Ejecuta: `/u 60 km/h -> m/s`
3. Verifica que la salida es inmediata y consistente.

## 3) Quiz robusto

1. Selecciona materia/tema y presiona “Iniciar quiz” (o `/quiz start`).
2. Contesta “A/B/C/D” y luego escribe “siguiente”.
3. Verifica que el flujo no se rompe: si falla la IA, entra el fallback local.

## 4) Memoria activada/desactivada

1. Desactiva “Usar memoria (SQLite)”.
2. Haz una pregunta que normalmente requeriría contexto previo.
3. Reactiva memoria y repite, observando que se recuperan interacciones previas (según `k`).


# Memoria (SQLite): qué guarda y cuánto contexto usa

## Qué guarda la aplicación (SQLite)

La aplicación guarda en SQLite:

- Usuarios  
- Materias/temas (topics)  
- Historial de preguntas/respuestas por usuario y topic  
- Sesiones de quiz, preguntas generadas y respuestas del usuario  

## Contexto inyectado en el prompt

- Por defecto se toman las últimas `k=3` interacciones relevantes del **mismo usuario** y del **mismo topic**.  
- El tamaño del fragmento de cada respuesta se recorta para no inflar el prompt.

## Archivo local

- `asesor_memoria.sqlite3`

## Reinicio de datos

- Puedes eliminar `asesor_memoria.sqlite3` para reiniciar toda la memoria e historial.

---

# Modos de respuesta

El modo controla la estructura de la respuesta:

- **Tutor:** explicación paso a paso; si es numérico, usa *fórmula → sustitución → resultado*.  
- **Directo:** respuesta concisa y validación breve.  
- **Repaso:** definición corta + ejemplo mínimo + preguntas de autoevaluación.  
- **Lab:** procedimiento y supuestos; enfoque práctico.  
- **Quiz:** preguntas tipo examen; corrección por opción.

---

# Herramientas disponibles (Tools)

La app incluye herramientas determinísticas para evitar depender siempre de la IA, por ejemplo:

- Cálculo simbólico (derivadas, integrales, límites, simplificación)  
- Conversión de unidades  
- Estadística básica  
- Gráficas simples  
- Consulta rápida tipo wiki (si está habilitada en toolkit)

Además, existe **autodetección**: si el texto del usuario coincide con un patrón reconocido, el backend puede ejecutar automáticamente una tool en lugar de invocar IA.

---

# Troubleshooting

## Error de modelo / respuesta vacía (`finish_reason`)

**Síntoma:**
- “No pude generar texto… finish_reason: …”

**Causas típicas:**
- Modelo incorrecto en `GEMINI_MODEL`
- API key inválida o sin permisos
- Respuesta bloqueada o sin `parts` válidos en el SDK

**Soluciones:**
- Verifica `GEMINI_API_KEY` y el nombre exacto del modelo
- Prueba una pregunta más específica y corta
- En **Quiz**, el sistema debe continuar por **fallback local** si Gemini falla

## Quiz no genera pregunta

**Síntoma:**
- “No pude generar pregunta de quiz. Intenta otra vez con siguiente.”

**Causas típicas:**
- Fallo de parseo de JSON de Gemini
- Respuesta truncada

**Soluciones:**
- Reintenta con “siguiente”
- Activa `BACKEND_DEBUG=1` para ver el flujo (gemini → reparación → fallback)
