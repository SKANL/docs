# Resume Prompt — SDD sessions in this repo

The founding change `universal-doc-harness` is COMPLETE and archived
(`openspec/changes/archive/2026-07-06-universal-doc-harness/`). The current
capability contract lives in `openspec/specs/`. This file is now the generic
resume/kickoff prompt for FUTURE SDD changes; replace `<change>` with the
active change name.

## Quick start (preferred)

Open Claude Code with the working directory set to this repo
(`C:\code\harness-projects\docs`) so `CLAUDE.md` and `.codegraph/` load from
here, then send:

```
Leé RESUME.md y ejecutá su prompt tal cual está escrito para el cambio "<change>": recuperá el estado, respetá la jerarquía de herramientas al pie de la letra, decime dónde quedamos y qué tarea sigue, y esperá mi OK antes de implementar.
```

To start a NEW change instead of resuming one, send `/sdd-new <change>` (or
`/sdd-ff <change>` to fast-forward planning) — the new change deltas against
the main specs in `openspec/specs/`.

## Full prompt

Paste the prompt below verbatim at the start of every session (or after any
interruption), substituting the change name. Files under
`openspec/changes/<change>/` are the source of truth; this prompt only tells
the session how to read them and which tool contract to honor. The prompt is
in Spanish because sessions are conducted in Spanish.

---

