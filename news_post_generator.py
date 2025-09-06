import asyncio
import telegram
import os
import sys
import json
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import textwrap
from notification.telegram_msg import send_image_to_telegram
from utils.news_fetcher import fetch_newapi_articles
from config import MODEL_ID
from llm_api.openaiAPI import call_llm
from prompts.news_analyzer_prompts import ANALYZE_NEWS_ARTICLE_PROMPT,VIRAL_NEWS_SELECTOR_PROMPT


# ----------------- Helper: Download image -----------------
def download_image(url):
    try:
        if url:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                return Image.open(BytesIO(resp.content)).convert("RGB")
    except Exception as e:
        print(f"Image download failed: {e}")
    return None


# ----------------- Pixel wrapping helper -----------------
def wrap_text_by_pixels(draw, text, font, max_width):
    """Wrap text based on pixel width (not characters)."""
    words = text.split()
    if not words:
        return []
    lines, cur = [], words[0]
    for w in words[1:]:
        trial = f"{cur} {w}"
        if draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def multiline_height(draw, lines, font, line_spacing=8):
    """Compute total pixel height of wrapped lines."""
    total = 0
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        h = bbox[3] - bbox[1]
        total += h
        if i < len(lines) - 1:
            total += line_spacing
    return total


# ----------------- Bullet rendering helper -----------------
def measure_bullets(draw, points, font, max_width, line_spacing=8, bullet="• "):
    """Return wrapped-lines per bullet and total height needed."""
    bullet_width = draw.textlength(bullet, font=font)
    text_width = max_width - bullet_width
    all_wrapped = []
    total_h = 0

    for idx, pt in enumerate(points):
        wrapped = wrap_text_by_pixels(draw, pt, font, text_width)
        all_wrapped.append(wrapped)
        # height of this bullet: lines heights + bullet gap after each bullet
        h = multiline_height(draw, wrapped, font, line_spacing)
        total_h += h
        if idx < len(points) - 1:
            total_h += 10  # space between bullets
    return all_wrapped, total_h, bullet_width


def draw_bullet_paragraph(draw, x, y, wrapped_points, font, fill, max_width,
                          bullet="• ", line_spacing=8, between_bullets=10):
    """Draw bullets with first-line bullet only; subsequent lines aligned."""
    bullet_width = draw.textlength(bullet, font=font)
    cur_y = y
    for bi, lines in enumerate(wrapped_points):
        for li, line in enumerate(lines):
            if li == 0:
                # draw bullet + first line
                draw.text((x, cur_y), bullet, font=font, fill=fill)
                draw.text((x + bullet_width, cur_y), line, font=font, fill=fill)
            else:
                draw.text((x + bullet_width, cur_y), line, font=font, fill=fill)
            bbox = draw.textbbox((0, 0), line, font=font)
            line_h = bbox[3] - bbox[1]
            cur_y += line_h + line_spacing
        if bi < len(wrapped_points) - 1:
            cur_y += between_bullets
    return cur_y


