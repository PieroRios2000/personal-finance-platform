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
#
# No rule here ever needs to recognize a transfer to the owner's *own* other account
# (including paying off his own credit card): `export_category_labels.py` excludes
# every `is_internal_transfer` movement before this guesser ever sees a description
# (ADR 0017), so "TRANSFERENCIA"-style wording that does reach here is, by
# construction, already a transfer to someone else's account.
_RULES: tuple[tuple[str, str], ...] = (
    (r"UBER|CABIFY|DIDI|TAXI|PEAJE|GRIFO|PETROPERU|PRIMAX|REPSOL", "Transporte"),
    (r"RESTAURANT|RAPPI|PEDIDOSYA|DELIVERY|CHIFA|POLLERIA", "Restaurantes"),
    (
        r"PLAZA\s*VEA|WONG|METRO|TOTTUS|VIVANDA|MERCADO|MINIMARKET|SUPERMERCADO",
        "Alimentacion",
    ),
    (
        r"AEROLINEA|LATAM|SKY\s*AIRLINE|AVIANCA|JETSMART|HOTEL|HOSTAL|BOOKING|AIRBNB"
        r"|DESPEGAR|AGENCIA\s*DE\s*VIAJES",
        "Viajes",
    ),
    (
        r"GIMNASIO|GYM|SMARTFIT|BODYTECH|CLUB\s*DEPORTIVO|ACADEMIA\s*DE|PADEL|CROSSFIT",
        "Deporte",
    ),
    (
        r"NETFLIX|SPOTIFY|DISNEY|HBO|YOUTUBE\s*PREMIUM|PRIME\s*VIDEO"
        r"|LUZ\s*DEL\s*SUR|SEDAPAL|CALIDDA|CLARO|MOVISTAR|ENTEL|BITEL|INTERNET"
        r"|FARMACIA|BOTICA|CLINICA|HOSPITAL|SEGURO\s*SALUD|EPS"
        r"|UNIVERSIDAD|INSTITUTO|COLEGIO|PENSION\s*ESCOLAR|PLATZI|UDEMY|COURSERA"
        r"|COMISION|ITF|MANTENIMIENTO\s*DE\s*CUENTA|PORTES",
        "Servicios",
    ),
    (r"SUELDO|PLANILLA|HONORARIOS|ABONO\s*DE\s*REMUNERACION", "Ingresos"),
    (r"TRANSFERENCIA|TRANSF\.?\s*A\s*TERCEROS|ENVIO\s*DE\s*DINERO", "Transferencias"),
)
_COMPILED = tuple((re.compile(pattern), category) for pattern, category in _RULES)


def guess(description: str) -> str:
    """The first category whose pattern matches `description` (already normalized,
    upper case), or `UNKNOWN` if none does."""
    for pattern, category in _COMPILED:
        if pattern.search(description):
            return category
    return UNKNOWN
