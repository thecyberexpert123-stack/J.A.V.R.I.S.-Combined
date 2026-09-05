"""Guarded desktop awareness (ADR-0022): the read-only tier of the AT-SPI family.

Everything in this package is fail-closed at the data boundary: blocked
applications, password roles withheld before any name read, sensitive-name
redaction, bounded/hygiened walks, and a content-free per-op audit ledger.
"""
