def analyze_momentum(rsi, macd, signal):
    score = 0
    reasons = []

    # RSI
    if rsi < 35:
        score += 2
        reasons.append("RSI oversold")

    elif rsi > 65:
        score -= 2
        reasons.append("RSI overbought")

    else:
        reasons.append("RSI neutral")

    # MACD
    if macd > signal:
        score += 3
        reasons.append("MACD bullish crossover")

    else:
        score -= 3
        reasons.append("MACD bearish crossover")

    return score, reasons
