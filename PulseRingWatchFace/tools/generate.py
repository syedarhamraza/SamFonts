#!/usr/bin/env python3
"""Generates the Pulse Ring watch face.

Writes:
  watchface/src/main/res/raw/watchface.xml   (Watch Face Format v2)
  watchface/src/main/res/values/strings.xml
  watchface/src/main/res/drawable/*.png      (icons + editor preview)
  docs/*.png                                 (theme previews for the README)

All layout constants live at the top of this file so the XML and the preview
renderer always agree. Run from anywhere:  python3 tools/generate.py
Requires Pillow.
"""
import math
import os
from xml.sax.saxutils import escape

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "watchface", "src", "main", "res")
DOCS = os.path.join(ROOT, "docs")

# --------------------------------------------------------------------------
# Layout (450 x 450 canvas, angles in degrees clockwise from 12 o'clock)
# --------------------------------------------------------------------------
SIZE = 450
C = SIZE // 2
R_INNER = 170          # inner circle that frames the clock
INNER_STROKE = 3
R_RING_TEXT = 195      # circle the curved ring text follows
RING_TEXT_SIZE = 24
R_ARC = 219            # step-progress arc, right at the bezel
ARC_STROKE = 6
ARC_SWEEP = 180       # degrees covered at 100% of the step goal
TICK_ANGLES = [42, 90, 138, 222, 270, 318]
TICK_STROKE = 3

# Ring segments
STEPS_RANGE = (-40, 40)         # top, clockwise text
HR_ICON_ANGLE = 53
HR_TEXT_RANGE = (62, 88)        # right upper, clockwise text
BAT_ICON_ANGLE = 282
BAT_TEXT_RANGE = (292, 316)     # left upper, clockwise text
RIGHT_SLOT = (92, 138)          # right lower complication (e.g. Sleep)
RIGHT_ICON_ANGLE = 130
RIGHT_TEXT_RANGE = (94, 124)
LEFT_SLOT = (222, 268)          # left lower complication (e.g. Alarm)
LEFT_ICON_ANGLE = 262
LEFT_TEXT_RANGE = (224, 256)
BOTTOM_SLOT = (140, 220)        # bottom complication (Next event)
RING_ICON = 34

# Centre stack (y values are cap-height centres)
WEATHER_ICON_Y = 90
WEATHER_ICON = 52
WEATHER_TEXT_Y = 133
WEATHER_TEXT_SIZE = 26
LINE1_Y = 156
TIME_Y = 225
TIME_SIZE = 132
LINE2_Y = 294
LINE_HALF = 140
DAY_Y = 316
DAY_SIZE = 30
DATE_Y = 356
DATE_SIZE = 40

# Font metrics (units of em) used to convert "cap centre" into text boxes.
# Text is vertically centred in its box, so the box height is the font's
# line height and the cap centre sits slightly below the box centre.
OSWALD = dict(line=1.482, cap_off=0.047)
MONTSERRAT = dict(line=1.219, cap_off=0.0085)

FONT_TIME = "oswald_semibold"
FONT_LABEL = "oswald_medium"
FONT_DAY = "montserrat_bold"

# --------------------------------------------------------------------------
# Themes: colors = background, foreground, progress arc, always-on colour
# --------------------------------------------------------------------------
ACCENTS = [
    ("mint", "Mint", "#1DE9B6", "#E8401C"),
    ("gold", "Gold", "#D4A35B", "#E8401C"),
    ("orange", "Orange", "#FF8A1F", "#FFFFFF"),
    ("ice", "Ice Blue", "#4FC3F7", "#E8401C"),
    ("lime", "Lime", "#C6FF00", "#E8401C"),
    ("red", "Red", "#FF5252", "#FFFFFF"),
    ("silver", "Silver", "#E0E0E0", "#E8401C"),
    ("pink", "Pink", "#FF6FB5", "#FFFFFF"),
]
THEMES = []  # (id, string_key, label, bg, fg, arc, aod)
for key, label, accent, arc in ACCENTS:
    THEMES.append((len(THEMES), f"theme_{key}", label, "#000000", accent, arc, accent))
    THEMES.append((len(THEMES), f"theme_{key}_inv", f"{label} inverted", accent,
                   "#000000", "#C62800" if arc != "#FFFFFF" else "#000000", accent))

BG, FG, ARC, AOD = (f"[CONFIGURATION.theme.{i}]" for i in range(4))


def polar(r, deg):
    a = math.radians(deg)
    return C + r * math.sin(a), C - r * math.cos(a)


def text_box(cap_y, size, metrics):
    h = math.ceil(size * metrics["line"])
    y = round(cap_y - size * metrics["cap_off"] - h / 2)
    return y, h


