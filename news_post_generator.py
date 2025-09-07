import asyncio
import telegram
import os
import sys
import json
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops
import textwrap
from notification.telegram_msg import send_image_to_telegram
from utils.news_fetcher import fetch_newapi_articles
from config import MODEL_ID
from llm_api.openaiAPI import call_llm
from prompts.news_analyzer_prompts import ANALYZE_NEWS_ARTICLE_PROMPT, VIRAL_NEWS_SELECTOR_PROMPT

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

def multiline_height(draw, lines, font, line_spacing=12):
    """Compute total pixel height of wrapped lines."""
    total = 0
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        h = bbox[3] - bbox[1]
        total += h
        if i < len(lines) - 1:
            total += line_spacing
    return total

# ----------------- Dynamic font sizing helper -----------------
def find_optimal_font_size(draw, text, font_path, max_width, max_height, min_size, max_size, 
                           max_lines=None, line_spacing=12):
    """Find the optimal font size that fits within constraints."""
    best_size = min_size
    best_lines = []
    
    for size in range(max_size, min_size - 1, -1):
        font = ImageFont.truetype(font_path, size)
        lines = wrap_text_by_pixels(draw, text, font, max_width)
        
        # Check line count constraint
        if max_lines and len(lines) > max_lines:
            continue
            
        # Check height constraint
        height = multiline_height(draw, lines, font, line_spacing)
        if height <= max_height:
            best_size = size
            best_lines = lines
            break
    
    return best_size, best_lines

# ----------------- Bullet rendering helper -----------------
def measure_bullets(draw, points, font, max_width, line_spacing=12, between_bullets=20, bullet="• "):
    """Return wrapped-lines per bullet and total height needed."""
    bullet_width = draw.textlength(bullet, font=font)
    text_width = max_width - bullet_width
    all_wrapped = []
    total_h = 0
    
    for idx, pt in enumerate(points):
        wrapped = wrap_text_by_pixels(draw, pt, font, text_width)
        all_wrapped.append(wrapped)
        h = multiline_height(draw, wrapped, font, line_spacing)
        total_h += h
        if idx < len(points) - 1:
            total_h += between_bullets
    
    return all_wrapped, total_h, bullet_width

def draw_bullet_paragraph(final_img, draw, x, y, wrapped_points, font, fills, max_width, 
                         bullet="• ", line_spacing=12, between_bullets=25):
    """Draw bullets with cloud-like shadow and proper spacing."""
    bullet_width = draw.textlength(bullet, font=font)
    cur_y = y
    
    # Normalize fills to a list matching number of bullets
    if isinstance(fills, (list, tuple)):
        fills_list = list(fills)
    else:
        fills_list = [fills] * len(wrapped_points)
    
    for bi, lines in enumerate(wrapped_points):
        color = fills_list[bi] if bi < len(fills_list) else fills_list[-1]
        indent_x = x + bullet_width
        
        for li, line in enumerate(lines):
            if li == 0:
                text_x = x
                full_line = bullet + line
            else:
                text_x = indent_x
                full_line = line
            
            # Cloud-like shadow layer
            shadow_layer = Image.new("RGBA", final_img.size, (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow_layer)
            
            for offset in range(4):
                shadow_draw.text(
                    (text_x + 4 + offset, cur_y + 4 + offset),
                    full_line,
                    font=font,
                    fill=(0, 0, 0, 200)
                )
            
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(6))
            final_img.alpha_composite(shadow_layer)
            
            # Actual text
            draw.text((text_x, cur_y), full_line, font=font, fill=color)
            
            bbox = draw.textbbox((0, 0), line, font=font)
            line_h = bbox[3] - bbox[1]
            cur_y += line_h + line_spacing
        
        if bi < len(wrapped_points) - 1:
            cur_y += between_bullets
    
    return cur_y

