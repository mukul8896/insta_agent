import telegram
import os
import requests

TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_BOT_CHAT_ID")
TELEGRAM_MAX_LEN = 4096  # Telegram hard cap

def split_for_telegram(text: str, chunk_size: int = TELEGRAM_MAX_LEN):
    """Yield chunks to respect Telegram message size limits."""
    while text:
        yield text[:chunk_size]
        text = text[chunk_size:]

async def send_to_telegram(bot: telegram.Bot, message: str):
    """Send message with Markdown parse mode and chunking."""
    for chunk in split_for_telegram(message):
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=chunk,
            parse_mode="Markdown"  # for *bold* formatting
        )

def fmt_price(val):
    return "N/A" if val in (None, "", "null") else str(val)


def send_image_to_telegram(image_path, caption='Your image post is ready!',token=None):
    """
    Sends an image file to a specified Telegram chat.
    """
    url = f'https://api.telegram.org/bot{token}/sendPhoto'
    with open(image_path, 'rb') as image_file:
        files = {'photo': image_file}
        data = {'chat_id': TELEGRAM_CHAT_ID, 'caption': caption}
        
        try:
            response = requests.post(url, files=files, data=data)
            response.raise_for_status()  # Raise an exception for bad status codes
            print("Image sent to Telegram successfully!")
        except requests.exceptions.RequestException as e:
            print(f"Failed to send image: {e}")

async def send_portfolio_analysis(bot: telegram.Bot, analysis_json: dict):
    """Send formatted portfolio analysis according to the strict JSON schema."""
    # 1) Per-holding analysis
    portfolio_analysis = analysis_json.get("portfolio_analysis", [])
    for holding in portfolio_analysis:
        msg = (
            f"📌 *{holding.get('ticker','')}*\n"
            f"Decision: {holding.get('final_decision','')} "
            f"({holding.get('confidence','')} confident)\n"
            f"Reason: {holding.get('reason','')}\n"
            f"Exit Price: {fmt_price(holding.get('EXIT_PRICE'))}\n"
            f"Buy Price: {fmt_price(holding.get('BUY_PRICE'))}\n"
        )
        relocate = holding.get("relocate_fund_to")
        if relocate:
            msg += (
                f"💡 Relocate to: {relocate.get('ticker','')} "
                f"at {fmt_price(relocate.get('BUY_PRICE'))}\n"
                f"Reason: {relocate.get('reason','')}\n"
            )
        await send_to_telegram(bot, msg)

    # 2) Additional Ideas
    long_term = analysis_json.get("etf_recommendations", [])
    if long_term:
        msg_lines = ["🌟 *ETF Allocation Recommendation:*"]
        for s in long_term:
            msg_lines.append(
                f"\n*{s.get('etf_name','')}* at {fmt_price(s.get('amount'))}\n"
                f"Reason: {s.get('reason','')}"
            )
        await send_to_telegram(bot, "\n".join(msg_lines))

    # 3) Swing trades
    swings = analysis_json.get("top_5_swing_trade_stocks", []) or \
             analysis_json.get("swing_trade_stocks", [])
    if swings:
        msg_lines = ["⚡ *Safe Swing Trades:*"]
        for s in swings:
            msg_lines.append(
                f"\n*{s.get('ticker','')}* at {fmt_price(s.get('BUY_PRICE'))}\n"
                f"({s.get('confidence','')} confident)\n"
                f"Reason: {s.get('reason','')}"
            )
        await send_to_telegram(bot, "\n".join(msg_lines))