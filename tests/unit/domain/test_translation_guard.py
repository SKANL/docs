from docs.domain.translation_guard import guarded_translate


def test_a_normal_translation_is_returned_and_marked_translated():
    outcome = guarded_translate("Hello", "en", "es", lambda _: "Hola")
    assert outcome == ("Hola", True)


def test_an_empty_response_is_retried_once_then_passes_through():
    calls = []

    def call(text):
        calls.append(text)
        return ""

    outcome = guarded_translate("Hello", "en", "es", call)
    assert len(calls) == 2, "must retry exactly once"
    assert outcome.text == "Hello"
    assert outcome.translated is False


def test_a_retry_that_succeeds_is_used():
    responses = iter(["", "Hola"])
    outcome = guarded_translate("Hello", "en", "es", lambda _: next(responses))
    assert outcome == ("Hola", True)


def test_a_refusal_passes_the_original_through_and_never_raises():
    def refuse(_):
        return "I cannot help with translating this content."

    outcome = guarded_translate("Hello", "en", "es", refuse)
    assert outcome.text == "Hello"
    assert outcome.translated is False


def test_a_spanish_refusal_is_recognised_too():
    outcome = guarded_translate("Hello", "en", "es", lambda _: "No puedo ayudarte con eso.")
    assert outcome.translated is False


def test_an_exception_from_the_engine_never_escapes():
    def explode(_):
        raise RuntimeError("provider is down")

    outcome = guarded_translate("Hello", "en", "es", explode)
    assert outcome.text == "Hello"
    assert outcome.translated is False


def test_an_unchanged_response_counts_as_not_translated():
    outcome = guarded_translate("Hello", "en", "es", lambda text: text)
    assert outcome.translated is False


def test_whitespace_only_input_is_passed_through_without_calling_the_engine():
    called = False

    def call(_):
        nonlocal called
        called = True
        return "x"

    outcome = guarded_translate("   ", "en", "es", call)
    assert called is False
    assert outcome.text == "   "


def test_a_translation_that_merely_mentions_cannot_is_not_a_refusal():
    """The refusal markers anchor at the START of the response on purpose: a
    real translation containing the word "cannot" must survive."""
    outcome = guarded_translate("No puedo abrirlo", "es", "en", lambda _: "I cannot open it")
    assert outcome.translated is True
    assert outcome.text == "I cannot open it"


def test_an_unchanged_response_counts_as_translated_when_the_engine_says_so():
    """A filled slot stating "this text is the same in both languages" -- a
    number, a proper noun, a code snippet -- is a real decision, not a
    failure. Reporting it as untranslated would call a complete document
    broken and re-request the same blocks forever."""
    outcome = guarded_translate("42", "en", "es", lambda text: text, accept_unchanged=True)
    assert outcome == ("42", True)


def test_accept_unchanged_still_rejects_an_empty_response():
    outcome = guarded_translate("Hello", "en", "es", lambda _: "", accept_unchanged=True)
    assert outcome.translated is False


def test_accept_unchanged_still_rejects_a_refusal():
    outcome = guarded_translate(
        "Hello", "en", "es", lambda _: "I cannot help with that.", accept_unchanged=True
    )
    assert outcome.translated is False


def test_the_safe_default_is_to_reject_an_echo():
    """A LIVE engine echoing its input did not translate, it repeated."""
    outcome = guarded_translate("Hello", "en", "es", lambda text: text)
    assert outcome.translated is False

