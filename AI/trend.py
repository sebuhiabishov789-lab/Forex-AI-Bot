def analyze_trend(price, ema50, ema200):
    score = 0
    reasons = []

    if price > ema50:
        score += 3
        reasons.append("Price above EMA50")
    else:
        score -= 3
        reasons.append("Price below EMA50")

    if price > ema200:
        score += 5
        reasons.append("Price above EMA200")
    else:
        score -= 5
        reasons.append("Price below EMA200")

    return score, reasons
