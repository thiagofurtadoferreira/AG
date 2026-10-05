#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import textwrap
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
ASSETS = ROOT / "assets"
SCENES = ROOT / "scenes"
PARTS = ROOT / "parts"

for d in (OUT, ASSETS, SCENES, PARTS):
    d.mkdir(parents=True, exist_ok=True)

W, H = 1080, 1920
FPS = 30

FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

def font(size: int, bold: bool = False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)

def wrap(draw, text, fnt, max_width):
    words = text.split()
    lines = []
    cur = ""
    for word in words:
        test = (cur + " " + word).strip()
        if draw.textbbox((0, 0), test, font=fnt)[2] <= max_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines

def download_image(name: str, url: str, referer: str) -> Path:
    dest = ASSETS / f"{name}.jpg"
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Referer": referer,
    }
    candidates = [
        url,
        "https://wsrv.nl/?url=" + quote(url, safe="") + "&w=1400&q=92&output=jpg",
    ]
    last_error = None
    for candidate in candidates:
        try:
            r = requests.get(candidate, headers=headers, timeout=45)
            r.raise_for_status()
            im = Image.open(BytesIO(r.content)).convert("RGB")
            if im.width < 300 or im.height < 250:
                raise ValueError(f"imagem pequena demais: {im.size}")
            im.save(dest, "JPEG", quality=94)
            print(f"OK {name}: {im.size} <- {candidate}")
            return dest
        except Exception as e:
            last_error = e
            print(f"Falha {name} em {candidate}: {e}")
    raise RuntimeError(f"Não foi possível baixar {name}: {last_error}")

def rounded_rect(draw, xy, radius, fill):
    draw.rounded_rectangle(xy, radius=radius, fill=fill)

def compose_photo_scene(photo_path: Path, title: str, body: str, source: str, out_path: Path):
    photo = Image.open(photo_path).convert("RGB")

    # Fundo: mesma foto em cover, desfocada e escurecida.
    bg = photo.copy()
    scale = max(W / bg.width, H / bg.height)
    bg = bg.resize((int(bg.width * scale), int(bg.height * scale)), Image.Resampling.LANCZOS)
    left = (bg.width - W) // 2
    top = (bg.height - H) // 2
    bg = bg.crop((left, top, left + W, top + H))
    bg = bg.filter(ImageFilter.GaussianBlur(28))
    bg = ImageEnhance.Brightness(bg).enhance(0.32)

    canvas = bg.convert("RGBA")
    draw = ImageDraw.Draw(canvas, "RGBA")

    # Área da fotografia - preserva a foto inteira.
    max_pw, max_ph = 980, 1160
    s = min(max_pw / photo.width, max_ph / photo.height)
    p = photo.resize((max(1, int(photo.width*s)), max(1, int(photo.height*s))), Image.Resampling.LANCZOS)
    px = (W - p.width) // 2
    py = 150 + (max_ph - p.height) // 2

    # Sombra e moldura.
    draw.rounded_rectangle((px-12, py-12, px+p.width+12, py+p.height+12), radius=30, fill=(0,0,0,100))
    mask = Image.new("L", p.size, 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0,0,p.width,p.height), radius=24, fill=255)
    canvas.alpha_composite(Image.composite(p.convert("RGBA"), Image.new("RGBA", p.size), mask), (px,py))

    # Caixa de texto.
    box_y = 1370
    rounded_rect(draw, (55, box_y, W-55, H-70), 34, (0,0,0,182))

    f_title = font(58, True)
    f_body = font(38, False)
    f_source = font(27, False)

    x = 90
    y = box_y + 55
    for line in wrap(draw, title, f_title, W-180):
        draw.text((x,y), line, font=f_title, fill=(255,255,255,255))
        y += 70

    y += 16
    for line in wrap(draw, body, f_body, W-180):
        draw.text((x,y), line, font=f_body, fill=(245,245,245,255))
        y += 51

    # Fonte no rodapé.
    sy = H - 130
    for line in wrap(draw, source, f_source, W-180):
        draw.text((x,sy), line, font=f_source, fill=(205,205,205,255))
        sy += 36

    canvas.convert("RGB").save(out_path, "JPEG", quality=94)

