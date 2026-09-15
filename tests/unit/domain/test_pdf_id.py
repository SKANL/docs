import hashlib

from docs.domain.pdf_id import normalize_pdf_id

TRAILER = b"trailer\r\n<</Info 33 0 R /Root 1 0 R /Size 38/ID[<%s><%s>]>>\r\n"


def _pdf(id_a: bytes, id_b: bytes, body: bytes = b"body bytes here") -> bytes:
    return b"%PDF-1.4\r\n" + body + b"\r\n" + TRAILER % (id_a, id_b)


def test_same_content_different_random_ids_normalizes_identical():
    a = _pdf(b"DF3B541ACE3E866AAB616FC3D178BA13", b"DF3B541ACE3E866AAB616FC3D178BA13")
    b = _pdf(b"53825174AA5D8408921C42C74CBF5F24", b"53825174AA5D8408921C42C74CBF5F24")
    assert hashlib.sha256(normalize_pdf_id(a)).digest() == hashlib.sha256(normalize_pdf_id(b)).digest()


def test_byte_length_is_preserved_so_xref_offsets_stay_valid():
    raw = _pdf(b"A" * 32, b"B" * 32)
    assert len(normalize_pdf_id(raw)) == len(raw)


def test_different_content_yields_different_id():
    a = normalize_pdf_id(_pdf(b"A" * 32, b"A" * 32))
    b = normalize_pdf_id(_pdf(b"A" * 32, b"A" * 32, body=b"DIFFERENT body"))
    assert a != b


def test_pdf_without_id_array_is_returned_unchanged():
    raw = b"%PDF-1.4\r\nno trailer id here\r\n"
    assert normalize_pdf_id(raw) == raw


def test_normalization_is_idempotent():
    once = normalize_pdf_id(_pdf(b"A" * 32, b"A" * 32))
    assert normalize_pdf_id(once) == once

