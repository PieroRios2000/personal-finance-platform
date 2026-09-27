"""A cold-start category guesser (T51): matches common wording on real Peruvian bank
statements to a category, so the labeling file (`categorization/labels.py`) starts with
a suggestion for every description instead of a blank column.

This is not the model: it is what proposes a first guess before any label exists to
train one on, and stays as the fallback when the trained model (T52) says it isn't
confident. A general-knowledge, generic keyword list -- verified against synthetic
descriptions, never against the owner's real ones (ADR 0004).
"""

import re

UNKNOWN = "Sin categorizar"

# Ordered: the first pattern that matches wins, so a more specific rule (a named
# streaming service) goes before a more general one (any recurring "SERVICIO" charge).
_RULES: tuple[tuple[str, str], ...] = (
    (r"NETFLIX|SPOTIFY|DISNEY|HBO|YOUTUBE\s*PREMIUM|PRIME\s*VIDEO", "Entretenimiento"),
    (r"UBER|CABIFY|DIDI|TAXI|PEAJE|GRIFO|PETROPERU|PRIMAX|REPSOL", "Transporte"),
    (
        r"PLAZA\s*VEA|WONG|METRO|TOTTUS|VIVANDA|MERCADO|MINIMARKET|SUPERMERCADO",
        "Alimentacion",
    ),
    (r"RESTAURANT|RAPPI|PEDIDOSYA|DELIVERY|CHIFA|POLLERIA", "Restaurantes"),
    (r"FARMACIA|BOTICA|CLINICA|HOSPITAL|SEGURO\s*SALUD|EPS", "Salud"),
    (
        r"LUZ\s*DEL\s*SUR|SEDAPAL|CALIDDA|CLARO|MOVISTAR|ENTEL|BITEL|INTERNET",
        "Servicios",
    ),
    (
        r"UNIVERSIDAD|INSTITUTO|COLEGIO|PENSION\s*ESCOLAR|PLATZI|UDEMY|COURSERA",
        "Educacion",
    ),
    (r"ALQUILER|ARRIENDO|INMOBILIARIA", "Vivienda"),
    (r"COMISION|ITF|MANTENIMIENTO\s*DE\s*CUENTA|PORTES", "Comisiones bancarias"),
    (r"SUELDO|PLANILLA|HONORARIOS|ABONO\s*DE\s*REMUNERACION", "Ingreso"),
    (r"PAGO\s*TARJETA|PAGO\s*DE\s*TC", "Pago de tarjeta"),
    (r"TRANSFERENCIA|INTERBANK\s*A|TRANSF\.?\s*A\s*TERCEROS", "Transferencias"),
)
_COMPILED = tuple((re.compile(pattern), category) for pattern, category in _RULES)


def guess(description: str) -> str:
    """The first category whose pattern matches `description` (already normalized,
    upper case), or `UNKNOWN` if none does."""
    for pattern, category in _COMPILED:
        if pattern.search(description):
            return category
    return UNKNOWN
