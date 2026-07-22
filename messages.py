def create_message(
    symbol,
    price,
    decision,
    confidence,
    reasons,
    trade
):

    if decision == "BUY":
        decision_text = "AL"

    elif decision == "SELL":
        decision_text = "SAT"

    else:
        decision_text = "SAXLA"

    message = f"""
Forex AI Siqnal

Cutluk: {symbol}
Qiymet: {price:.5f}

Qerar: {decision_text}
Etibar: {confidence:.2f}%

Sebebler:
"""

    for reason in reasons:
        message += f"\n- {reason}"

    if trade and decision in ["BUY", "SELL"]:

        message += f"""

Ticaret Plani
-------------

Giris:          {trade['entry']:.5f}
Stop Loss:      {trade['stop_loss']:.5f}
Take Profit 1:  {trade['take_profit_1']:.5f}
Take Profit 2:  {trade['take_profit_2']:.5f}
Risk/Mukafat:   {trade['risk_reward']}
ATR:            {trade['atr']:.5f}
"""

    return message