def compose_text_scene(title: str, body: str, foot: str, out_path: Path, big_number: str | None = None):
    canvas = Image.new("RGB", (W,H), (10,12,14)).convert("RGBA")
    draw = ImageDraw.Draw(canvas, "RGBA")

    # Elementos discretos, estilo documental.
    draw.rectangle((0,0,W,18), fill=(225,225,225,255))
    draw.ellipse((700, -170, 1250, 380), fill=(255,255,255,12))
    draw.ellipse((-180, 1380, 430, 1990), fill=(255,255,255,10))

    f_title = font(70, True)
    f_body = font(46, False)
    f_big = font(122, True)
    f_foot = font(29, False)

    y = 320
    for line in wrap(draw, title, f_title, W-160):
        bbox = draw.textbbox((0,0), line, font=f_title)
        draw.text(((W-(bbox[2]-bbox[0]))/2,y), line, font=f_title, fill="white")
        y += 86

    if big_number:
        y += 80
        bbox = draw.textbbox((0,0), big_number, font=f_big)
        draw.text(((W-(bbox[2]-bbox[0]))/2,y), big_number, font=f_big, fill=(255,255,255,255))
        y += 160

    y += 55
    for line in wrap(draw, body, f_body, W-180):
        bbox = draw.textbbox((0,0), line, font=f_body)
        draw.text(((W-(bbox[2]-bbox[0]))/2,y), line, font=f_body, fill=(225,225,225,255))
        y += 64

    fy = H-230
    for line in wrap(draw, foot, f_foot, W-180):
        bbox = draw.textbbox((0,0), line, font=f_foot)
        draw.text(((W-(bbox[2]-bbox[0]))/2,fy), line, font=f_foot, fill=(175,175,175,255))
        fy += 40

    canvas.convert("RGB").save(out_path, "JPEG", quality=94)

def make_part(still: Path, duration: float, out: Path):
    fade_out = max(duration - 0.55, 0)
    vf = (
        f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={FPS},"
        f"fade=t=in:st=0:d=0.45,"
        f"fade=t=out:st={fade_out}:d=0.5,"
        "format=yuv420p"
    )
    cmd = [
        "ffmpeg","-y",
        "-loop","1","-t",str(duration),"-i",str(still),
        "-f","lavfi","-t",str(duration),"-i","anullsrc=channel_layout=stereo:sample_rate=44100",
        "-vf",vf,
        "-c:v","libx264","-preset","medium","-crf","20",
        "-c:a","aac","-b:a","128k",
        "-pix_fmt","yuv420p","-shortest",
        str(out)
    ]
    subprocess.run(cmd, check=True)