# --------------------------------------------------------------------------
# XML helpers
# --------------------------------------------------------------------------
def template(fmt, params):
    p = "".join(f'<Parameter expression="{escape(e, {chr(34): "&quot;"})}"/>' for e in params)
    return f"<Template><![CDATA[{fmt}]]>{p}</Template>"


def font(family, size, color, body, upper=False):
    if upper:
        body = f"<Upper>{body}</Upper>"
    return f'<Font family="{family}" size="{size}" color="{color}">{body}</Font>'


def part_text(x, y, w, h, inner, extra="", name=None):
    n = f' name="{name}"' if name else ""
    return f'<PartText x="{x}" y="{y}" width="{w}" height="{h}"{n}>{extra}{inner}</PartText>'


def flat_text(x, y, w, h, fnt, align="CENTER", extra="", name=None):
    return part_text(x, y, w, h, f'<Text align="{align}" ellipsis="TRUE">{fnt}</Text>', extra, name)


def circular_text(rng, fnt, ox=0, oy=0, clockwise=True, name=None):
    """Curved text on R_RING_TEXT. ox/oy is the parent's offset from the canvas."""
    d = "CLOCKWISE" if clockwise else "COUNTER_CLOCKWISE"
    tc = (f'<TextCircular centerX="{C}" centerY="{C}" width="{2 * R_RING_TEXT}" '
          f'height="{2 * R_RING_TEXT}" startAngle="{rng[0]}" endAngle="{rng[1]}" '
          f'direction="{d}" align="CENTER" ellipsis="TRUE">{fnt}</TextCircular>')
    return part_text(-ox, -oy, SIZE, SIZE, tc, name=name)


def ring_image(angle, resource, tint, ox=0, oy=0, flip=False, extra=""):
    x, y = polar(R_RING_TEXT, angle)
    rot = (angle + 180) % 360 if flip else angle % 360
    return (f'<PartImage x="{round(x - RING_ICON / 2) - ox}" y="{round(y - RING_ICON / 2) - oy}" '
            f'width="{RING_ICON}" height="{RING_ICON}" angle="{rot}" tintColor="{tint}">'
            f'{extra}<Image resource="{resource}"/></PartImage>')