# ----------------- Calculate dynamic layout -----------------
def calculate_dynamic_layout(draw, heading, pointers, fonts_config, dimensions):
    """Calculate optimal layout with dynamic spacing and font sizes."""
    IMG_W, IMG_H = dimensions['width'], dimensions['height']
    IMAGE_H = dimensions['image_height']
    WATERMARK_H = dimensions['watermark_height']
    
    # Available space for text content
    top_margin = 20
    bottom_margin = 30
    watermark_margin = 40  # Extra margin above watermark
    
    content_start_y = IMAGE_H + top_margin
    content_end_y = IMG_H - WATERMARK_H - watermark_margin - bottom_margin
    available_height = content_end_y - content_start_y
    
    # Text area width
    left_pad = 60
    right_pad = 60
    max_text_width = IMG_W - left_pad - right_pad
    
    # Dynamic allocation of space (percentages can be adjusted)
    heading_max_height_ratio = 0.35  # Maximum 35% for heading
    min_bullets_height_ratio = 0.45  # Minimum 45% for bullets
    
    # Find optimal heading font size
    heading_max_height = int(available_height * heading_max_height_ratio)
    heading_font_size, heading_lines = find_optimal_font_size(
        draw, heading,
        fonts_config['heading_path'],
        max_text_width,
        heading_max_height,
        fonts_config['heading_min'],
        fonts_config['heading_max'],
        max_lines=3,
        line_spacing=15
    )
    
    heading_font = ImageFont.truetype(fonts_config['heading_path'], heading_font_size)
    actual_heading_height = multiline_height(draw, heading_lines, heading_font, 15)
    
    # Space between heading and bullets
    heading_bullet_gap = max(25, int(available_height * 0.05))
    
    # Calculate remaining space for bullets
    remaining_height = available_height - actual_heading_height - heading_bullet_gap
    
    # Find optimal bullet font size
    bullet_font_size = fonts_config['bullet_max']
    bullet_font = ImageFont.truetype(fonts_config['bullet_path'], bullet_font_size)
    
    # Adjust bullet spacing based on available space
    line_spacing = 12
    between_bullets = max(20, min(35, int(remaining_height * 0.08)))
    
    wrapped_bullets, bullets_height, bullet_width = measure_bullets(
        draw, pointers, bullet_font, max_text_width, 
        line_spacing=line_spacing, between_bullets=between_bullets
    )
    
    # Reduce font size if bullets don't fit
    while bullets_height > remaining_height and bullet_font_size > fonts_config['bullet_min']:
        bullet_font_size -= 1
        bullet_font = ImageFont.truetype(fonts_config['bullet_path'], bullet_font_size)
        wrapped_bullets, bullets_height, bullet_width = measure_bullets(
            draw, pointers, bullet_font, max_text_width,
            line_spacing=line_spacing, between_bullets=between_bullets
        )
    
    # Calculate vertical centering of content
    total_content_height = actual_heading_height + heading_bullet_gap + bullets_height
    vertical_padding = max(0, (available_height - total_content_height) // 2)
    
    return {
        'heading_font': heading_font,
        'heading_lines': heading_lines,
        'heading_y': content_start_y + vertical_padding,
        'bullet_font': bullet_font,
        'wrapped_bullets': wrapped_bullets,
        'bullets_y': content_start_y + vertical_padding + actual_heading_height + heading_bullet_gap,
        'line_spacing': line_spacing,
        'between_bullets': between_bullets,
        'left_pad': left_pad,
        'bullet_left': left_pad + 20,
        'max_text_width': max_text_width
    }

# ----------------- Post Generator -----------------
def create_instagram_post(post_count, news_item, analysis_result):
    # Canvas setup
    IMG_W, IMG_H = 1080, 1080
    IMAGE_TARGET_H = int(IMG_H * 0.40)
    BG = (37, 43, 77)
    
    final_img = Image.new("RGBA", (IMG_W, IMG_H), BG + (255,))
    draw = ImageDraw.Draw(final_img)
    
    # Load and process article image
    article = download_image(news_item.get("urlToImage", ""))
    if article:
        ow, oh = article.size
        ratio = min(IMG_W / ow, IMAGE_TARGET_H / oh)
        nw, nh = int(ow * ratio), int(oh * ratio)
        article = article.resize((nw, nh)).convert("RGBA")
        
        # Rounded corners
        corner_radius = 10
        mask = Image.new("L", (nw, nh), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, nw, nh), radius=corner_radius, fill=255)
        article.putalpha(mask)
        
        # Create blurred-edge overlay
        blur_radius = 18
        blurred_article = article.filter(ImageFilter.GaussianBlur(blur_radius))
        
        # Create edge mask
        solid_mask = Image.new("L", (nw, nh), 255)
        solid_draw = ImageDraw.Draw(solid_mask)
        inset = int(nw * 0.06)
        solid_draw.rounded_rectangle(
            (inset, inset, nw - inset, nh - inset),
            radius=max(0, corner_radius - inset//4),
            fill=0
        )
        edge_mask = ImageChops.invert(solid_mask)
        edge_mask = edge_mask.filter(ImageFilter.GaussianBlur(int(blur_radius * 0.6)))
        
        blurred_overlay = blurred_article.copy()
        blurred_overlay.putalpha(edge_mask)
        
        paste_x = (IMG_W - nw) // 2
        paste_y = 10
        
        final_img.alpha_composite(blurred_overlay, (paste_x, paste_y))
        final_img.alpha_composite(article, (paste_x, paste_y))
        current_image_height = nh + paste_y
    else:
        fallback = Image.new("RGBA", (IMG_W, IMG_H), BG + (255,))
        final_img.alpha_composite(fallback, (0, 0))
        current_image_height = IMG_H * 0.10
    
    # Font configuration
    fonts_config = {
        'heading_path': "fonts/Roboto/static/Roboto-Bold.ttf",
        'bullet_path': "fonts/Roboto/static/Roboto_Condensed-Regular.ttf",
        'watermark_path': "fonts/Roboto/static/Roboto-SemiBoldItalic.ttf",
        'heading_min': 32,
        'heading_max': 56,
        'bullet_min': 20,
        'bullet_max': 32
    }
    
    # Prepare watermark font for height calculation
    watermark_font = ImageFont.truetype(fonts_config['watermark_path'], 30)
    ascent, descent = watermark_font.getmetrics()
    watermark_height = ascent + descent + 50  # Include margins
    
    # Dimensions for layout calculation
    dimensions = {
        'width': IMG_W,
        'height': IMG_H,
        'image_height': current_image_height,
        'watermark_height': watermark_height
    }
    
    # Content preparation
    heading = (analysis_result.get("heading") or "").upper().strip()
    pointers = [p.strip("{}").strip() for p in analysis_result.get("pointers", [])[:4]]
    
    # Calculate dynamic layout
    layout = calculate_dynamic_layout(draw, heading, pointers, fonts_config, dimensions)
    
    # Draw source text (top-right corner)
    source_text = news_item.get("source", "") or ""
    if source_text:
        small_font = ImageFont.truetype(fonts_config['bullet_path'], 10)
        small_margin = 8
        source_w = draw.textlength(source_text, font=small_font)
        source_x = IMG_W - small_margin - int(source_w)
        source_y = small_margin
        
        # Semi-transparent background
        bbox = draw.textbbox((0, 0), source_text, font=small_font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        
        rect = Image.new("RGBA", (IMG_W, IMG_H), (0, 0, 0, 0))
        rd = ImageDraw.Draw(rect)
        rd.rounded_rectangle(
            (source_x - 8, source_y - 4, source_x + tw + 8, source_y + th + 4),
            radius=6, fill=(0, 0, 0, 120)
        )
        final_img = Image.alpha_composite(final_img, rect)
        draw = ImageDraw.Draw(final_img)
        draw.text((source_x, source_y), source_text, font=small_font, fill=(255, 255, 255, 220))
    
    # Draw heading with dynamic positioning
    y = layout['heading_y']
    for line in layout['heading_lines']:
        # Shadow effect
        shadow_layer = Image.new("RGBA", final_img.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        for offset in range(4):
            shadow_draw.text(
                (layout['left_pad'] + 4 + offset, y + 4 + offset),
                line,
                font=layout['heading_font'],
                fill=(0, 0, 0, 200)
            )
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(6))
        final_img.alpha_composite(shadow_layer)
        draw = ImageDraw.Draw(final_img)
        
        # Draw heading text
        draw.text((layout['left_pad'], y), line, font=layout['heading_font'], fill=(255, 223, 0))
        bbox = draw.textbbox((0, 0), line, font=layout['heading_font'])
        y += (bbox[3] - bbox[1]) + 15
    
    # Draw bullets with dynamic spacing
    bullet_colors = [(255, 255, 255)] * len(layout['wrapped_bullets'])
    draw_bullet_paragraph(
        final_img, draw,
        layout['bullet_left'],
        layout['bullets_y'],
        layout['wrapped_bullets'],
        layout['bullet_font'],
        bullet_colors,
        layout['max_text_width'],
        bullet="• ",
        line_spacing=layout['line_spacing'],
        between_bullets=layout['between_bullets']
    )
    
    # Draw watermark at bottom with proper spacing
    wm_text = "mks_newslines"
    globe_path = "logos/globe.png"
    globe_img = Image.open(globe_path).convert("RGBA") if os.path.exists(globe_path) else None
    
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
    wm_y = IMG_H - (text_height + 30)  # Fixed bottom margin
    
    # Watermark shadow
    shadow_layer = Image.new("RGBA", final_img.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)
    
    if globe_icon:
        icon_mask = globe_icon.split()[3]
        black_icon = Image.new("RGBA", globe_icon.size, (0, 0, 0, 200))
        for offset in range(6):
            ox = wm_x + 5 + offset
            oy = wm_y + 5 + offset + int((text_height - icon_size) / 2)
            shadow_layer.paste(black_icon, (ox, oy), icon_mask)
    
    text_base_x = wm_x + (icon_size + spacing if globe_icon else 0)
    for offset in range(6):
        shadow_draw.text(
            (text_base_x + 5 + offset, wm_y + 5 + offset),
            wm_text,
            font=watermark_font,
            fill=(0, 0, 0, 200)
        )
    
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(8))
    final_img = Image.alpha_composite(final_img.convert("RGBA"), shadow_layer)
    draw = ImageDraw.Draw(final_img)
    
    # Draw watermark
    if globe_icon:
        icon_y = wm_y + (text_height - icon_size) // 2
        final_img.paste(globe_icon, (wm_x + 2, icon_y + 2), globe_icon)
    
    draw.text((text_base_x, wm_y), wm_text, font=watermark_font, fill="white")
    
    # Save post
    os.makedirs("posts", exist_ok=True)
    filename = f"posts/post{post_count}_{news_item.get('source','source')}.png"
    final_img.save(filename)
    return filename

def generate_caption(news_item, analysis_result):
    pointers_text = "\n".join([f"• {p}" for p in analysis_result['pointers']])
    return f"""{analysis_result['heading']}

🔗 Read more: {news_item['url']}
📌 Source: {news_item['source']}

{pointers_text}

Hashtags: {analysis_result['hashtags']}
"""

# ----------------- Async main -----------------
async def main():
    telegram_token = os.getenv("TELEGRAM_NEWSBOT_TOKEN")
    try:
        # Fetch articles
        news_data = fetch_newapi_articles(query=os.getenv("NEWS_QUERY", "Geopolitics"))
        
        # Use LLM to select viral articles
        articles_for_llm = json.dumps([{"title": n['title'], "url": n['url']} for n in news_data])
        llm_selected_articles = call_llm(VIRAL_NEWS_SELECTOR_PROMPT, articles_for_llm)
        
        post_count = 0
        
        for news in llm_selected_articles:
            full_article = next((item for item in news_data if item["url"] == news['url']), None)
            print(f"INFO: {full_article}")
            
            if full_article:
                analyzed_news = call_llm(ANALYZE_NEWS_ARTICLE_PROMPT, full_article)
                print(f"INFO: {analyzed_news}")
                
                post_file = create_instagram_post(post_count, full_article, analyzed_news)
                caption = generate_caption(news_item=full_article, analysis_result=analyzed_news)
                send_image_to_telegram(f"{post_file}", f"{caption}", telegram_token)
                
                post_count += 1
                if post_count == 5:
                    break
                    
    except Exception as e:
        print(f"ERROR : {e}")
    # import temp
    # post_file = create_instagram_post(post_count=1, news_item=temp.full_article, analysis_result=temp.analyzed_news)
    # send_image_to_telegram(f"{post_file}", f"test", telegram_token)

if __name__ == "__main__":
    asyncio.run(main())