# ----------------- Post Generator -----------------
def create_instagram_post(post_count, news_item, analysis_result):
    # Canvas setup
    IMG_W, IMG_H = 1080, 1080
    IMAGE_TARGET_H = int(IMG_H * 0.40)
    BG = (37, 43, 77)

    # square post (no rounded corners)
    final_img = Image.new("RGBA", (IMG_W, IMG_H), BG + (255,))
    draw = ImageDraw.Draw(final_img)

    # Load article image
    article = download_image(news_item.get("urlToImage", ""))

    if article:
        ow, oh = article.size
        ratio = min(IMG_W / ow, IMAGE_TARGET_H / oh)
        nw, nh = int(ow * ratio), int(oh * ratio)
        article = article.resize((nw, nh)).convert("RGBA")

        # Rounded corners ONLY on the image
        corner_radius = 10
        mask = Image.new("L", (nw, nh), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, nw, nh), radius=corner_radius, fill=255)

        # --- ADD: Fade out bottom of image ---
        # fade_h = int(nh * 0.25)  # bottom 25% fades out
        # fade = Image.new("L", (nw, fade_h), 0)
        # for y in range(fade_h):
        #     fade.putpixel((0, y), int(255 * (y / fade_h)))  # top=0 (transparent), bottom=255
        # fade = fade.resize((nw, fade_h))
        # mask.paste(fade, (0, nh - fade_h))  # apply fade at bottom of mask

        article.putalpha(mask)

        paste_x = (IMG_W - nw) // 2
        final_img.alpha_composite(article, (paste_x, 10))
        current_image_height = nh
    else:
        # fallback area if no image
        fallback = Image.new("RGBA", (IMG_W, IMAGE_TARGET_H), BG + (255,))
        final_img.alpha_composite(fallback, (0, 0))
        current_image_height = IMAGE_TARGET_H

    # Smooth gradient transition under image
    # grad_h = int(IMG_H * 0.10)
    # gradient = Image.new("L", (1, grad_h), 0xFF)
    # for y in range(grad_h):
    #     # fade from opaque at top to transparent at bottom
    #     gradient.putpixel((0, y), int(255 * (1 - y / grad_h)))
    # alpha_grad = gradient.resize((IMG_W, grad_h))
    # grad_overlay = Image.new("RGBA", (IMG_W, grad_h), BG + (255,))
    # grad_overlay.putalpha(alpha_grad)
    # final_img.alpha_composite(grad_overlay, (0, current_image_height - grad_h // 2))

    # Fonts (robust paths; adjust to your repo)
    heading_path_bold = "fonts/Roboto/static/Roboto-Bold.ttf"
    watermark_italic = "fonts/Roboto/static/Roboto-SemiBoldItalic.ttf"
    text_path = "fonts/Roboto/static/Roboto_Condensed-SemiBold.ttf"
    watermark_font = ImageFont.truetype(watermark_italic, 35)

    # Content
    heading = (analysis_result.get("heading") or "").upper().strip()
    pointers = [p.strip("{}").strip() for p in analysis_result.get("pointers", [])[:4]]
    pointer_colors = [
        (255, 223, 0) if (p.startswith("{") and p.endswith("}")) else "white"
        for p in analysis_result.get("pointers", [])[:4]
    ]  # not used (since we strip {} above), but kept if you want per-pointer colors later

    # --- NEW WATERMARK POSITION: at the bottom ---
    wm_text = "mks_newslines"
    globe_path = "logos/globe.png"
    globe_img = None
    if os.path.exists(globe_path):
        globe_img = Image.open(globe_path).convert("RGBA")

    ascent, descent = watermark_font.getmetrics()
    text_height = ascent + descent
    text_w = draw.textlength(wm_text, font=watermark_font)
    if globe_img:
        icon_size = int(text_height * 0.90)
        globe_icon = globe_img.resize((icon_size, icon_size), Image.LANCZOS)
    else:
        icon_size = 0
        globe_icon = None

    spacing = 5
    total_w = (icon_size + spacing + text_w) if globe_icon else text_w
    wm_x = int((IMG_W - total_w) // 2)
    wm_y = IMG_H - (text_height + 25) # Position watermark near the bottom

    # Create shadow layer and draw shadows for both icon and text
    shadow_layer = Image.new("RGBA", final_img.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)
    drop_dx, drop_dy = 5, 5
    passes = 6
    blur_radius = 8
    shadow_alpha = 200

    if globe_icon:
        icon_mask = globe_icon.split()[3]
        black_icon = Image.new("RGBA", globe_icon.size, (0, 0, 0, shadow_alpha))
        for offset in range(passes):
            ox = wm_x + drop_dx + offset
            oy = wm_y + drop_dy + offset + int((text_height - icon_size) / 2)
            shadow_layer.paste(black_icon, (ox, oy), icon_mask)

    text_base_x = wm_x + (icon_size + spacing if globe_icon else 0)
    for offset in range(passes):
        shadow_draw.text(
            (text_base_x + drop_dx + offset, wm_y + drop_dy + offset),
            wm_text,
            font=watermark_font,
            fill=(0, 0, 0, shadow_alpha)
        )

    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(blur_radius))
    final_img = Image.alpha_composite(final_img.convert("RGBA"), shadow_layer)
    draw = ImageDraw.Draw(final_img)

    # Draw actual icon + text in white on top
    if globe_icon:
        icon_y = wm_y + (text_height - icon_size) // 2
        final_img.paste(globe_icon, (wm_x + 2, icon_y + 2), globe_icon)
    draw.text((text_base_x, wm_y), wm_text, font=watermark_font, fill="white")
    # --- END NEW WATERMARK POSITION ---

    # --- NEW TEXT LAYOUT: moved up to fit between image and watermark ---
    # Layout box for text (left-aligned)
    left_pad = 60
    bullet_left = 80
    right_pad = 60
    # Calculate available space: from under the image to above the new watermark position
    top_text_start = current_image_height + 15
    bottom_text_end = wm_y - 15
    max_text_w = IMG_W - left_pad - right_pad
    available_h = bottom_text_end - top_text_start

    # Dynamic sizing
    max_heading_part = int(available_h * 0.30)
    min_heading_fs, max_heading_fs = 34, 60
    min_point_fs, max_point_fs = 22, 34

    # Find biggest heading font that fits
    heading_fs = max_heading_fs
    heading_font = ImageFont.truetype(heading_path_bold, heading_fs)
    heading_lines = wrap_text_by_pixels(draw, heading, heading_font, max_text_w)
    while (len(heading_lines) > 3 or multiline_height(draw, heading_lines, heading_font) > max_heading_part) and heading_fs > min_heading_fs:
        heading_fs -= 2
        heading_font = ImageFont.truetype(heading_path_bold, heading_fs)
        heading_lines = wrap_text_by_pixels(draw, heading, heading_font, max_text_w)
    heading_h = multiline_height(draw, heading_lines, heading_font)

    # Now size bullet text so all bullets fit in remaining height
    remaining_h = max(0, available_h - (heading_h + 22))
    point_fs = max_point_fs
    points_font = ImageFont.truetype(text_path, point_fs)
    wrapped_bullets, bullets_h, bullet_width = measure_bullets(draw, pointers, points_font, max_text_w, line_spacing=8)
    while bullets_h > remaining_h and point_fs > min_point_fs:
        point_fs -= 2
        points_font = ImageFont.truetype(text_path, point_fs)
        wrapped_bullets, bullets_h, bullet_width = measure_bullets(draw, pointers, points_font, max_text_w, line_spacing=8)

    # Balance vertical space (center the block within available height)
    total_text_h = heading_h + 22 + bullets_h
    extra_space = max(0, available_h - total_text_h)
    y = top_text_start + extra_space // 2

    # Draw heading (with DROP SHADOW)
    for line in heading_lines:
        shadow_layer = Image.new("RGBA", final_img.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)

        for offset in range(4):
            shadow_draw.text(
                (left_pad + 4 + offset, y + 4 + offset),
                line,
                font=heading_font,
                fill=(0, 0, 0, 200)
            )

        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(6))
        final_img.alpha_composite(shadow_layer)
        draw = ImageDraw.Draw(final_img) # Redraw object after alpha_composite
        draw.text((left_pad, y), line, font=heading_font, fill=(255, 223, 0))

        bbox = draw.textbbox((0, 0), line, font=heading_font)
        y += (bbox[3] - bbox[1]) + 10
    y += 20

    # Draw bullets
    per_pointer_colors = []
    raw_ptrs = analysis_result.get("pointers", [])[:4]
    for p in raw_ptrs:
        per_pointer_colors.append((255, 223, 0) if p.startswith("{") and p.endswith("}") else "white")

    for idx, wrapped in enumerate(wrapped_bullets):
        color = per_pointer_colors[idx] if idx < len(per_pointer_colors) else "white"
        y = draw_bullet_paragraph(draw, bullet_left, y, [wrapped], points_font, color, max_text_w,
                                  bullet="• ", line_spacing=8, between_bullets=10)

    # Save post
    os.makedirs("posts", exist_ok=True)
    filename = f"posts/post{post_count}_{news_item.get('source','source')}.png"
    final_img.save(filename)
    return filename


