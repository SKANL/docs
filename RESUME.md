# Resume Prompt — universal-doc-harness

## Quick start (preferred)

Open Claude Code with the working directory set to this repo
(`C:\code\harness-projects\docs`) so `CLAUDE.md` and `.codegraph/` load from
here, then send exactly:

```
Leé RESUME.md y ejecutá su prompt tal cual está escrito: recuperá el estado del cambio universal-doc-harness, respetá la jerarquía de herramientas al pie de la letra, decime dónde quedamos y qué tarea sigue, y esperá mi OK antes de implementar.
```

## Full prompt

Paste the prompt below verbatim at the start of every new Claude Code session
(or after any interruption) to resume the SDD implementation exactly where it
stopped. Files under `openspec/changes/universal-doc-harness/` are the source
of truth; this prompt only tells the session how to read them and which tool
contract to honor. The prompt is in Spanish because sessions are conducted in
Spanish.

---

```
Retomá el SDD del cambio "universal-doc-harness" en C:\code\harness-projects\docs exactamente donde quedó. Trabajás bajo el siguiente CONTRATO DE HERRAMIENTAS — todas obligatorias, cada una en su dominio, con jerarquía explícita que resuelve cualquier conflicto entre ellas.

## JERARQUÍA DE AUTORIDAD

1. OPENSPEC ES LA FUENTE DE VERDAD. Todo vive en openspec/changes/universal-doc-harness/: proposal.md, design.md, specs/ (5 capacidades), tasks.md (los checkboxes [x] son LA verdad del progreso) y state.yaml (config + fase actual). PROHIBIDO reescribir, regenerar, truncar o borrar estos archivos. Solo actualizaciones aditivas: marcar checkboxes, actualizar campos de state.yaml, crear artefactos de fases nuevas (apply-progress, verify-report, archive-report). Si algo contradice estos archivos, los archivos ganan.

2. GENTLE AI (SDD) ES EL ORQUESTADOR. Decide qué fase sigue y delega a subagentes sdd-* (sdd-apply con modelo sonnet). El artifact store es HYBRID, así que el dispatcher nativo puede leer los archivos openspec para rutear; los espejos en Engram son respaldo de recuperación, NUNCA verdad primaria. TDD AGRESIVO (Strict TDD Mode) activo: `uv run pytest`, test RED obligatorio antes de cada implementación, sin fallback a modo estándar, sin excepciones.

3. SUPERPOWERS APORTA LA DISCIPLINA DE PROCESO que OpenSpec no define — el CÓMO dentro de cada tarea. Obligatorios: test-driven-development (método red/green/refactor de cada par de tareas), systematic-debugging (ante cualquier test que falle de forma inesperada, antes de proponer fixes), verification-before-completion (evidencia de comandos corridos antes de declarar nada terminado), subagent-driven-development y dispatching-parallel-agents (la implementación la ejecutan subagentes, no el orquestador), requesting-code-review (antes de cada PR). PROHIBIDO usar brainstorming, writing-plans o executing-plans para re-planificar: la planificación ya está congelada en OpenSpec y superpowers NO la pisa, la ejecuta.

4. HERRAMIENTAS DE CONOCIMIENTO Y EFICIENCIA, obligatorias en su ámbito:
   - ENGRAM: al inicio mem_context + recuperar "sdd/universal-doc-harness/apply-progress" (merge, NUNCA overwrite); guardado proactivo de toda decisión/bug/descubrimiento durante el trabajo; mem_session_summary antes de cerrar la sesión.
   - CODEGRAPH: SIEMPRE antes de editar — codegraph_explore para blast radius y fuente verbatim del símbolo a tocar. Nada de exploración masiva con grep/read cuando el grafo ya tiene la respuesta.
   - CONTEXT7: SIEMPRE antes de escribir código contra una librería externa (typer, pydantic, python-docx, filetype, opendataloader-pdf, pandoc) — resolvé la documentación actual, no codees APIs de memoria.
   - RTK: prefijo `rtk` en TODOS los comandos de shell, incluso dentro de cadenas con &&.

## RECUPERACIÓN (en este orden, antes de tocar código)

1. Leé state.yaml y tasks.md de openspec/changes/universal-doc-harness/.
2. Engram (project: "docs"): mem_context + mem_search "sdd/universal-doc-harness/apply-progress" y el último session summary; si apply-progress existe, leelo completo con mem_get_observation y cruzalo con los checkboxes de tasks.md.
3. Verificá la realidad: estado de git (rama, cambios sin commitear, últimos commits) y `rtk uv run pytest` como línea base. Si hay trabajo a medias sin commitear, evaluálo contra tasks.md ANTES de escribir nada. Ante divergencia: git y tasks.md mandan sobre Engram.

## REGLAS VINCULANTES (ya decididas — no re-preguntar)

- Modo interactivo: al cerrar cada slice, mostrame resultado y esperá mi OK antes del siguiente.
- auto-chain + stacked-to-main: cada PR mergea a main en orden; main queda verde y shippeable tras cada merge; slices ≤400 líneas.
- Skills chained-pr y work-unit-commits inyectados a cada subagente de implementación (paths del registry en .atl/skill-registry.md).
- Revisión fresh-context obligatoria antes de cada commit/PR.
- Tarea 5.1 (spike opendataloader-pdf) es GATE BLOQUEANTE antes de lockear la dependencia PDF (tareas 5.6, 6.3, 6.4); si falla, PR6 se replanifica sin PDF.
- Artefactos técnicos en inglés; strings de UI del CLI en español (convención del proyecto); conversación en español.

## CIERRE DE CADA SLICE

1. Marcar checkboxes en tasks.md y actualizar state.yaml (aditivo).
2. Actualizar apply-progress en Engram (merge con lo existente).
3. `rtk uv run pytest` verde + evidencia mostrada (verification-before-completion).
4. Si la sesión está por terminar: mem_session_summary con próximo paso exacto.

Arrancá: ejecutá la RECUPERACIÓN, decime en qué estado quedó todo y qué tarea sigue, y esperá mi confirmación antes de implementar.
```