def main():
    images = [
        {
            "name":"ghazal",
            "url":"https://www.unicef.org/mena/sites/unicef.org.mena/files/styles/hero_desktop/public/DSC_7825%20%281%29.webp?itok=ZgjSXsH_",
            "referer":"https://www.unicef.org/mena/stories/facing-life-gaza-strip-new-disability",
        },
        {
            "name":"razan",
            "url":"https://www.unicef.org/sop/sites/unicef.org.sop/files/styles/hero_desktop/public/NX8A5515.jpg.webp?itok=Y6BJiUAy",
            "referer":"https://www.unicef.org/sop/stories/hope-amidst-ruins-echoing-voices-gaza-strips-children",
        },
        {
            "name":"jihad",
            "url":"https://www.unicef.org/sop/sites/unicef.org.sop/files/styles/media_large_image/public/Jihad.webp?itok=4bOI1kXq",
            "referer":"https://www.unicef.org/sop/stories/toys-and-art-supplies-provide-respite-children-northern-gaza-strip",
        },
        {
            "name":"ghada",
            "url":"https://www.unicef.org/sites/default/files/styles/collage_desktop/public/UNI776582.webp?itok=86V6eb7O",
            "referer":"https://www.unicef.org/sop/stories/lives-changed-forever-war-gaza",
        },
    ]

    paths = {}
    for item in images:
        try:
            paths[item["name"]] = download_image(item["name"], item["url"], item["referer"])
        except Exception as e:
            print("AVISO:", e)

    scene_specs = []

    s = SCENES/"00_abertura.jpg"
    compose_text_scene(
        "Crianças amputadas em Gaza",
        "Quatro histórias documentadas pela UNICEF durante a guerra iniciada em outubro de 2023.",
        "Imagens reais e não gráficas. Fontes e créditos aparecem ao longo do vídeo.",
        s
    )
    scene_specs.append((s,5.0))

    data = [
        ("ghazal","Ghazal, 4 anos",
         "Depois que sua casa foi atingida, uma lesão grave na perna infeccionou. A equipe médica precisou amputá-la.",
         "Fonte: UNICEF MENA — 2 jan. 2024"),
        ("razan","Razan, 11 anos",
         "Perdeu os pais e três irmãos. Uma explosão causou ferimentos que levaram à amputação da perna esquerda.",
         "Fonte: UNICEF State of Palestine — 26 fev. 2024"),
        ("jihad","Jihad, 17 anos",
         "Em relato à UNICEF, descreveu a dificuldade de aceitar a amputação da perna e de voltar a se locomover.",
         "Fonte/foto: UNICEF State of Palestine / Eyad al-Baba"),
        ("ghada","Ghada",
         "Foi ferida quando o abrigo onde brincava com amigos foi atingido. Sofreu amputação no membro superior direito.",
         "Fonte/foto: UNICEF / Mohammed Nateel — 6 mai. 2025"),
    ]

    idx = 1
    for key, title, body, src in data:
        if key not in paths:
            continue
        s = SCENES/f"{idx:02d}_{key}.jpg"
        compose_photo_scene(paths[key], title, body, src, s)
        scene_specs.append((s,10.0))
        idx += 1

    s = SCENES/"90_oms.jpg"
    compose_text_scene(
        "A dimensão das amputações",
        "A OMS estima entre 5.161 e 6.710 amputações de membros relacionadas ao conflito desde outubro de 2023. Entre 2.277 pessoas amputadas avaliadas, 18% eram crianças.",
        "Fonte: Organização Mundial da Saúde — Estimating Trauma Rehabilitation Needs in Gaza, atualização de maio de 2026.",
        s,
        big_number="5.161–6.710"
    )
    scene_specs.append((s,9.0))

    s = SCENES/"99_creditos.jpg"
    compose_text_scene(
        "Cada número é uma vida",
        "As consequências continuam na reabilitação, nas próteses, na mobilidade e no apoio psicológico.",
        "Fontes: UNICEF MENA · UNICEF State of Palestine · OMS. Edição documental V1. Nenhuma imagem gráfica foi utilizada.",
        s
    )
    scene_specs.append((s,6.0))

    # Renderiza cada cena.
    part_paths = []
    for i, (still, dur) in enumerate(scene_specs):
        part = PARTS/f"part_{i:02d}.mp4"
        make_part(still, dur, part)
        part_paths.append(part)

    concat_file = ROOT/"concat.txt"
    concat_file.write_text("\n".join([f"file '{p.as_posix()}'" for p in part_paths])+"\n", encoding="utf-8")

    final = OUT/"gaza_criancas_amputadas_v1.mp4"
    subprocess.run([
        "ffmpeg","-y","-f","concat","-safe","0","-i",str(concat_file),
        "-c","copy","-movflags","+faststart",str(final)
    ], check=True)

    sources = OUT/"fontes.txt"
    sources.write_text(
        """FONTES DO VÍDEO — V1

Ghazal:
https://www.unicef.org/mena/stories/facing-life-gaza-strip-new-disability

Razan:
https://www.unicef.org/sop/stories/hope-amidst-ruins-echoing-voices-gaza-strips-children

Jihad:
https://www.unicef.org/sop/stories/toys-and-art-supplies-provide-respite-children-northern-gaza-strip

Ghada:
https://www.unicef.org/sop/stories/lives-changed-forever-war-gaza

OMS — atualização de maio de 2026:
https://www.emro.who.int/images/stories/palestine/Estimating_Trauma_Rehabilitation_Needs_in_Gaza_2026.pdf

Nota editorial:
Foram usadas somente imagens documentais não gráficas provenientes da UNICEF.
""",
        encoding="utf-8"
    )
    print(final)
    print(sources)

if __name__ == "__main__":
    main()