```
Retomá el SDD del cambio "<change>" en C:\code\harness-projects\docs exactamente donde quedó. Trabajás bajo el siguiente CONTRATO DE HERRAMIENTAS — todas obligatorias, cada una en su dominio, con jerarquía explícita que resuelve cualquier conflicto entre ellas.

## JERARQUÍA DE AUTORIDAD

1. OPENSPEC ES LA FUENTE DE VERDAD. Los specs vigentes viven en openspec/specs/ (5 capacidades); los cambios nuevos son deltas contra esos specs. Todo lo del cambio activo vive en openspec/changes/<change>/: proposal.md, design.md, specs/, tasks.md (los checkboxes [x] son LA verdad del progreso) y state.yaml (config + fase actual). PROHIBIDO reescribir, regenerar, truncar o borrar estos archivos. Solo actualizaciones aditivas: marcar checkboxes, actualizar campos de state.yaml, crear artefactos de fases nuevas (apply-progress, verify-report, archive-report). Si algo contradice estos archivos, los archivos ganan.

2. GENTLE AI (SDD) ES EL ORQUESTADOR. Decide qué fase sigue y delega a subagentes sdd-* según la tabla de modelos (sdd-apply con sonnet). El artifact store es HYBRID: los archivos openspec son verdad primaria; los espejos en Engram son respaldo de recuperación, NUNCA verdad primaria. TDD AGRESIVO (Strict TDD Mode) activo: `uv run pytest`, test RED obligatorio antes de cada implementación, sin fallback a modo estándar, sin excepciones.

3. SUPERPOWERS APORTA LA DISCIPLINA DE PROCESO que OpenSpec no define — el CÓMO dentro de cada tarea. Obligatorios: test-driven-development (método red/green/refactor de cada par de tareas), systematic-debugging (ante cualquier test que falle de forma inesperada, antes de proponer fixes), verification-before-completion (evidencia de comandos corridos antes de declarar nada terminado), subagent-driven-development y dispatching-parallel-agents (la implementación la ejecutan subagentes, no el orquestador), requesting-code-review (antes de cada PR). PROHIBIDO usar brainstorming, writing-plans o executing-plans para re-planificar: la planificación congelada en OpenSpec no se pisa, se ejecuta.

4. HERRAMIENTAS DE CONOCIMIENTO Y EFICIENCIA, obligatorias en su ámbito:
   - ENGRAM: al inicio mem_context + recuperar "sdd/<change>/apply-progress" (merge, NUNCA overwrite); guardado proactivo de toda decisión/bug/descubrimiento durante el trabajo; mem_session_summary antes de cerrar la sesión.
   - CODEGRAPH: SIEMPRE antes de editar — codegraph_explore para blast radius y fuente verbatim del símbolo a tocar; `rtk codegraph sync` después de cada merge a main o cuando el índice quede detrás de la rama. Nada de exploración masiva con grep/read cuando el grafo ya tiene la respuesta.
   - CONTEXT7: SIEMPRE antes de escribir código contra una librería externa (typer, pydantic, python-docx, filetype, opendataloader-pdf, pandoc) — resolvé la documentación actual, no codees APIs de memoria.
   - RTK: prefijo `rtk` en TODOS los comandos de shell, incluso dentro de cadenas con &&.

## RECUPERACIÓN (en este orden, antes de tocar código)

1. Leé state.yaml y tasks.md de openspec/changes/<change>/ (si no existe el cambio, arrancá por /sdd-new o /sdd-ff).
2. Engram (project: "docs"): mem_context + mem_search "sdd/<change>/apply-progress" y el último session summary; si apply-progress existe, leelo completo con mem_get_observation y cruzalo con los checkboxes de tasks.md.
3. Verificá la realidad: estado de git (rama, cambios sin commitear, últimos commits) y `rtk uv run pytest` como línea base. Si hay trabajo a medias sin commitear, evaluálo contra tasks.md ANTES de escribir nada. Ante divergencia: git y tasks.md mandan sobre Engram.

## REGLAS VINCULANTES (ya decididas — no re-preguntar)

- Modo interactivo: al cerrar cada slice, mostrame resultado y esperá mi OK antes del siguiente (salvo que yo autorice explícitamente encadenar).
- auto-chain + stacked-to-main: cada PR mergea a main en orden; main queda verde y shippeable tras cada merge; slices ≤400 líneas; overages justificados se registran como size:exception en el cuerpo del PR (el repo no tiene ese label).
- Skills chained-pr y work-unit-commits inyectados a cada subagente de implementación (paths del registry en .atl/skill-registry.md).
- Revisión fresh-context obligatoria antes de cada commit/PR; SOLUCIONAR TODOS los hallazgos (incluidos SUGGESTIONs) y re-revisar antes de push/PR/merge.
- Artefactos técnicos en inglés; strings de UI del CLI en español (convención del proyecto); conversación en español.

## LECCIONES OPERATIVAS VINCULANTES (pagadas con incidentes reales)

- GATE MECÁNICO TRAS CADA FASE DELEGADA: validá el output del subagente contra la realidad (diff contra fuentes, paths existentes, suite corrida) ANTES de commitear o encadenar la fase siguiente. Fases "mecánicas" delegadas a modelos chicos (copiar/archivar) se verifican con diff byte a byte contra los originales — "copied/frozen" declarado no es evidencia.
- Un test de determinismo que falla intermitentemente es un BUG DE PRODUCTO hasta demostrar lo contrario (precedente: timestamps de entradas zip en DOCX, granularidad DOS de 2s — pasa en aislamiento, falla bajo carga). Root cause con systematic-debugging y RED determinista antes de cualquier fix.
- Al resolver una colisión de archivos por renombre/namespacing, auditá TAMBIÉN el lado lector: todo glob/reader del directorio afectado (precedente: curated-index.md filtrándose al pipeline de evidencia).
- Los documentos generados por subagentes (reportes, specs mergeados) se verifican factualmente contra git/gh antes de volverse registro durable.
- apply-progress en Engram se actualiza por MERGE preservando historia; si un subagente lo estrecha, el orquestador lo restaura consolidado.

## CIERRE DE CADA SLICE

1. Marcar checkboxes en tasks.md y actualizar state.yaml (aditivo).
2. Actualizar apply-progress en Engram (merge con lo existente).
3. `rtk uv run pytest` verde + evidencia mostrada (verification-before-completion).
4. Tras merge a main: verificar main verde, `rtk codegraph sync`, registrar el merge en state.yaml.
5. Si la sesión está por terminar: mem_session_summary con próximo paso exacto.

Arrancá: ejecutá la RECUPERACIÓN, decime en qué estado quedó todo y qué tarea sigue, y esperá mi confirmación antes de implementar.
```

## Reference

- Baseline at archive time (2026-07-06): main @ `488ed1b`, suite 923 passed /
  7 skipped, all 5 capability specs merged to `openspec/specs/`.
- PR ledger and full audit trail:
  `openspec/changes/archive/2026-07-06-universal-doc-harness/archive-report.md`.