def sector_bounds(a0, a1, r0=R_INNER, r1=SIZE // 2):
    pts = []
    for a in range(a0, a1 + 1):
        pts += [polar(r0, a), polar(r1, a)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, y0 = math.floor(min(xs)), math.floor(min(ys))
    return x0, y0, math.ceil(max(xs)) - x0, math.ceil(max(ys)) - y0


WEATHER_CODES = {
    0: "unknown", 1: "clear", 2: "cloudy", 3: "fog", 4: "heavy_rain", 5: "heavy_snow",
    6: "rain", 7: "snow", 8: "clear", 9: "thunder", 10: "sleet", 11: "snow", 12: "rain",
    13: "fog", 14: "partly", 15: "windy",
}


def weather_bitmap_fonts():
    out = []
    for period in ("day", "night"):
        out.append(f'<BitmapFont name="wx_{period}">')
        for code, icon in WEATHER_CODES.items():
            res = f"wx_{icon}_{period}" if icon in ("clear", "partly") else f"wx_{icon}"
            tag = "Character" if code < 10 else "Word"
            out.append(f'<{tag} name="{code}" resource="{res}" width="96" height="96"/>')
        out.append("</BitmapFont>")
    return "<BitmapFonts>" + "".join(out) + "</BitmapFonts>"


def weather_block(color):
    """Weather icon and 'NOW: 8°C  H 9°/L 7°' line."""
    s = WEATHER_ICON
    icon_x, icon_y = C - s // 2, WEATHER_ICON_Y - s // 2
    ty, th = text_box(WEATHER_TEXT_Y, WEATHER_TEXT_SIZE, OSWALD)
    code = "([WEATHER.CONDITION] <= 15 ? [WEATHER.CONDITION] : 0)"

    def icon(period):
        return part_text(icon_x, icon_y, s, s,
                         f'<Text align="CENTER"><BitmapFont family="wx_{period}" size="{s}">'
                         f'{template("%s", [code])}</BitmapFont></Text>',
                         extra="", name=f"weather_icon_{period}").replace(
            "<PartText ", f'<PartText tintColor="{color}" ', 1)

    unit = '([WEATHER.TEMPERATURE_UNIT] == 1 ? "C" : "F")'
    line = flat_text(55, ty, 340, th, font(FONT_LABEL, WEATHER_TEXT_SIZE, color, template(
        "NOW: %s°%s   H %s°/L %s°",
        ["[WEATHER.TEMPERATURE]", unit, "[WEATHER.TEMPERATURE_HIGH]", "[WEATHER.TEMPERATURE_LOW]"])))
    na_icon = part_text(icon_x, icon_y, s, s,
                        f'<Text align="CENTER"><BitmapFont family="wx_day" size="{s}">'
                        f'{template("%s", ["0"])}</BitmapFont></Text>').replace(
        "<PartText ", f'<PartText tintColor="{color}" ', 1)
    na_line = flat_text(55, ty, 340, th, font(FONT_LABEL, WEATHER_TEXT_SIZE, color,
                                              template("%s", ['"NO WEATHER DATA"'])))
    return (
        "<Condition><Expressions>"
        '<Expression name="wx_ok"><![CDATA[[WEATHER.IS_AVAILABLE] && ![WEATHER.IS_ERROR]]]></Expression>'
        "</Expressions>"
        '<Compare expression="wx_ok">'
        "<Condition><Expressions><Expression name=\"is_day\">[WEATHER.IS_DAY]</Expression></Expressions>"
        f'<Compare expression="is_day">{icon("day")}</Compare><Default>{icon("night")}</Default></Condition>'
        f"{line}</Compare>"
        f"<Default>{na_icon}{na_line}</Default></Condition>"
    )


def clock_stack(color, launch=True):
    """Weather, divider lines, time, day and date - shared by active and AOD."""
    out = [weather_block(color)]
    out.append(f'<PartDraw x="0" y="0" width="{SIZE}" height="{SIZE}">'
               f'<Line startX="{C - LINE_HALF}" startY="{LINE1_Y}" endX="{C + LINE_HALF}" endY="{LINE1_Y}">'
               f'<Stroke color="{color}" thickness="3"/></Line>'
               f'<Line startX="{C - LINE_HALF}" startY="{LINE2_Y}" endX="{C + LINE_HALF}" endY="{LINE2_Y}">'
               f'<Stroke color="{color}" thickness="3"/></Line></PartDraw>')
    ty, th = text_box(TIME_Y, TIME_SIZE, OSWALD)
    out.append(f'<DigitalClock x="20" y="{ty}" width="410" height="{th}">'
               f'<TimeText format="hh:mm" hourFormat="SYNC_TO_DEVICE" align="CENTER" '
               f'x="0" y="0" width="410" height="{th}">'
               f'<Font family="{FONT_TIME}" size="{TIME_SIZE}" color="{color}"/></TimeText></DigitalClock>')
    cal = '<Launch target="CALENDAR"/>' if launch else ""
    dy, dh = text_box(DAY_Y, DAY_SIZE, MONTSERRAT)
    out.append(flat_text(75, dy, 300, dh, font(FONT_DAY, DAY_SIZE, color, template("%s", ["[DAY_OF_WEEK_F]"])),
                         extra=cal))
    ny, nh = text_box(DATE_Y, DATE_SIZE, MONTSERRAT)
    out.append(flat_text(135, ny, 180, nh, font(FONT_DAY, DATE_SIZE, color, template("%s", ["[DAY_Z]"])),
                         extra=cal))
    return "".join(out)


def ring_complication(slot_id, label_key, rng, text_rng, icon_angle, flip, provider):
    x, y, w, h = sector_bounds(*rng)
    mid = (rng[0] + rng[1]) / 2
    txt = lambda fmt, params: circular_text(
        text_rng, font(FONT_LABEL, RING_TEXT_SIZE, FG, template(fmt, params), upper=True),
        ox=x, oy=y, clockwise=not flip)
    icon = ring_image(icon_angle, "[COMPLICATION.MONOCHROMATIC_IMAGE]", FG, ox=x, oy=y, flip=flip)
    with_title = txt("%s %s", ["[COMPLICATION.TEXT]", "[COMPLICATION.TITLE]"])
    text_only = txt("%s", ["[COMPLICATION.TEXT]"])
    body = (
        "<Condition><Expressions>"
        '<Expression name="has_icon"><![CDATA[[COMPLICATION.MONOCHROMATIC_IMAGE] != null]]></Expression>'
        "</Expressions>"
        f'<Compare expression="has_icon">{icon}</Compare></Condition>'
        "<Condition><Expressions>"
        '<Expression name="has_title"><![CDATA[[COMPLICATION.TITLE] != null]]></Expression>'
        "</Expressions>"
        f'<Compare expression="has_title">{with_title}</Compare><Default>{text_only}</Default></Condition>'
    )
    return (
        f'<ComplicationSlot slotId="{slot_id}" name="{label_key}" displayName="{label_key}" '
        f'x="{x}" y="{y}" width="{w}" height="{h}" supportedTypes="SHORT_TEXT RANGED_VALUE EMPTY">'
        f'<DefaultProviderPolicy defaultSystemProvider="{provider}" defaultSystemProviderType="SHORT_TEXT"/>'
        f'<BoundingArc centerX="{C - x}" centerY="{C - y}" width="{2 * R_RING_TEXT}" height="{2 * R_RING_TEXT}" '
        f'thickness="44" startAngle="{rng[0]}" endAngle="{rng[1]}"/>'
        f'<Complication type="SHORT_TEXT">{body}</Complication>'
        f'<Complication type="RANGED_VALUE">{body}</Complication>'
        '<Variant mode="AMBIENT" target="alpha" value="0"/>'
        "</ComplicationSlot>"
    ), mid


def bottom_complication():
    x, y, w, h = sector_bounds(*BOTTOM_SLOT)
    rng = (BOTTOM_SLOT[0] + 4, BOTTOM_SLOT[1] - 4)
    txt = lambda fmt, params: circular_text(
        rng, font(FONT_LABEL, RING_TEXT_SIZE, FG, template(fmt, params), upper=True),
        ox=x, oy=y, clockwise=False)
    body = (
        "<Condition><Expressions>"
        '<Expression name="has_title"><![CDATA[[COMPLICATION.TITLE] != null]]></Expression>'
        "</Expressions>"
        f'<Compare expression="has_title">{txt("%s %s", ["[COMPLICATION.TEXT]", "[COMPLICATION.TITLE]"])}</Compare>'
        f'<Default>{txt("%s", ["[COMPLICATION.TEXT]"])}</Default></Condition>'
    )
    return (
        f'<ComplicationSlot slotId="3" name="slot_bottom" displayName="slot_bottom" '
        f'x="{x}" y="{y}" width="{w}" height="{h}" supportedTypes="LONG_TEXT SHORT_TEXT EMPTY">'
        '<DefaultProviderPolicy defaultSystemProvider="NEXT_EVENT" defaultSystemProviderType="LONG_TEXT"/>'
        f'<BoundingArc centerX="{C - x}" centerY="{C - y}" width="{2 * R_RING_TEXT}" height="{2 * R_RING_TEXT}" '
        f'thickness="44" startAngle="{BOTTOM_SLOT[0]}" endAngle="{BOTTOM_SLOT[1]}"/>'
        f'<Complication type="LONG_TEXT">{body}</Complication>'
        f'<Complication type="SHORT_TEXT">{body}</Complication>'
        '<Variant mode="AMBIENT" target="alpha" value="0"/>'
        "</ComplicationSlot>"
    )


def battery_icon():
    levels = [("bat_4", "[BATTERY_PERCENT] > 75"), ("bat_3", "[BATTERY_PERCENT] > 50"),
              ("bat_2", "[BATTERY_PERCENT] > 25"), ("bat_1", "[BATTERY_PERCENT] > 10")]
    exprs = "".join(f'<Expression name="{n}"><![CDATA[{e}]]></Expression>' for n, e in levels)
    launch = '<Launch target="BATTERY_STATUS"/>'
    compares = "".join(f'<Compare expression="{n}">{ring_image(BAT_ICON_ANGLE, n, FG, extra=launch)}</Compare>'
                       for n, _ in levels)
    return (f"<Condition><Expressions>{exprs}</Expressions>{compares}"
            f"<Default>{ring_image(BAT_ICON_ANGLE, 'bat_0', FG, extra=launch)}</Default></Condition>")


def build_xml():
    s = []
    s.append('<?xml version="1.0" encoding="UTF-8"?>')
    s.append("<!-- Generated by tools/generate.py - edit the generator, not this file. -->")
    s.append(f'<WatchFace width="{SIZE}" height="{SIZE}">')
    s.append('<Metadata key="CLOCK_TYPE" value="DIGITAL"/>')
    s.append('<Metadata key="PREVIEW_TIME" value="10:08:32"/>')
    s.append("<UserConfigurations>")
    s.append('<ColorConfiguration id="theme" displayName="theme_label" defaultValue="0">')
    for tid, key, _, bg, fg, arc, aod in THEMES:
        s.append(f'<ColorOption id="{tid}" displayName="{key}" colors="{bg} {fg} {arc} {aod}"/>')
    s.append("</ColorConfiguration>")
    s.append('<BooleanConfiguration id="showArc" displayName="show_arc_label" defaultValue="TRUE"/>')
    s.append("</UserConfigurations>")
    s.append(weather_bitmap_fonts())
    s.append('<Scene backgroundColor="#FF000000">')

    # ---------------- Active (interactive) layer ----------------
    s.append(f'<Group name="active" x="0" y="0" width="{SIZE}" height="{SIZE}">')
    s.append('<Variant mode="AMBIENT" target="alpha" value="0"/>')
    s.append(f'<PartDraw name="background" x="0" y="0" width="{SIZE}" height="{SIZE}">'
             f'<Rectangle x="0" y="0" width="{SIZE}" height="{SIZE}"><Fill color="{BG}"/></Rectangle></PartDraw>')
    ticks = "".join(
        f'<Line startX="{polar(R_INNER, a)[0]:.1f}" startY="{polar(R_INNER, a)[1]:.1f}" '
        f'endX="{polar(SIZE / 2 + 4, a)[0]:.1f}" endY="{polar(SIZE / 2 + 4, a)[1]:.1f}">'
        f'<Stroke color="{FG}" thickness="{TICK_STROKE}"/></Line>' for a in TICK_ANGLES)
    s.append(f'<PartDraw name="frame" x="0" y="0" width="{SIZE}" height="{SIZE}">'
             f'<Ellipse x="{C - R_INNER}" y="{C - R_INNER}" width="{2 * R_INNER}" height="{2 * R_INNER}">'
             f'<Stroke color="{FG}" thickness="{INNER_STROKE}"/></Ellipse>{ticks}</PartDraw>')
    # Step progress arc
    s.append('<BooleanConfiguration id="showArc"><BooleanOption id="TRUE">')
    s.append(f'<PartDraw name="step_arc" x="0" y="0" width="{SIZE}" height="{SIZE}">'
             f'<Arc centerX="{C}" centerY="{C}" width="{2 * R_ARC}" height="{2 * R_ARC}" startAngle="0" endAngle="0">'
             f'<Stroke color="{ARC}" thickness="{ARC_STROKE}" cap="ROUND"/>'
             f'<Transform target="endAngle" value="clamp([STEP_PERCENT], 0, 100) * {ARC_SWEEP / 100}"/></Arc></PartDraw>')
    s.append("</BooleanOption></BooleanConfiguration>")
    # Steps (top)
    s.append(circular_text(STEPS_RANGE, font(FONT_LABEL, RING_TEXT_SIZE, FG,
                                             template("STEPS: %s", ["[STEP_COUNT]"])), name="steps"))
    # Heart rate (right upper)
    hr_launch = '<Launch target="HEALTH_HEART_RATE"/>'
    s.append(ring_image(HR_ICON_ANGLE, "ic_heart", FG, extra=hr_launch))
    s.append(circular_text(HR_TEXT_RANGE, font(FONT_LABEL, RING_TEXT_SIZE, FG, template(
        "%s", ['[HEART_RATE] > 0 ? [HEART_RATE] : "--"'])), name="heart_rate"))
    # Battery (left upper)
    s.append(battery_icon())
    s.append(circular_text(BAT_TEXT_RANGE, font(FONT_LABEL, RING_TEXT_SIZE, FG, template(
        "%s%s", ["[BATTERY_PERCENT]", '"%"'])), name="battery"))
    s.append(clock_stack(FG))
    s.append("</Group>")

    # ---------------- Complications ----------------
    left, _ = ring_complication(1, "slot_left", LEFT_SLOT, LEFT_TEXT_RANGE, LEFT_ICON_ANGLE, True, "EMPTY")
    right, _ = ring_complication(2, "slot_right", RIGHT_SLOT, RIGHT_TEXT_RANGE, RIGHT_ICON_ANGLE, True, "EMPTY")
    s += [left, right, bottom_complication()]

    # ---------------- Always-on layer ----------------
    s.append(f'<Group name="ambient" x="0" y="0" width="{SIZE}" height="{SIZE}" alpha="0">')
    s.append('<Variant mode="AMBIENT" target="alpha" value="255"/>')
    s.append(clock_stack(AOD, launch=False))
    s.append("</Group>")

    s.append("</Scene></WatchFace>")
    return "\n".join(s) + "\n"


def build_strings():
    items = [("app_name", "Pulse Ring"), ("theme_label", "Theme"), ("show_arc_label", "Step progress arc"),
             ("slot_left", "Left ring (e.g. Alarm)"), ("slot_right", "Right ring (e.g. Sleep)"),
             ("slot_bottom", "Bottom ring (e.g. Next event)")]
    items += [(key, label) for _, key, label, *_ in THEMES]
    body = "\n".join(f'    <string name="{k}">{escape(v)}</string>' for k, v in items)
    return f'<?xml version="1.0" encoding="utf-8"?>\n<resources>\n{body}\n</resources>\n'


# --------------------------------------------------------------------------
# Icons (white on transparent, tinted at runtime)
# --------------------------------------------------------------------------
SS = 4  # supersampling


def canvas(n=96):
    im = Image.new("RGBA", (n * SS, n * SS), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def finish(im, n=96):
    return im.resize((n, n), Image.LANCZOS)


def S(*v):
    return [x * SS for x in v]


W = (255, 255, 255, 255)


def cloud(d, ox=0, oy=0, sc=1.0, width=5):
    """Outlined cloud. Built as a solid shape whose rim is kept, so it is seamless;
    whatever was drawn underneath the cloud is cleared."""
    im = d._image
    m = Image.new("L", im.size, 0)
    md = ImageDraw.Draw(m)

    def circ(cx, cy, r):
        md.ellipse(S(ox + (cx - r) * sc, oy + (cy - r) * sc, ox + (cx + r) * sc, oy + (cy + r) * sc), fill=255)
    circ(30, 54, 15)
    circ(47, 38, 19)
    circ(66, 52, 15)
    md.rounded_rectangle(S(ox + 15 * sc, oy + 46 * sc, ox + 81 * sc, oy + 69 * sc), radius=11 * sc * SS, fill=255)
    im.paste((0, 0, 0, 0), mask=m)
    rim = ImageChops.subtract(m, m.filter(ImageFilter.MinFilter(2 * width * SS + 1)))
    im.paste(Image.new("RGBA", im.size, W), mask=rim)


def sun(d, cx, cy, r, rays=True, width=5):
    lw = int(width * SS)
    d.ellipse(S(cx - r, cy - r, cx + r, cy + r), outline=W, width=lw)
    if rays:
        for i in range(8):
            a = math.radians(i * 45)
            d.line(S(cx + (r + 7) * math.cos(a), cy + (r + 7) * math.sin(a),
                     cx + (r + 17) * math.cos(a), cy + (r + 17) * math.sin(a)), fill=W, width=lw)


def moon(d, cx, cy, r, im, fill=False, width=5):
    m = Image.new("L", im.size, 0)
    md = ImageDraw.Draw(m)
    md.ellipse(S(cx - r, cy - r, cx + r, cy + r), fill=255)
    md.ellipse(S(cx - r * 0.35, cy - r * 1.15, cx + r * 1.45, cy + r * 0.65), fill=0)
    if not fill:
        # keep only a stroke-wide rim of the crescent
        eroded = m.filter(ImageFilter.MinFilter(2 * width * SS + 1))
        m = ImageChops.subtract(m, eroded)
    im.paste(Image.new("RGBA", im.size, W), mask=m)


def drops(d, xs, y0, length, width=5):
    for x in xs:
        d.line(S(x, y0, x - 4, y0 + length), fill=W, width=int(width * SS))


def flake(d, cx, cy, r, width=4):
    for i in range(3):
        a = math.radians(i * 60)
        d.line(S(cx - r * math.cos(a), cy - r * math.sin(a), cx + r * math.cos(a), cy + r * math.sin(a)),
               fill=W, width=int(width * SS))


def make_weather_icons():
    icons = {}

    im, d = canvas(); sun(d, 48, 48, 18); icons["wx_clear_day"] = im
    im, d = canvas(); moon(d, 48, 48, 30, im, fill=True); icons["wx_clear_night"] = im
    im, d = canvas(); cloud(d, 0, 6); icons["wx_cloudy"] = im
    im, d = canvas()
    for i, y in enumerate((30, 46, 62, 78)):
        d.line(S(14 + 6 * (i % 2), y, 82 - 6 * ((i + 1) % 2), y), fill=W, width=5 * SS)
    icons["wx_fog"] = im
    im, d = canvas(); cloud(d, 0, -8); drops(d, (32, 50, 68), 70, 16); icons["wx_rain"] = im
    im, d = canvas(); cloud(d, 0, -8); drops(d, (26, 40, 54, 68), 68, 22); icons["wx_heavy_rain"] = im
    im, d = canvas(); cloud(d, 0, -8); [flake(d, x, 80, 7) for x in (32, 50, 68)]; icons["wx_snow"] = im
    im, d = canvas(); cloud(d, 0, -10)
    [flake(d, x, y, 6) for x, y in ((26, 74), (44, 84), (60, 74), (76, 84))]; icons["wx_heavy_snow"] = im
    im, d = canvas(); cloud(d, 0, -8); drops(d, (34,), 70, 16); flake(d, 60, 80, 7); icons["wx_sleet"] = im
    im, d = canvas(); cloud(d, 0, -10)
    d.line(S(52, 62, 40, 78, 54, 78, 44, 94), fill=W, width=5 * SS, joint="curve"); icons["wx_thunder"] = im
    im, d = canvas()
    d.line(S(12, 36, 62, 36), fill=W, width=5 * SS); d.arc(S(54, 20, 74, 40), 180, 90, fill=W, width=5 * SS)
    d.line(S(12, 52, 76, 52), fill=W, width=5 * SS)
    d.line(S(12, 68, 56, 68), fill=W, width=5 * SS); d.arc(S(48, 60, 66, 78), 270, 180, fill=W, width=5 * SS)
    icons["wx_windy"] = im
    im, d = canvas(); sun(d, 34, 34, 12); cloud(d, 10, 14, 0.95); icons["wx_partly_day"] = im
    im, d = canvas(); moon(d, 34, 32, 20, im, fill=True); cloud(d, 10, 14, 0.95); icons["wx_partly_night"] = im
    im, d = canvas(); cloud(d, 0, 6)
    d.text((40 * SS, 38 * SS), "?", fill=W, font=ImageFont.truetype(font_path(FONT_LABEL), 30 * SS))
    icons["wx_unknown"] = im
    return {k: finish(v) for k, v in icons.items()}


def make_ring_icons():
    icons = {}
    n = 64
    # heart with a pulse line cut out
    im, d = canvas(n)
    hs = [(32 + 26 * (16 * math.sin(t) ** 3) / 16,
           30 - 24 * (13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)) / 16)
          for t in [i * 2 * math.pi / 200 for i in range(200)]]
    d.polygon([(x * SS, y * SS) for x, y in hs], fill=W)
    d.line(S(0, 30, 20, 30, 26, 20, 34, 42, 40, 30, 64, 30), fill=(0, 0, 0, 0), width=4 * SS, joint="curve")
    icons["ic_heart"] = finish(im, n)
    # batteries drawn horizontally (terminal on the right); rotated onto the ring
    for lvl in range(5):
        im, d = canvas(n)
        d.rounded_rectangle(S(2, 14, 54, 50), radius=5 * SS, outline=W, width=5 * SS)
        d.rectangle(S(54, 24, 62, 40), fill=W)
        for b in range(lvl):
            d.rectangle(S(10 + b * 10.5, 22, 17 + b * 10.5, 42), fill=W)
        icons[f"bat_{lvl}"] = finish(im, n)
    return icons


# --------------------------------------------------------------------------
# Preview renderer (approximates the on-watch rendering)
# --------------------------------------------------------------------------
def font_path(name):
    return os.path.join(RES, "font", name + ".ttf")


def hexc(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (255,)


def tint(icon, color):
    out = Image.new("RGBA", icon.size, hexc(color))
    out.putalpha(icon.getchannel("A"))
    return out


def draw_flat(img, text, fname, size, color, cap_y, cx=C):
    f = ImageFont.truetype(font_path(fname), size)
    d = ImageDraw.Draw(img)
    asc = size * (1.193 if "oswald" in fname else 0.968)
    capf = 0.810 if "oswald" in fname else 0.700
    baseline = cap_y + size * capf / 2
    w = d.textlength(text, font=f)
    d.text((cx - w / 2, baseline - asc), text, font=f, fill=hexc(color))


def draw_curved(img, text, fname, size, color, center_deg, clockwise=True, r=R_RING_TEXT):
    f = ImageFont.truetype(font_path(fname), size)
    d0 = ImageDraw.Draw(img)
    widths = [d0.textlength(ch, font=f) for ch in text]
    total = sum(widths)
    step = 1 if clockwise else -1
    pos = -total / 2
    for ch, w in zip(text, widths):
        mid = pos + w / 2
        deg = center_deg + step * math.degrees(mid / r)
        pos += w
        if ch == " ":
            continue
        tile = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
        td = ImageDraw.Draw(tile)
        asc = size * 1.193
        td.text((size - w / 2, size + size * 0.405 - asc), ch, font=f, fill=hexc(color))
        rot = deg if clockwise else deg + 180
        tile = tile.rotate(-rot, resample=Image.BICUBIC)
        x, y = polar(r, deg)
        img.alpha_composite(tile, (round(x - size), round(y - size)))


def paste_center(img, icon, x, y, size, color, rot=0):
    ic = tint(icon, color).resize((size, size), Image.LANCZOS)
    if rot:
        ic = ic.rotate(-rot, resample=Image.BICUBIC, expand=True)
    img.alpha_composite(ic, (round(x - ic.width / 2), round(y - ic.height / 2)))


def render(theme, wx_icons, ring_icons, ambient=False, sample=None):
    _, _, _, bg, fg, arc, aod = theme
    sample = sample or {}
    sc = 2
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 255))
    d = ImageDraw.Draw(img)
    col = aod if ambient else fg
    if not ambient:
        d.rectangle((0, 0, SIZE, SIZE), fill=hexc(bg))
        d.ellipse((C - R_INNER, C - R_INNER, C + R_INNER, C + R_INNER), outline=hexc(fg), width=INNER_STROKE)
        for a in TICK_ANGLES:
            d.line((*polar(R_INNER, a), *polar(SIZE / 2 + 4, a)), fill=hexc(fg), width=TICK_STROKE)
        d.arc((C - R_ARC, C - R_ARC, C + R_ARC, C + R_ARC), -90, -90 + 0.66 * ARC_SWEEP, fill=hexc(arc), width=ARC_STROKE)
        draw_curved(img, "STEPS: 6628", FONT_LABEL, RING_TEXT_SIZE, fg, 0)
        paste_center(img, ring_icons["ic_heart"], *polar(R_RING_TEXT, HR_ICON_ANGLE), RING_ICON, fg, HR_ICON_ANGLE)
        draw_curved(img, "92", FONT_LABEL, RING_TEXT_SIZE, fg, sum(HR_TEXT_RANGE) / 2)
        paste_center(img, ring_icons["bat_2"], *polar(R_RING_TEXT, BAT_ICON_ANGLE), RING_ICON, fg, BAT_ICON_ANGLE)
        draw_curved(img, "41%", FONT_LABEL, RING_TEXT_SIZE, fg, sum(BAT_TEXT_RANGE) / 2)
        draw_curved(img, "NO ALARMS", FONT_LABEL, RING_TEXT_SIZE, fg, sum(LEFT_TEXT_RANGE) / 2, clockwise=False)
        paste_center(img, ring_icons["alarm"], *polar(R_RING_TEXT, LEFT_ICON_ANGLE), RING_ICON, fg,
                     LEFT_ICON_ANGLE + 180)
        draw_curved(img, "3H 50M", FONT_LABEL, RING_TEXT_SIZE, fg, sum(RIGHT_TEXT_RANGE) / 2, clockwise=False)
        paste_center(img, ring_icons["moon"], *polar(R_RING_TEXT, RIGHT_ICON_ANGLE), RING_ICON, fg,
                     RIGHT_ICON_ANGLE + 180)
        draw_curved(img, "NO UPCOMING EVENTS", FONT_LABEL, RING_TEXT_SIZE, fg, 180, clockwise=False)
    paste_center(img, wx_icons["wx_cloudy"], C, WEATHER_ICON_Y, WEATHER_ICON, col)
    draw_flat(img, "NOW: 8°C   H 9°/L 7°", FONT_LABEL, WEATHER_TEXT_SIZE, col, WEATHER_TEXT_Y)
    for ly in (LINE1_Y, LINE2_Y):
        d.line((C - LINE_HALF, ly, C + LINE_HALF, ly), fill=hexc(col), width=3)
    draw_flat(img, sample.get("time", "23:58"), FONT_TIME, TIME_SIZE, col, TIME_Y)
    draw_flat(img, "Wednesday", FONT_DAY, DAY_SIZE, col, DAY_Y)
    draw_flat(img, "03", FONT_DAY, DATE_SIZE, col, DATE_Y)
    # round mask like the real display
    mask = Image.new("L", (SIZE * sc, SIZE * sc), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, SIZE * sc - 1, SIZE * sc - 1), fill=255)
    mask = mask.resize((SIZE, SIZE), Image.LANCZOS)
    out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    out.paste(img, mask=mask)
    return out


