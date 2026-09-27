"""Reference tax calculator for BucketShare tax tables (Python 3.9, standard library only).

It reads one tax table (presets/v1/tax/*.json) and returns the yearly estimate for a gross
income. validate.py uses it to re-check every sample. The app's estimator (Stage 11) must
produce the same figures. Money is Decimal throughout; results are rounded to cents.
"""
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_FLOOR

CENT = Decimal("0.01")


def D(value):
    return Decimal(str(value))


def banded(amount, bands):
    """Progressive bands: each rate applies to the slice above its `over` up to the next band.
    A band with appliesTo "total" charges its rate on the whole amount instead, and a band with
    baseAmount charges that amount plus its rate on the excess."""
    ordered = sorted(bands, key=lambda b: D(b["over"]))
    top = None
    for band in ordered:
        if amount > D(band["over"]):
            top = band
    if top is not None and top.get("appliesTo") == "total":
        return amount * D(top["rate"])
    if top is not None and "baseAmount" in top:
        # Published schedules state a rounded amount for the bands below ("$9,028 plus 17c").
        return D(top["baseAmount"]) + (amount - D(top["over"])) * D(top["rate"])
    total = Decimal(0)
    for i, band in enumerate(ordered):
        low = D(band["over"])
        high = D(ordered[i + 1]["over"]) if i + 1 < len(ordered) else None
        if amount <= low:
            break
        slice_top = amount if high is None else min(amount, high)
        total += (slice_top - low) * D(band["rate"])
    return total


def schedule(entry, gross, taxable):
    base = taxable if entry.get("base") == "taxable" else gross
    exempt = entry.get("exemptAtOrBelow")
    if exempt is not None and base <= D(exempt):
        return Decimal(0)
    charged = min(base, D(entry["ceiling"])) if "ceiling" in entry else base
    value = banded(charged, entry["bands"])
    if exempt is not None and "shadeInRate" in entry:
        value = min(value, (base - D(exempt)) * D(entry["shadeInRate"]))
    return max(value, Decimal(0))


def piecewise(points, x):
    pts = sorted(((D(p["income"]), D(p["amount"])) for p in points))
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def formula_tax(formula, taxable):
    x = taxable.to_integral_value(rounding=ROUND_FLOOR)
    zone = None
    for z in sorted(formula["zones"], key=lambda z: D(z["over"])):
        if x > D(z["over"]):
            zone = z
    tax = Decimal(0)
    if zone is not None and zone["type"] == "quadratic":
        y = (x - D(zone["base"])) / Decimal(10000)
        tax = (D(zone["a"]) * y + D(zone["b"])) * y + D(zone.get("c", "0"))
    elif zone is not None and zone["type"] == "linear":
        tax = D(zone["rate"]) * x - D(zone["minus"])
    if formula.get("roundDown", False):
        tax = tax.to_integral_value(rounding=ROUND_FLOOR)
    return max(tax, Decimal(0))


def estimate(table, gross):
    gross = D(gross)
    social = sum((schedule(s, gross, gross) for s in table.get("socialContributions", [])), Decimal(0))
    deductible = sum((schedule(s, gross, gross) for s in table.get("socialContributions", []) if s.get("deductible")), Decimal(0))
    allowances = Decimal(0)
    for d in table.get("deductions", []):
        amount = D(d["amount"])
        if "taperStart" in d and gross > D(d["taperStart"]):
            amount = max(Decimal(0), amount - (gross - D(d["taperStart"])) * D(d["taperRate"]))
        allowances += amount
    if table.get("deductSocialContributions"):
        allowances += deductible
    taxable = max(Decimal(0), gross - allowances)

    if "formula" in table:
        tax = formula_tax(table["formula"], taxable)
        lowest = Decimal(0)
    else:
        tax = banded(taxable, table["brackets"])
        rates = [D(b["rate"]) for b in table["brackets"] if D(b["rate"]) > 0]
        lowest = min(rates) if rates else Decimal(0)
    for c in table.get("credits", []):
        tax -= D(c["amount"]) * (lowest if c.get("atLowestRate") else Decimal(1))
    tax = max(tax, Decimal(0))
    for o in table.get("offsets", []):
        tax = max(Decimal(0), tax - piecewise(o["points"], taxable))
    rebate = table.get("rebate")
    if rebate:
        limit = D(rebate["maxIncome"])
        if taxable <= limit:
            tax = max(Decimal(0), tax - D(rebate["maxAmount"]))
        elif rebate.get("marginalRelief"):
            tax = min(tax, taxable - limit)
    surcharge = table.get("surcharge")
    if surcharge:
        rate = Decimal(0)
        for band in surcharge["bands"]:
            if taxable > D(band["over"]):
                rate = D(band["rate"])
        tax += tax * rate
    for s in table.get("taxSurcharges", []):
        tax += tax * D(s["rate"])
    levies = sum((schedule(l, gross, taxable) for l in table.get("levies", [])), Decimal(0))

    def r(v):
        return v.quantize(CENT, rounding=ROUND_HALF_EVEN)
    tax, levies, social = r(tax), r(levies), r(social)
    return {"taxable": r(taxable), "incomeTax": tax, "levies": levies, "socialContributions": social,
            "net": r(gross - tax - levies - social)}


def student_loan(table, plan, income):
    for loan in table.get("studentLoans", []):
        if loan["name"] == plan:
            return banded(D(income), loan["bands"]).quantize(CENT, rounding=ROUND_HALF_EVEN)
    raise KeyError(plan)