def generate_caption(news_item, analysis_result):
    pointers_text = "\n".join([f"• {p}" for p in analysis_result['pointers']])
    
    return f"""{analysis_result['heading']}
        {pointers_text}

        🔗 Read more: {news_item['url']}
        📌 Source: {news_item['source']}

        {analysis_result['hashtags']}
    """

# ----------------- Async main (unchanged) -----------------
# In your main function
async def main():
    bot = telegram.Bot(token=os.getenv("TELEGRAM_NEWSBOT_TOKEN"))
    telegram_token = os.getenv("TELEGRAM_QUOTEBOT_TOKEN")
    try:
        # Fetch a broader set of popular articles
        news_data = fetch_newapi_articles(query="BJP")

        # Use the LLM to select the most viral articles from the fetched data
        # Pass the list of articles as a JSON string to the LLM
        articles_for_llm = json.dumps([{"title": n['title'], "url": n['url']} for n in news_data])
        llm_selected_articles = call_llm(VIRAL_NEWS_SELECTOR_PROMPT, articles_for_llm)
        post_count = 0
        
        # Iterate over the LLM-selected articles for posting
        for news in llm_selected_articles:
            # You'll need to fetch the full details for the selected article
            # For simplicity, we'll assume the original 'news_data' contains what we need
            
            # Find the full article data based on the URL from the LLM
            full_article = next((item for item in news_data if item["url"] == news['url']), None)
            
            if full_article:
                analyzed_news = call_llm(ANALYZE_NEWS_ARTICLE_PROMPT, full_article)
                print(f"INFO: {analyzed_news}")
                post_file = create_instagram_post(post_count, full_article, analyzed_news)
                caption = generate_caption(news_item=full_article, analysis_result=analyzed_news)
                send_image_to_telegram(f"{post_file}", f"{caption}", telegram_token)
                post_count += 1
            if post_count == 5:
                break
    finally:
        try:
            if hasattr(bot, "close") and callable(getattr(bot, "close")):
                await bot.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())