def preview_only_icons():
    icons = {}
    n = 64
    im, d = canvas(n)
    d.ellipse(S(12, 14, 52, 54), outline=W, width=5 * SS)
    d.line(S(32, 22, 32, 34, 40, 40), fill=W, width=4 * SS)
    d.line(S(8, 16, 18, 8), fill=W, width=5 * SS); d.line(S(56, 16, 46, 8), fill=W, width=5 * SS)
    icons["alarm"] = finish(im, n)
    im, d = canvas(n); moon(d, 32, 32, 24, im, fill=True); icons["moon"] = finish(im, n)
    return icons


def main():
    os.makedirs(DOCS, exist_ok=True)
    with open(os.path.join(RES, "raw", "watchface.xml"), "w", encoding="utf-8") as fh:
        fh.write(build_xml())
    with open(os.path.join(RES, "values", "strings.xml"), "w", encoding="utf-8") as fh:
        fh.write(build_strings())
    wx = make_weather_icons()
    ring = make_ring_icons()
    for name, im in {**wx, **ring}.items():
        im.save(os.path.join(RES, "drawable", name + ".png"), optimize=True)
    ring.update(preview_only_icons())

    render(THEMES[0], wx, ring).save(os.path.join(RES, "drawable", "preview.png"), optimize=True)
    tiles = [render(THEMES[0], wx, ring), render(THEMES[1], wx, ring),
             render(THEMES[0], wx, ring, ambient=True)]
    for t in THEMES:
        render(t, wx, ring).save(os.path.join(DOCS, f"{t[1]}.png"), optimize=True)
    render(THEMES[2], wx, ring, ambient=True, sample={"time": "10:09"}).save(
        os.path.join(DOCS, "aod_gold.png"), optimize=True)
    strip = Image.new("RGBA", (SIZE * 3 + 40, SIZE), (0, 0, 0, 0))
    for i, t in enumerate(tiles):
        strip.alpha_composite(t, (i * (SIZE + 20), 0))
    strip.save(os.path.join(DOCS, "overview.png"), optimize=True)
    grid = Image.new("RGBA", (4 * 230, 4 * 230), (0, 0, 0, 0))
    for i, t in enumerate(THEMES):
        grid.alpha_composite(render(t, wx, ring).resize((220, 220), Image.LANCZOS), ((i % 4) * 230, (i // 4) * 230))
    grid.save(os.path.join(DOCS, "themes.png"), optimize=True)
    print("generated", len(THEMES), "themes")


if __name__ == "__main__":
    main()
