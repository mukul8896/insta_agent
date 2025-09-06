from PIL import Image, ImageDraw, ImageFont
import os
import datetime
import re
import random
from prompts.insta_quote_prompt import QUOTES_PROMPT
from llm_api.openaiAPI import call_llm_text_output
from notification.telegram_msg import send_image_to_telegram


def create_quote_post(quote, output_dir="posts", logo_path="logos/ai_robo_logo.png"):
    os.makedirs(output_dir, exist_ok=True)

    # --- Random Background (Black or White) ---
    bg_color_name = random.choice(["black", "black"])
    bg_color = (0, 0, 0) if bg_color_name == "black" else (255, 255, 255)
    text_default_color = (255, 255, 255) if bg_color_name == "black" else (0, 0, 0)
    highlight_color = (255, 230, 50) if bg_color_name == "black" else (255, 140, 0)

    # Create background
    img_size = 1080
    img = Image.new("RGB", (img_size, img_size), color=bg_color)
    draw = ImageDraw.Draw(img)

    # --- Fonts ---
    font_normal_path = "fonts/Lato/Lato-Regular.ttf"
    font_bold_path = "fonts/Lato/Lato-Bold.ttf"
    font_watermark_path = "fonts/Lato/Lato-Italic.ttf"

    font_size = 42
    font_normal = ImageFont.truetype(font_normal_path, font_size)
    font_bold = ImageFont.truetype(font_bold_path, font_size)
    max_width = int(img_size * 0.7)  # reduced width

    # --- Logo + Caption ---
    logo_bottom = 100
    if os.path.exists(logo_path):
        logo = Image.open(logo_path).convert("RGBA")
        logo_width = int(img_size * 0.08)
        aspect_ratio = logo.height / logo.width
        logo_height = int(logo_width * aspect_ratio)
        logo = logo.resize((logo_width, logo_height), Image.LANCZOS)
        logo_x = (img_size - logo_width) // 2
        logo_y = 100
        img.paste(logo, (logo_x, logo_y), logo)
        font_small = ImageFont.truetype(font_watermark_path, 24)
        caption = "AI speaking"
        cap_w = draw.textlength(caption, font=font_small)
        cap_x = (img_size - cap_w) // 2
        cap_y = logo_y + logo_height + 5
        draw.text((cap_x, cap_y), caption, font=font_small, fill=(180, 180, 180))
        logo_bottom = cap_y + 60

    # --- Text Wrapping Helper ---
    def wrap_text(text, font, max_width):
        words = text.split()
        lines, line = [], ""
        for word in words:
            test_line = f"{line} {word}".strip()
            if draw.textlength(test_line, font=font) <= max_width:
                line = test_line
            else:
                lines.append(line)
                line = word
        if line:
            lines.append(line)
        return lines

    # --- Process Quote ---
    raw_lines = quote.split("\n")
    processed_lines, highlight_flags = [], []

    for rl in raw_lines:
        rl = rl.strip()
        highlight = False
        if rl.startswith("{") and rl.endswith("}"):
            rl = rl[1:-1]
            highlight = True

        font_to_use = font_bold if highlight else font_normal
        wrapped = wrap_text(rl, font_to_use, max_width)

        processed_lines.extend(wrapped)
        highlight_flags.extend([highlight] * len(wrapped))

    # --- Center Vertically ---
    line_height = font_normal.getbbox("A")[3] + 25
    text_height = len(processed_lines) * line_height
    y = max((img_size - text_height) / 2, logo_bottom)

    # --- Draw Lines ---
    for line, highlight in zip(processed_lines, highlight_flags):
        font_to_use = font_bold if highlight else font_normal
        w = draw.textlength(line, font=font_to_use)
        x = (img_size - w) / 2
        fill_color = highlight_color if highlight else text_default_color
        draw.text((x, y), line, font=font_to_use, fill=fill_color)
        y += line_height

    # --- Watermark ---
    font_watermark = ImageFont.truetype(font_watermark_path, 30)
    watermark_text = "@mksmindset"
    wm_w = draw.textlength(watermark_text, font=font_watermark)
    wm_x = (img_size - wm_w) / 2
    wm_y = img_size - (line_height // 2) - 60
    draw.text((wm_x, wm_y), watermark_text, font=font_watermark, fill=(180, 180, 180))

    # --- Save ---
    filename = f"{output_dir}/quote_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    img.save(filename)
    print(f"✅ Post saved: {filename}")
    return filename


if __name__ == "__main__":
    print("INFO: Generating Quotes...")

    # Get the AI output
    output = call_llm_text_output(QUOTES_PROMPT)
    print(f"INFO: {output}")

    # Extract quote and hashtags
    match = re.search(r"(.*)\n\[(.*)\]", output, re.DOTALL)
    quote_text = match.group(1).strip()
    hashtags = match.group(2).strip()

    # Create Instagram post image with quote only
    filename = create_quote_post(quote_text)
    send_image_to_telegram(f"{filename}", f"{hashtags}", os.getenv("TELEGRAM_QUOTEBOT_TOKEN"))
