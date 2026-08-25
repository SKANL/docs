# src/docs/domain/translation_guard.py
"""The rule that a model never gets a vote on whether to translate.

A translator that declines is a broken tool. This module is the harness-side
half of that promise: the model sees one block and a target language, and
whatever comes back, the RUN CONTINUES. A refusal, an empty answer, an
exception or an unchanged string all degrade exactly one block -- the original
text passes through and the block is counted -- and the caller reports the
count in its own pipeline line.

Nothing here instructs the model. These are harness mechanics, which is the
point: an instruction can be ignored, a code path cannot.

Pure logic. No I/O, no imports from other layers.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

_ATTEMPTS = 2

# Matched case-insensitively against the START of the response.
#
# These name the REFUSAL OF A TASK ("I cannot help", "no puedo traducir"), not
# mere inability ("I cannot open it") -- because "I cannot open it" is a
# perfectly good translation of "No puedo abrirlo", and a marker list built on
# the bare "i cannot" prefix throws that correct translation away.
#
# The asymmetry that sets the width of this list: letting a refusal through
# prints boilerplate INTO the document, while a false positive merely leaves
# one block untranslated and counted. So err toward catching refusals, but not
# so wide that ordinary sentences trip it.
_REFUSAL_PREFIXES = (
    "i cannot help",
    "i cannot assist",
    "i cannot translate",
    "i cannot provide",
    "i can't help",
    "i can't assist",
    "i can't translate",
    "i won't help",
    "i won't translate",
    "i am unable to help",
    "i am unable to translate",
    "i'm unable to help",
    "i'm unable to translate",
    "i apologize, but i",
    "sorry, but i can",
    "as an ai",
    "no puedo ayudar",
    "no puedo traducir",
    "no puedo asistir",
    "lo siento, pero no puedo",
    "lo siento, no puedo",
)


class TranslationOutcome(NamedTuple):
    text: str
    translated: bool


def _is_refusal(response: str) -> bool:
    lowered = response.strip().lower()
    return any(lowered.startswith(prefix) for prefix in _REFUSAL_PREFIXES)


def _usable(response: str, original: str, accept_unchanged: bool) -> bool:
    stripped = response.strip()
    if not stripped:
        return False
    if not accept_unchanged and stripped == original.strip():
        return False
    return not _is_refusal(stripped)


def guarded_translate(
    block_text: str,
    source_lang: str,
    target_lang: str,
    call: Callable[[str], str],
    accept_unchanged: bool = False,
) -> TranslationOutcome:
    """Translate `block_text`, or pass it through unchanged. Never raises.

    Exactly one retry: a transient hiccup deserves a second chance, a
    systematic refusal does not deserve a third.

    `source_lang` and `target_lang` are part of the signature so the caller
    cannot invoke this without having decided them; `call` is expected to
    close over them.

    `accept_unchanged` decides what an echoed input means, and the answer
    genuinely differs by engine:

    - A LIVE engine echoing its input is a failure mode -- it did not
      translate, it repeated. Default `False` catches that.
    - An engine reading an EXPLICITLY FILLED slot is stating intent: "1",
      "ACME" and `curl -X POST` are identical in every language, and marking
      them untranslated forever would report a correct document as broken.
      Such an engine passes `True`.

    Getting this wrong is not cosmetic. Reporting a fully translated document
    as `4/16` is the kind of misleading degradation signal this harness exists
    to avoid.
    """
    if not block_text.strip():
        return TranslationOutcome(block_text, False)

    for _ in range(_ATTEMPTS):
        try:
            response = call(block_text)
        except Exception:
            # The engine being down degrades a block, never the document.
            continue
        if _usable(response, block_text, accept_unchanged):
            return TranslationOutcome(response.strip(), True)

    return TranslationOutcome(block_text, False)
