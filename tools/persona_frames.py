"""Compose the two frames Chris appears in, in his own brand colours."""
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
PINK = (233, 30, 120)          # #E91E78, lifted from his CTA button
GREY = (220, 214, 214)         # #DCD6D6, his studio backdrop
INK = (51, 51, 53)             # #333335, his lower bar
CJK = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"


def subject(src, fallback=0.68):
    """Him, cut just above the dark caption bar his poster already carries.

    The bar is found rather than assumed, so a re-shot poster with the bar in a
    different place still crops cleanly.
    """
    img = Image.open(src).convert("RGB")
    px, w, h = img.load(), img.width, img.height
    cut = int(h * fallback)
    for y in range(int(h * 0.5), h):
        dark = sum(1 for x in range(0, w, 8) if sum(px[x, y]) < 200)
        if dark > (w // 8) * 0.75:
            cut = y - 6
            break
    return img.crop((0, 0, w, cut))


def line(draw, text, font, cx, y, fill):
    w = draw.textlength(text, font=font)
    draw.text((cx - w / 2, y), text, font=font, fill=fill)
    return w


def pill(draw, text, font, cx, y, pad=(46, 24), radius=999, bg=PINK, fg=(255, 255, 255)):
    w = draw.textlength(text, font=font)
    a, d = font.getmetrics()
    box = [cx - w / 2 - pad[0], y - pad[1], cx + w / 2 + pad[0], y + a + d + pad[1]]
    draw.rounded_rectangle(box, radius=radius, fill=bg)
    draw.text((cx - w / 2, y), text, font=font, fill=fg)
    return box


def frame(src, out, headline, sub=None, cta=None, top=300):
    canvas = Image.new("RGB", (W, H), GREY)
    person = subject(src)
    person = person.resize((W, round(person.height * W / person.width)), Image.LANCZOS)
    canvas.paste(person, (0, top))

    d = ImageDraw.Draw(canvas)
    y = top + person.height + 60
    big = ImageFont.truetype(CJK, 104)
    pill(d, headline, big, W / 2, y)
    y += 104 * 1.35 + 60

    if sub:
        small = ImageFont.truetype(CJK, 44)
        line(d, sub, small, W / 2, y, INK)
        y += 44 * 1.5 + 30
    if cta:
        mid = ImageFont.truetype(CJK, 52)
        pill(d, cta, mid, W / 2, y, pad=(40, 20))

    canvas.save(out, "JPEG", quality=94)
    return out


if __name__ == "__main__":
    import sys
    src, outdir = sys.argv[1], sys.argv[2]
    frame(src, f"{outdir}/hook.jpg", "猜这间多少钱？")
    frame(src, f"{outdir}/end.jpg", "RM 1.98 mil",
          sub="Horizon Hills · CL8656 · 永久地契",
          cta="WhatsApp 我 · 010-369 8656")
    print("built hook.jpg and end.jpg")
