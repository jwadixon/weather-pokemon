#!/usr/bin/env python3
"""
Weather Pokemon frame: cloud renderer (Seeed reTerminal Sticky, 4 greys).

Runs every hour on GitHub Actions. Checks the weather, picks four Gen 1 Pokemon
whose type suits it, and draws each as an 800 x 480 picture in the four greys
the Sticky's screen can show, using the original Red/Blue sprite scaled up as
crisp pixel art. Writes them to ./site for GitHub Pages:

  site/now.png      the main picture the frame shows every hour
  site/alt-1.png    alternatives the frame steps through when you press
  site/alt-2.png    its buttons
  site/alt-3.png
  site/index.html   a page to check the images in a browser

Run it on your Mac the same way:  python render_frame.py

Low-battery screen, made once and built into the frame's firmware:
  python render_frame.py --fainted     writes fainted.png next to this script
"""
import datetime as dt
import json
import random
import re
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from PIL import Image, ImageDraw, ImageFont

# One shared connection that retries a few times (5s, 10s, 20s, 40s apart)
# if Open-Meteo or PokéAPI has a blip, instead of failing the whole run.
SESSION = requests.Session()
SESSION.mount("https://", HTTPAdapter(max_retries=Retry(
    total=4, backoff_factor=5, status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"])))

# ---------- Settings you might change ----------
# These coordinates end up in a public repo, so use the city centre or your
# postcode district rather than your front door.
LAT, LON = 51.4545, -2.5879
PLACE = "Bristol"
TZ = ZoneInfo("Europe/London")
WINDY_KMH = 40
HOT_C, FREEZING_C = 25, 0
MAX_DEX = 151          # 151 = the original Gen 1 Pokemon only
SPRITE_SIZE = 288      # largest sprite size in pixels; the window is 392
WIDTH, HEIGHT = 800, 480
ALTERNATIVES = 3
OUT = Path("site")
CACHE = Path.home() / ".cache" / "weather-pokemon"
API = "https://pokeapi.co/api/v2"
HEADERS = {"User-Agent": "weather-pokemon-frame/3.0"}

# The four greys. Each sits inside one of the bands ESPHome's Sticky driver
# uses (black < 32, dark 32-95, light 96-159, white 160+), so every pixel
# lands on exactly the shade you see in the preview.
BLACK, DARK, LIGHT, WHITE = (0, 0, 0), (80, 80, 80), (140, 140, 140), (255, 255, 255)
SHADES = [BLACK, DARK, LIGHT, WHITE]

# Weather -> (label, Pokemon types, icon). Pokemon GO's weather boosts, plus
# night, storm, freezing and hot.
CONDITIONS = {
    "clear":    ("Sunny",         ["fire", "grass", "ground"], "sun"),
    "night":    ("Clear night",   ["dark", "ghost", "psychic"], "moon"),
    "partly":   ("Partly cloudy", ["normal", "rock"], "partly"),
    "cloudy":   ("Cloudy",        ["fairy", "fighting", "poison"], "cloud"),
    "rain":     ("Rain",          ["water", "electric", "bug"], "rain"),
    "storm":    ("Thunderstorm",  ["electric"], "storm"),
    "snow":     ("Snow",          ["ice", "steel"], "snow"),
    "fog":      ("Fog",           ["dark", "ghost"], "fog"),
    "windy":    ("Windy",         ["dragon", "flying", "psychic"], "wind"),
    "freezing": ("Freezing",      ["ice"], "snow"),
    "hot":      ("Hot",           ["fire"], "sun"),
}

RAIN = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}
SNOW = {71, 73, 75, 77, 85, 86}
FOG = {45, 48}

# 16 x 16 pixel weather icons, drawn 4x size. "#" = black, "+" = dark grey.
ICONS = {
    "sun": [".......#........", "...#...#...#....", "....#.....#.....", "......###.......",
            ".....#####......", "....#######.....", "##..#######..##.", "....#######.....",
            ".....#####......", "......###.......", "....#.....#.....", "...#...#...#....",
            ".......#........", "................", "................", "................"],
    "moon": ["......####......", "....###.........", "...###..........", "..###...........",
             "..###...........", ".###............", ".###............", ".###............",
             ".###............", "..###...........", "..####.......#..", "...#####...###..",
             "....#########...", "......#####.....", "................", "................"],
    "partly": [".#...#..........", "..#.#...........", "#.###.#.........", ".#####..........",
               "#######.........", ".####.####......", "..##.#....##....", "...#........#...",
               ".###........###.", "#..............#", "#..............#", ".##############.",
               "................", "................", "................", "................"],
    "cloud": ["................", "................", "......####......", "....##....##....",
              "...#........#...", ".###........###.", "#..............#", "#..............#",
              "#..............#", ".##############.", "................", "................",
              "................", "................", "................", "................"],
    "rain": ["......####......", "....##....##....", "...#........#...", ".###........###.",
             "#..............#", "#..............#", ".##############.", "................",
             "..#...#...#...#.", ".#...#...#...#..", "................", "...#...#...#....",
             "..#...#...#.....", "................", "................", "................"],
    "storm": ["......####......", "....##....##....", "...#........#...", ".###........###.",
              "#..............#", "#..............#", ".######..#######", "......#.#.......",
              ".....#..#.......", "....#....#......", "....####..#.....", ".......#.#......",
              "......#.#.......", "......##........", "......#.........", "................"],
    "snow": ["................", ".......#........", "....#..#..#.....", ".....#.#.#......",
             "......###.......", ".#############..", "......###.......", ".....#.#.#......",
             "....#..#..#.....", ".......#........", "................", "..+...+...+...+.",
             "................", "....+...+...+...", "................", "................"],
    "fog": ["................", "................", "################", "................",
            "................", "..##############", "................", "................",
            "################", "................", "................", "##############..",
            "................", "................", "################", "................"],
    "wind": ["................", "..........##....", "...........#....", "#############...",
             "................", "................", "###############.", "..............#.",
             ".............#..", "................", "##########......", ".........#......",
             "........#.......", "................", "................", "................"],
}

FONT_FILES = {
    "bold": ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
             "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
             "C:/Windows/Fonts/courbd.ttf"],
    "regular": ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
                "/System/Library/Fonts/Supplemental/Courier New.ttf",
                "C:/Windows/Fonts/cour.ttf"],
}


