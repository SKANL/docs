"""`docs.templates` — package-data namespace for built-in document templates.

Real package (has `__init__.py`, matching every other `docs` subpackage) so
`importlib.resources.files("docs.templates.builtin")` resolves reliably from
an installed wheel, not just a repo checkout (design.md item C, ADR-C).
"""
