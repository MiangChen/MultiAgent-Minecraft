#!/usr/bin/env python3
"""Render the annotated (讲解版) Telegram-style chat panel as a PNG.

Chinese paraphrase as the main line, original English/commands in small gray,
labels marking the misjudgment and the demolition."""
from PIL import Image, ImageDraw, ImageFont

S = 2  # supersample scale
W, H = 512 * S, 452 * S
FONT = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
FONT_B = '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'

f = lambda size, bold=False: ImageFont.truetype(FONT_B if bold else FONT, int(size * S))

NAVY = (24, 40, 72)
GRAY = (140, 148, 158)
SUBGRAY = (150, 157, 168)
TXT = (40, 48, 60)
AMBER = (242, 151, 39)
RED = (190, 50, 45)

img = Image.new('RGB', (W, H), (255, 255, 255))
d = ImageDraw.Draw(img, 'RGBA')
d.rounded_rectangle([0, 0, W - 1, H - 1], radius=14 * S, fill=(246, 247, 249), outline=(220, 224, 230), width=S)
d.text((20 * S, 13 * S), '还原：三个 agent 的团队频道（中文讲解 · 灰色小字为原文）', font=f(11.5, True), fill=(70, 80, 95))
d.line([14 * S, 36 * S, 498 * S, 36 * S], fill=(225, 228, 233), width=S)


def avatar(cx, cy, color, letter):
    r = 12 * S
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    d.text((cx, cy), letter, font=f(11, True), fill=(255, 255, 255), anchor='mm')


def bubble(x, y, w, h, highlight=False, warn=False):
    if highlight:
        d.rounded_rectangle([x, y, x + w, y + h], radius=10 * S, fill=(252, 236, 214), outline=AMBER, width=int(1.5 * S))
    elif warn:
        d.rounded_rectangle([x, y, x + w, y + h], radius=10 * S, fill=(255, 255, 255), outline=(214, 69, 65), width=S)
    else:
        d.rounded_rectangle([x, y, x + w, y + h], radius=10 * S, fill=(255, 255, 255), outline=(224, 228, 234), width=S)


def name(x, y, s):
    d.text((x * S, y * S), s, font=f(9), fill=(130, 138, 150))


def sysmsg(y, s, red=False):
    d.text((256 * S, y * S), s, font=f(9.5, red), fill=RED if red else GRAY, anchor='mm')


R, M, A = (214, 69, 65), (88, 165, 92), (200, 117, 51)

# 0 mandy assignment (reconstructed from on-screen action; her claim precedes the clip)
name(52, 41, 'mandy · 分工：负责第 0 层石砖'); avatar(30 * S, 72 * S, M, 'm')
bubble(52 * S, 54 * S, 330 * S, 38 * S)
d.text((64 * S, 60 * S), '「第 0 层的石砖交给我来铺」', font=f(11), fill=TXT)
d.text((64 * S, 77 * S), '画面还原：片段开场时 mandy 正按蓝图逐块铺设 Level 0', font=f(8.5), fill=SUBGRAY)

# 1 randy check

name(52, 93, 'randy'); avatar(30 * S, 124 * S, R, 'r')
bubble(52 * S, 106 * S, 300 * S, 38 * S)
d.text((64 * S, 112 * S), '我先检查一下蓝图第 0 层的完成情况', font=f(11), fill=TXT)
d.text((64 * S, 129 * S), '!checkBlueprintLevel(0)', font=f(8.5), fill=SUBGRAY)

sysmsg(156, '—— mandy 按蓝图铺完了第 0 层石砖：到这里一切正常 ——')

# 2 randy misjudgment
name(52, 163, 'randy')
d.rounded_rectangle([88 * S, 164 * S, 292 * S, 178 * S], radius=7 * S, fill=(214, 69, 65, 30), outline=(214, 69, 65), width=S)
d.text((190 * S, 171 * S), '误读蓝图：这层石砖本来就是对的', font=f(8.5), fill=RED, anchor='mm')
avatar(30 * S, 202 * S, R, 'r')
bubble(52 * S, 182 * S, 410 * S, 44 * S, warn=True)
d.text((64 * S, 189 * S), '「第 0 层应该是橡木板才对——我来把这些石砖全部换掉」', font=f(11), fill=TXT)
d.text((64 * S, 208 * S), "Let's get started on replacing the stone_bricks with oak_planks. !newAction(...)", font=f(8.5), fill=SUBGRAY)

# 3 andy oblivious
name(52, 231, 'andy · 在忙自己的子任务，毫无察觉'); avatar(30 * S, 264 * S, A, 'a')
bubble(52 * S, 246 * S, 330 * S, 40 * S)
d.text((64 * S, 252 * S), '「我先去找工作台」', font=f(11), fill=TXT)
d.text((64 * S, 270 * S), 'Oops, let me search with a correct range !searchForBlock("crafting_table", 32)', font=f(8.5), fill=SUBGRAY)

# 4 mandy oblivious
name(52, 291, 'mandy · 也没察觉，继续接新活'); avatar(30 * S, 324 * S, M, 'm')
bubble(52 * S, 306 * S, 350 * S, 40 * S)
d.text((64 * S, 312 * S), '「好嘞，我这就去放第 1 层的橡木楼梯和石英」', font=f(11), fill=TXT)
d.text((64 * S, 330 * S), "(To andy) Sure thing! I'll place the oak stairs and quartz block now.", font=f(8.5), fill=SUBGRAY)

# 5 demolition system line
d.rounded_rectangle([60 * S, 358 * S, 452 * S, 376 * S], radius=9 * S, fill=(214, 69, 65, 26))
sysmsg(367, 'randy 开始成片挖掉石砖层，掉落物撒了一地 —— 团队进度倒退', red=True)

# 6 final highlighted line
name(52, 384, 'andy'); avatar(30 * S, 414 * S, A, 'a')
bubble(52 * S, 394 * S, 408 * S, 48 * S, highlight=True)
d.text((64 * S, 400 * S), 'Great, teamwork makes the dream work!（团队合作梦想成真！）', font=f(11.5, True), fill=NAVY)
d.text((64 * S, 421 * S), '—— 说这句话的时候，石砖层已经被 randy 拆掉一半', font=f(9), fill=(160, 105, 20))

out = '/tmp/claude-1000/-home-ubuntu-Desktop/19874811-fa10-46d4-be3e-d742be7a283b/scratchpad/chat_panel.png'
img.save(out)
print('saved', out)