# ---------- Data ----------
def fetch_json(url, **params):
    r = SESSION.get(url, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()


def get_weather():
    return fetch_json(
        "https://api.open-meteo.com/v1/forecast",
        latitude=LAT, longitude=LON, timezone="Europe/London", forecast_days=1,
        current="temperature_2m,weather_code,wind_speed_10m,is_day",
        daily="temperature_2m_max,temperature_2m_min,precipitation_probability_max",
    )


def classify(code, wind, is_day, temp):
    if code >= 95:
        return "storm"
    if code in SNOW:
        return "snow"
    if code in RAIN:
        return "rain"
    if code in FOG:
        return "fog"
    if wind >= WINDY_KMH:
        return "windy"
    if temp <= FREEZING_C:
        return "freezing"
    if temp >= HOT_C:
        return "hot"
    if code == 3:
        return "cloudy"
    if code in (1, 2):
        return "partly"
    return "clear" if is_day else "night"


def ids_for_type(type_name):
    path = CACHE / f"type-{type_name}.json"
    if path.exists():
        return json.loads(path.read_text())
    data = fetch_json(f"{API}/type/{type_name}")
    ids = []
    for entry in data["pokemon"]:
        pid = int(entry["pokemon"]["url"].rstrip("/").split("/")[-1])
        if pid < 10000:               # skip megas, regional forms etc.
            ids.append(pid)
    path.write_text(json.dumps(ids))
    return ids


def english(items, key):
    for item in items:
        if item["language"]["name"] == "en":
            return item[key]
    return ""


def get_pokemon(pid):
    path = CACHE / f"pokemon-v3-{pid}.json"
    if path.exists():
        return json.loads(path.read_text())
    p = fetch_json(f"{API}/pokemon/{pid}")
    s = fetch_json(f"{API}/pokemon-species/{pid}")
    gen1 = p["sprites"].get("versions", {}).get("generation-i", {})
    sprite = None
    for game in ("red-blue", "yellow"):
        g = gen1.get(game) or {}
        sprite = g.get("front_transparent") or g.get("front_default") or g.get("front_gray")
        if sprite:
            break
    slim = {
        "id": pid,
        "name": english(s["names"], "name") or p["name"].title(),
        "types": [t["type"]["name"] for t in p["types"]],
        "sprite": sprite,
        "art": p["sprites"]["other"]["official-artwork"]["front_default"],
    }
    path.write_text(json.dumps(slim))
    return slim


def download(url, name):
    path = CACHE / name
    if not path.exists():
        r = SESSION.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        path.write_bytes(r.content)
    return Image.open(BytesIO(path.read_bytes()))


def to_four_greys(img, dither=False):
    """Flatten onto white and map to the four greys."""
    rgba = img.convert("RGBA")
    flat = Image.new("RGBA", rgba.size, WHITE + (255,))
    flat.alpha_composite(rgba)
    pal = Image.new("P", (1, 1))
    colours = [c for s in SHADES for c in s]
    pal.putpalette(colours + colours[:3] * (256 - len(SHADES)))
    mode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
    return flat.convert("RGB").quantize(palette=pal, dither=mode).convert("RGB")


def get_sprite(mon, box=SPRITE_SIZE):
    """The Red/Blue sprite as crisp pixel art; official artwork as a fallback.

    Gen 1 sprites sit on a fixed 56 x 56 canvas, and small Pokemon only fill
    part of it, so trim to the Pokemon's own outline first, then scale up by
    the largest whole number that fits the window (whole numbers keep every
    pixel square and sharp)."""
    if mon.get("sprite"):
        raw = download(mon["sprite"], f"gen1-{mon['id']}.png").convert("RGBA")
        mask = Image.new("L", raw.size, 0)
        src, dst = raw.load(), mask.load()
        for yy in range(raw.height):
            for xx in range(raw.width):
                r, g, b, a = src[xx, yy]
                if a > 0 and (r, g, b) != (255, 255, 255):
                    dst[xx, yy] = 255
        if mask.getbbox():
            raw = raw.crop(mask.getbbox())
        s = to_four_greys(raw)
        scale = max(1, min(box // s.width, box // s.height))
        return s.resize((s.width * scale, s.height * scale), Image.NEAREST)
    art = download(mon["art"], f"art-{mon['id']}.png")
    art.thumbnail((box, box), Image.LANCZOS)
    return to_four_greys(art, dither=True)


def pick_pokemon(cond, count):
    """Pokemon for this weather, up to No. MAX_DEX. No repeats unless the
    weather has fewer matching Pokemon than pictures (Gen 1 has only three
    Ghost types and no Dark types, so foggy days can repeat one)."""
    pool = sorted({pid for t in CONDITIONS[cond][1] for pid in ids_for_type(t) if pid <= MAX_DEX})
    if not pool:
        raise SystemExit(f"No Pokémon up to No. {MAX_DEX} for '{cond}'. Raise MAX_DEX or change its types.")
    random.shuffle(pool)
    chosen = []
    for pid in pool + random.choices(pool, k=count):
        if len(chosen) == count:
            break
        mon = get_pokemon(pid)
        if mon["sprite"] or mon["art"]:
            chosen.append(mon)
    return chosen


# ---------- Drawing ----------
def font(style, size):
    for f in FONT_FILES[style]:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default(size=size)


def fit(draw, text, style, size, width, smallest=14):
    while size > smallest and draw.textlength(text, font=font(style, size)) > width:
        size -= 2
    return font(style, size)


def icon(name, scale=4):
    im = Image.new("RGB", (16 * scale, 16 * scale), WHITE)
    d = ImageDraw.Draw(im)
    for y, row in enumerate(ICONS[name]):
        for x, c in enumerate(row):
            if c in "#+":
                d.rectangle([x * scale, y * scale, x * scale + scale - 1, y * scale + scale - 1],
                            fill=BLACK if c == "#" else DARK)
    return im


def render(weather, cond, mon, sprite, stamp):
    img = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    d = ImageDraw.Draw(img)
    label, types, icon_name = CONDITIONS[cond]

    # Sprite window
    d.rectangle([24, 36, 432, 444], outline=BLACK, width=4)
    d.rectangle([32, 44, 424, 436], outline=LIGHT, width=2)
    # centred in the inner window (x 32-424, y 44-436)
    img.paste(sprite, (32 + (392 - sprite.width) // 2, 44 + (392 - sprite.height) // 2))

    x, w = 464, 312
    y = 34
    d.text((x, y), f"No.{mon['id']:03d}", font=font("regular", 22), fill=BLACK)
    y += 30
    name = mon["name"].upper()
    d.text((x, y), name, font=fit(d, name, "bold", 46, w, smallest=26), fill=BLACK)
    y += 62

    bx = x
    badge = font("bold", 18)
    for t in mon["types"]:
        text = t.upper()
        tw = d.textlength(text, font=badge)
        d.rectangle([bx, y, bx + tw + 24, y + 30], outline=BLACK, width=2)
        d.text((bx + 12, y + 4), text, font=badge, fill=BLACK)
        bx += tw + 34
    y += 48

    for px in range(x, x + w, 8):                      # dotted rule
        d.rectangle([px, y, px + 3, y + 2], fill=BLACK)
    y += 14

    cur, day = weather["current"], weather["daily"]
    temp = f"{round(cur['temperature_2m'])}°"
    size = 96
    while size > 60 and d.textlength(temp, font=font("bold", size)) > w - 64 - 16:
        size -= 6                                   # e.g. -12° next to the icon
    d.text((x - 4, y - 8 + (96 - size) // 2), temp, font=font("bold", size), fill=BLACK)
    img.paste(icon(icon_name), (x + w - 64, y + 2))
    rain = day["precipitation_probability_max"][0]
    if rain is not None:
        small_rain = font("regular", 15)
        rt = f"RAIN {rain}%"
        d.text((x + w - d.textlength(rt, font=small_rain), y + 72), rt, font=small_rain, fill=BLACK)
    y += 104

    line = label.upper()
    d.text((x, y), line, font=fit(d, line, "bold", 26, w), fill=BLACK)
    y += 36
    d.text((x, y), f"HI {round(day['temperature_2m_max'][0])}°  LO {round(day['temperature_2m_min'][0])}°",
           font=font("regular", 24), fill=BLACK)
    y += 38
    d.text((x, y), "OUT TODAY:", font=font("bold", 18), fill=DARK)
    y += 24
    out = " ".join(t.upper() for t in types)
    d.text((x, y), out, font=fit(d, out, "regular", 18, w), fill=BLACK)

    # The bottom strip (y 446+) is left empty: the frame draws its battery
    # as an HP bar bottom left, and the time it redrew bottom right.
    return to_four_greys(img)          # snap text edges to the four greys


def render_fainted(mon, sprite):
    """Low-battery screen in the style of a Gen 1 battle: the Pokemon sinks
    out of view behind the text box, its HP bar is empty, and the box says it
    fainted. The frame shows this at 2% and leaves it there: e-paper keeps the
    picture even after the battery is completely flat."""
    img = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    d = ImageDraw.Draw(img)
    box_top = 318

    # Sprite on the right, slid down so the text box hides its lower part,
    # like the faint animation in Red and Blue.
    sx = 560 - sprite.width // 2
    sy = box_top - int(sprite.height * 0.62)
    img.paste(sprite, (sx, sy))
    # "Ground" line the Pokemon sinks behind
    d.rectangle([380, box_top - 6, 740, box_top - 1], fill=DARK)

    # HP box, top left: name, level, empty HP bar, Game Boy style bracket
    x, y = 48, 40
    name = mon["name"].upper()
    d.text((x, y), name, font=font("bold", 44), fill=BLACK)
    d.text((x + 150, y + 56), ":L25", font=font("bold", 28), fill=BLACK)
    by = y + 104
    d.text((x, by - 6), "HP:", font=font("bold", 24), fill=BLACK)
    d.rectangle([x + 60, by, x + 300, by + 16], outline=BLACK, width=3)   # empty bar
    d.rectangle([x + 300, by + 4, x + 306, by + 12], fill=BLACK)
    d.text((x + 200, by + 26), "0/ 35", font=font("bold", 26), fill=BLACK)
    d.line([x - 16, by + 6, x - 16, by + 64], fill=BLACK, width=5)        # bracket
    d.line([x - 16, by + 64, x + 320, by + 64], fill=BLACK, width=5)
    d.polygon([(x + 320, by + 56), (x + 336, by + 64), (x + 320, by + 72)], fill=BLACK)

    # Text box along the bottom, double border like the games
    d.rectangle([16, box_top, WIDTH - 17, HEIGHT - 17], fill=WHITE, outline=BLACK, width=6)
    d.rectangle([28, box_top + 12, WIDTH - 29, HEIGHT - 29], outline=DARK, width=3)
    d.text((60, box_top + 30), f"{name} fainted!", font=font("bold", 44), fill=BLACK)
    d.text((60, box_top + 92), "Plug in USB-C to revive.", font=font("regular", 30), fill=BLACK)
    tx, ty = WIDTH - 80, HEIGHT - 66
    d.polygon([(tx, ty), (tx + 22, ty), (tx + 11, ty + 13)], fill=BLACK)   # the little "next" arrow
    return to_four_greys(img)


INDEX = """<!DOCTYPE html><html lang="en-GB"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Weather Pokemon frame</title>
<style>body{{font:16px system-ui;margin:24px;background:#eee}}img{{max-width:100%;
display:block;margin:8px 0 24px;border:12px solid #222;image-rendering:pixelated}}</style>
<h1>Weather Pokemon frame</h1><p>Rendered {stamp} for {label}.</p>
<p>Weather data by <a href="https://open-meteo.com/">Open-Meteo.com</a> (CC BY 4.0).</p>
{images}</html>"""


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(exist_ok=True)

    try:
        weather = get_weather()
        c = weather["current"]
        cond = classify(c["weather_code"], c["wind_speed_10m"], c["is_day"], c["temperature_2m"])
        names = ["now"] + [f"alt-{i}" for i in range(1, ALTERNATIVES + 1)]
        mons = pick_pokemon(cond, len(names))
    except requests.RequestException as e:
        # Open-Meteo or PokéAPI is down even after retries. Skip this hour
        # quietly: the frame keeps last hour's picture and tries again next hour.
        print(f"::warning::Skipped this hour, a data source didn't answer: {e}")
        return
    stamp = dt.datetime.now(TZ).strftime("%H:%M")

    for name, mon in zip(names, mons):
        img = render(weather, cond, mon, get_sprite(mon), stamp)
        img.save(OUT / f"{name}.png", optimize=True)
        print(f"{name}.png  {mon['name']}  ({CONDITIONS[cond][0]})")

    images = "".join(f'<p>{n}.png</p><img src="{n}.png" alt="{n}">' for n in names)
    (OUT / "index.html").write_text(INDEX.format(stamp=stamp, label=CONDITIONS[cond][0], images=images))
    (OUT / ".nojekyll").write_text("")
    # When this picture was made, so the frame can show it (Unix time, seconds).
    (OUT / "stamp.txt").write_text(str(int(dt.datetime.now(dt.timezone.utc).timestamp())))


if __name__ == "__main__":
    import sys
    if "--fainted" in sys.argv:
        CACHE.mkdir(parents=True, exist_ok=True)
        mon = get_pokemon(25)                          # Pikachu
        out = Path(__file__).with_name("fainted.png")
        render_fainted(mon, get_sprite(mon, box=240)).save(out, optimize=True)
        print(f"Wrote {out}")
    else:
        main()
