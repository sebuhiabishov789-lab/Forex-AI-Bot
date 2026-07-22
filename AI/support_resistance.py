def analyze_support_resistance(price, support, resistance):
    score = 0
    reasons = []

    if price <= support * 1.001:
        score += 2
        reasons.append("Price is near support")

    elif price >= resistance * 0.999:
        score -= 2
        reasons.append("Price is near resistance")

    return score, reasons
