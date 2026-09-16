# src/docs/domain/issue_codes.py
"""The catalog behind every `Issue.code` the review loop emits.

`AGENTS.md` §4 asks the agent to run `review-section --json` and iterate to
green. That is only actionable if each code says what it means and what
clears it, so this module is the ONE place that knowledge lives: `docs
explain` reads it, `AGENTS.md` points at that command instead of restating
the table, and `tests/unit/domain/test_issue_codes.py` fails the build if
the code emits something absent here (or documents something nobody emits).

Pure data + two pure functions. No I/O -- the CLI does the printing.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass

# What each code family is ABOUT, so an unfamiliar code is still placeable
# from its prefix alone.
ISSUE_CODE_FAMILIES: dict[str, str] = {
    "accessibility": "Señales técnicas de accesibilidad del artefacto, sin afirmar conformidad WCAG.",
    "apa": "Citas y referencias en estilo APA 7 dentro de una sección.",
    "coherence": "Consistencia del documento COMPLETO (entre secciones).",
    "content": "Estado del cuerpo redactado frente a la política del template.",
    "contract": "El contrato de la sección: contenido obligatorio y longitud.",
    "evidence": "Respaldo verificable de lo que la sección afirma.",
    "privacy": "Secretos, credenciales o datos sensibles filtrados al texto.",
    "qa": "Auditoría visual del artefacto renderizado (PDF vía LibreOffice).",
    "render": "Verificación y apertura de artefactos renderizados en formatos admitidos.",
    "reproducibility": "Reproducibilidad determinista de los artefactos generados.",
    "scope": "Delimitación del alcance declarado del documento.",
    "structure": "Existencia y forma de las secciones y sus títulos.",
    "template": "Validez del archivo de plantilla en sí.",
    "visual": "Comparación visual y evidencia de previews del artefacto renderizado.",
    "voice": "Registro y persona gramatical exigidos por el template.",
}


@dataclass(frozen=True)
class IssueCode:
    """One diagnostic the review loop can emit.

    `meaning` answers "¿qué detectó?"; `fix` answers "¿qué hago para que
    desaparezca?". Both are required and both are checked for substance by
    the catalog tests -- a one-word entry is worse than none, because it
    looks documented.
    """

    meaning: str
    fix: str


ISSUE_CODES: dict[str, IssueCode] = {
    # --- apa ----------------------------------------------------------------
    "apa.citation_without_reference": IssueCode(
        meaning="Una cita en el texto no tiene su entrada correspondiente en la lista de referencias.",
        fix="Agregá la referencia completa a la lista, o corregí el apellido/año de la cita si no coinciden.",
    ),
    "apa.no_reference_list": IssueCode(
        meaning="Hay citas APA en el cuerpo pero no se detecta ninguna lista de referencias.",
        fix="Creá la sección de referencias que el template declara (`references_list: true` en su contrato).",
    ),
    "apa.quote_without_locator": IssueCode(
        meaning="Una cita textual aparece sin el localizador de página o párrafo que APA 7 exige.",
        fix="Agregá el localizador junto a la cita, por ejemplo `(Autor, 2024, p. 12)`.",
    ),
    "apa.reference_without_citation": IssueCode(
        meaning="Una entrada de la lista de referencias no se cita en ninguna parte del texto.",
        fix="Citala donde corresponda, o quitala de la lista: APA no admite referencias no citadas.",
    ),
    "apa.references_not_sorted": IssueCode(
        meaning="Las entradas de la lista de referencias no están en orden alfabético.",
        fix="Reordená la lista alfabéticamente por apellido del primer autor.",
    ),
    "apa.required": IssueCode(
        meaning="El contrato de la sección exige citas APA y no se detectó ninguna.",
        fix="Citá las fuentes que respaldan la sección, o dejá `PENDIENTE:` si todavía no las tenés (solo en borrador).",
    ),
    # --- coherence ----------------------------------------------------------
    "coherence.citation_without_global_reference": IssueCode(
        meaning="Una cita usada en el cuerpo no figura en la lista de referencias del documento completo.",
        fix="Agregala a la lista de referencias global. Es la versión documento-completo de `apa.citation_without_reference`.",
    ),
    "coherence.contested_stack_unqualified": IssueCode(
        meaning="La sección afirma una tecnología en disputa como si fuera decisión cerrada.",
        fix="Delimitá la afirmación (para qué componente, bajo qué criterio) o marcala como `PENDIENTE:`.",
    ),
    "coherence.duration_mismatch": IssueCode(
        meaning="Distintas secciones declaran duraciones distincts para el mismo período.",
        fix="Unificá el valor. Si viene del contexto, corregilo con `context set` y regenerá las secciones afectadas.",
    ),
    "coherence.missing_flow": IssueCode(
        meaning="No se detecta el hilo argumental mínimo que conecta las secciones entre sí.",
        fix="Agregá las referencias cruzadas que faltan; el hallazgo nombra los términos de flujo ausentes.",
    ),
    "coherence.reference_without_global_citation": IssueCode(
        meaning="Una referencia del documento no se cita en ninguna sección del cuerpo.",
        fix="Citala donde corresponda o quitala. Es la versión documento-completo de `apa.reference_without_citation`.",
    ),
    # --- content ------------------------------------------------------------
    "content.pending_not_allowed": IssueCode(
        meaning="Quedan marcadores `PENDIENTE:` y el modo estricto no los admite.",
        fix="Reemplazá cada `PENDIENTE:` por contenido real, o construí sin `--strict` si todavía es un borrador.",
    ),
    # --- contract -----------------------------------------------------------
    "contract.length_above_max": IssueCode(
        meaning="La sección supera el máximo de palabras que fija su contrato.",
        fix="Recortá el cuerpo, o subí `length.max_words` en el contrato de la sección si el límite era irreal.",
    ),
    "contract.length_below_min": IssueCode(
        meaning="La sección no llega al mínimo de palabras que fija su contrato.",
        fix="Desarrollá el contenido faltante, o bajá `length.min_words` si el mínimo era irreal.",
    ),
    "contract.missing_required": IssueCode(
        meaning="Falta contenido obligatorio que el contrato de la sección declara en `required_content`.",
        fix="Escribí sobre cada tema que el hallazgo enumera usando esa misma palabra en el cuerpo: sin un bloque `detect`, el arnés lematiza el término y lo busca como palabra suelta. Si tu sección lo cubre con otro vocabulario, declará los sinónimos en `detect` dentro del contrato de la sección.",
    ),
    # --- evidence -----------------------------------------------------------
    "evidence.required": IssueCode(
        meaning="El contrato exige evidencia verificable y la sección no la aporta.",
        fix="Citá una fuente del ledger de hechos, o dejá `PENDIENTE:` mientras la conseguís (solo en borrador).",
    ),
    "evidence.results_without_evidence": IssueCode(
        meaning="La sección afirma resultados sin evidencia detectable que los respalde.",
        fix="Agregá la evidencia (dato, medición, fuente) o marcá el resultado como `PENDIENTE:`.",
    ),
    # --- privacy ------------------------------------------------------------
    "privacy.sensitive_data": IssueCode(
        meaning="El texto contiene algo que coincide con un patrón de secreto, credencial o dato personal.",
        fix="Quitá el dato del cuerpo. Si es un falso positivo, ajustá `secret_patterns` en la configuración normativa.",
    ),
    # --- qa -----------------------------------------------------------------
    "qa.failed": IssueCode(
        meaning="La auditoría visual sobre el PDF renderizado terminó con error.",
        fix="Leé el detalle del hallazgo: casi siempre es LibreOffice fallando sobre un .docx que igual quedó bien armado.",
    ),
    "qa.skipped": IssueCode(
        meaning="No se pudo hacer la auditoría visual porque falta LibreOffice; la de formato sí corrió.",
        fix="Instalá LibreOffice para habilitarla. No bloquea: la auditoría estructural del .docx ya se ejecutó.",
    ),
    # --- render ------------------------------------------------------------
    "accessibility.pdf.language_missing": IssueCode(
        meaning="El catálogo PDF no declara el idioma principal del documento.",
        fix="Definí el idioma del documento en el catálogo PDF y repetí la verificación; esto no valida por sí solo el orden de lectura.",
    ),
    "accessibility.pdf.title_missing": IssueCode(
        meaning="Los metadatos del PDF no declaran un título.",
        fix="Agregá un título descriptivo en los metadatos del PDF y repetí la verificación; esto no constituye una auditoría WCAG.",
    ),
    "accessibility.pdf.metadata_unverified": IssueCode(
        meaning="No se pudieron inspeccionar las señales básicas de idioma y título del PDF.",
        fix="Revisá la capacidad del parser PDF instalado y volvé a ejecutar la verificación.",
    ),
    "accessibility.pdf.untagged": IssueCode(
        meaning="El PDF no declara una estructura etiquetada; el orden de lectura y las alternativas no pudieron verificarse.",
        fix="Generá el PDF con estructura etiquetada y validalo con una herramienta especializada.",
    ),
    "accessibility.pdf.tags_unverified": IssueCode(
        meaning="El PDF declara etiquetas, pero esta verificación no inspecciona su semántica ni el orden de lectura.",
        fix="Usá una herramienta especializada de accesibilidad PDF para revisar la estructura y las alternativas.",
    ),
    "accessibility.pdf.structure_unverified": IssueCode(
        meaning="No se pudo inspeccionar el árbol lógico del PDF, por lo que esta señal técnica quedó sin verificar; no representa una conclusión de conformidad.",
        fix="Instalá o repará el parser PDF opcional y repetí la verificación; después usá una herramienta especializada para evaluar la estructura completa.",
    ),
    "accessibility.pdf.structure_missing": IssueCode(
        meaning="El PDF no contiene un árbol de estructura lógica detectable para relacionar encabezados, figuras o tablas.",
        fix="Generá el PDF conservando una estructura lógica etiquetada y repetí la verificación; confirmá el resultado con una herramienta especializada.",
    ),
    "accessibility.pdf.heading_missing": IssueCode(
        meaning="El árbol lógico inspeccionado no contiene elementos básicos de encabezado, así que no se pudo confirmar su jerarquía.",
        fix="Marcá los encabezados con roles estructurales PDF apropiados y revisá nuevamente el árbol lógico generado.",
    ),
    "accessibility.pdf.figure_alt_missing": IssueCode(
        meaning="Una figura estructurada no tiene texto alternativo ni descripción detectable en el PDF.",
        fix="Agregá texto alternativo o una descripción equivalente a la figura en la fuente y reconstruí el PDF.",
    ),
    "accessibility.pdf.table_semantics_missing": IssueCode(
        meaning="Una tabla estructurada no expone filas o celdas detectables, por lo que su semántica básica requiere revisión.",
        fix="Generá la tabla con roles de fila y celda apropiados y validá el árbol resultante con una herramienta especializada.",
    ),
    "accessibility.pdf.structure_checked": IssueCode(
        meaning="Se inspeccionó el árbol lógico para buscar encabezados, alternativas de figuras y semántica de tablas; es evidencia técnica, no una conclusión de conformidad.",
        fix="Tomalo como evidencia informativa y complementalo con auditorías estructurales y visuales especializadas si necesitás evaluar accesibilidad PDF.",
    ),
    "render.browser.unavailable": IssueCode(
        meaning="No se pudo ejecutar el navegador headless; la verificación HTML quedó limitada a evidencia estática.",
        fix="Instalá Playwright y su navegador Chromium, o tratá el hallazgo como una degradación explícita del entorno.",
    ),
    "render.browser.checked": IssueCode(
        meaning="Se inspeccionó el HTML en un navegador headless y se recolectó evidencia de layout por viewport.",
        fix="Es un hallazgo informativo; revisá cualquier hallazgo asociado de overflow, blank o accesibilidad.",
    ),
    "render.browser.horizontal_overflow": IssueCode(
        meaning="El contenido renderizado excede horizontalmente el viewport del navegador.",
        fix="Corregí el layout responsive o el contenido que provoca overflow y repetí la verificación.",
    ),
    "render.browser.excessive_height": IssueCode(
        meaning="El contenido renderizado resulta inusualmente alto para el viewport inspeccionado.",
        fix="Revisá bucles de layout, contenido expandido y estilos que generen altura inesperada.",
    ),
    "render.browser.blank": IssueCode(
        meaning="El navegador no encontró texto visible en el viewport inspeccionado.",
        fix="Comprobá que el HTML tenga contenido visible después de ejecutar estilos y scripts.",
    ),
    "render.capability.unavailable": IssueCode(
        meaning="La verificación de render multiformato no está configurada, por lo que la calidad del artefacto no pudo comprobarse.",
        fix="Configurá e inyectá el puerto de verificación de render para el formato solicitado y repetí la etapa de revisión.",
    ),
    "render.open": IssueCode(
        meaning="El artefacto renderizado no existe o no pudo abrirse para realizar la verificación solicitada.",
        fix="Comprobá que el build generó el archivo esperado y que el formato, permisos y contenido permiten abrirlo; luego reconstruí y revisá de nuevo.",
    ),
    "render.profile.invalid": IssueCode(
        meaning="La configuración del perfil de QA visual contiene opciones con tipos o dimensiones inválidas.",
        fix="Corregí `visual_qa` para usar booleanos en sus opciones y dos dimensiones numéricas positivas en `expected_page_size`, luego repetí la revisión.",
    ),
    "render.failed": IssueCode(
        meaning="La verificación del render encontró uno o más defectos bloqueantes en el artefacto visual.",
        fix="Revisá los hallazgos por página, corregí el origen en la fuente o plantilla y reconstruí el artefacto antes de publicar.",
    ),
    "render.previews.required": IssueCode(
        meaning="La política de QA exige previews por página, pero el renderer no produjo ninguna.",
        fix="Habilitá el renderer requerido y sus herramientas, o ajustá explícitamente la política si el formato no admite previews.",
    ),
    # --- reproducibility ---------------------------------------------------
    "reproducibility.failed": IssueCode(
        meaning="La reconstrucción del artefacto no coincide con el artefacto original.",
        fix="Revisá las entradas, el renderer y cualquier fuente de datos no determinista hasta que ambas salidas coincidan.",
    ),
    "visual.baseline_unreadable": IssueCode(
        meaning="La comparación visual no pudo ejecutarse porque faltan previews legibles del artefacto.",
        fix="Generá previews válidas antes de comparar contra la baseline y verificá que el directorio de QA sea accesible.",
    ),
    # --- scope --------------------------------------------------------------
    "scope.excluded_section": IssueCode(
        meaning="La sección incluye un apartado que el alcance del documento excluye explícitamente.",
        fix="Quitá el apartado, o corregí el alcance si la exclusión ya no aplica.",
    ),
    "scope.undelimited_ecosystem": IssueCode(
        meaning="Se menciona un ecosistema amplio sin acotarlo al foco que el documento declara.",
        fix="Delimitá la mención al foco declarado; el hallazgo nombra el término y el foco esperado.",
    ),
    # --- structure ----------------------------------------------------------
    "structure.missing_section": IssueCode(
        meaning="El template declara una sección obligatoria que todavía no existe en disco.",
        fix="Creala con `docs build-section <id>` y después redactá su cuerpo.",
    ),
    "structure.missing_sections_dir": IssueCode(
        meaning="No existe el directorio `sections/` del documento.",
        fix="Corré `docs document prepare`, que lo crea junto con los scaffolds de todas las secciones.",
    ),
    "structure.missing_title": IssueCode(
        meaning="El cuerpo de la sección no arranca con un título Markdown de primer nivel.",
        fix="Agregá el encabezado `# Título` al inicio del cuerpo, debajo del header gestionado por el arnés.",
    ),
    # --- template -----------------------------------------------------------
    "template.duplicate_topic_id": IssueCode(
        meaning="Dos temas de `context_schema` comparten el mismo `id`.",
        fix="Renombrá uno: el `id` es la clave con la que `context set` guarda y lee cada tema.",
    ),
    "template.incomplete_field": IssueCode(
        meaning="Un campo del template quedó con un marcador `TODO` o nulo sin completar.",
        fix="Completá el campo que el hallazgo nombra. `docs template init` deja estos marcadores a propósito.",
    ),
    "template.invalid_field": IssueCode(
        meaning="Un campo del template no respeta el tipo o la forma que el esquema exige.",
        fix="Corregí el campo según el mensaje de validación que acompaña al hallazgo.",
    ),
    "template.unknown_key": IssueCode(
        meaning="Una clave del template se parece mucho a un campo real pero no es ninguno, en un contrato de sección o en un bloque de configuración (`format`, `paths`, `output`...).",
        fix="Corregí la clave al nombre que el hallazgo sugiere. Mientras no coincida, el arnés la ignora: la regla o el valor que declaraste no se aplica. Si quedó de una versión anterior y la querés conservar como nota, prefijala con `_`.",
    ),
    "template.missing_blocks": IssueCode(
        meaning="Al template le faltan bloques de primer nivel obligatorios.",
        fix="Agregá los bloques que el hallazgo enumera; `docs template init` genera un esqueleto con todos.",
    ),
    "template.contract.invalid": IssueCode(
        meaning="El contrato de fidelidad declara una regla con una forma o valor que el auditor no puede ejecutar.",
        fix="Corregí la forma declarada en `template_contract` y respetá los tipos indicados por el hallazgo.",
    ),
    # --- voice --------------------------------------------------------------
    "voice.first_person": IssueCode(
        meaning="El texto usa primera persona u otra voz que el template no permite.",
        fix="Reescribí en la voz que exige el template (habitualmente impersonal o tercera persona).",
    ),
    "voice.subjective_term": IssueCode(
        meaning="Aparece un término valorativo que ninguna evidencia automática respalda.",
        fix="Sustituilo por una afirmación verificable, o respaldalo con evidencia citable.",
    ),
}


def _render(code: str, entry: IssueCode) -> str:
    family = ISSUE_CODE_FAMILIES.get(code.split(".")[0], "")
    lines = [f"## `{code}`"]
    if family:
        lines.append(f"_Familia:_ {family}")
    lines += ["", f"**Qué significa:** {entry.meaning}", "", f"**Cómo se resuelve:** {entry.fix}"]
    return "\n".join(lines)


def explain_code(code: str | None) -> str:
    """Render one catalog entry, the whole catalog, or a near-match hint.

    `None` lists everything (grouped by family, so the output reads as a
    reference rather than a dump). An unknown code suggests the closest
    real ones instead of a bare "desconocido" -- an agent quoting a code
    from a truncated log is the common case, and a dead end there costs a
    whole turn.
    """
    if code is None:
        blocks = ["# Códigos de hallazgo del ciclo de revisión", ""]
        for family, description in ISSUE_CODE_FAMILIES.items():
            blocks.append(f"# {family} — {description}")
            blocks.append("")
            for name in sorted(c for c in ISSUE_CODES if c.split(".")[0] == family):
                blocks.append(_render(name, ISSUE_CODES[name]))
                blocks.append("")
        return "\n".join(blocks).rstrip() + "\n"

    entry = ISSUE_CODES.get(code)
    if entry is not None:
        return _render(code, entry) + "\n"

    close = difflib.get_close_matches(code, sorted(ISSUE_CODES), n=3, cutoff=0.4)
    if not close:
        close = sorted(c for c in ISSUE_CODES if c.startswith(code.split(".")[0]))[:3]
    hint = "\n".join(f"- `{name}`" for name in close)
    suggestion = f"\n\n¿Quisiste decir?\n{hint}" if hint else ""
    return (
        f"Código desconocido: `{code}`.{suggestion}\n\n"
        f"Corré `docs explain` sin argumentos para ver el catálogo completo.\n"
    )
