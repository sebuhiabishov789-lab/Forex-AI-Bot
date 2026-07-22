def analyze_volatility(price, upper, lower, adx):
    score = 0
    reasons = []

    # Bollinger Bands
    if price <= lower:
        score += 1
        reasons.append("Price at lower Bollinger Band")

    elif price >= upper:
        score -= 1
        reasons.append("Price at upper Bollinger Band")

    # ADX
    if adx >= 25:
        score += 2
        reasons.append("Strong trend (ADX >= 25)")

    elif adx < 20:
        score -= 2
        reasons.append("Weak trend (ADX < 20)")

    else:
        reasons.append("Moderate trend (20 <= ADX < 25)")

    return score, reasons
