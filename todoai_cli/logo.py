"""ASCII block logo for TODOforAI CLI."""
import sys

# Letter bitmaps: 6 rows tall, 4 wide (except 'i' = 2 wide)
# 'x' = bright white, 'l' = gray, ' ' = black
# Rows 0-2: top half (crisp), rows 3-5: bottom half (gray gradient)
LETTERS = {
    't': [
        ' x  ',
        'xxxx',
        ' x  ',
        ' xll',
        ' xll',
        ' xxx',
    ],
    'o': [
        '    ',
        'xxxx',
        'x  x',
        'xllx',
        'xllx',
        'xxxx',
    ],
    'd': [
        '   x',
        'xxxx',
        'x  x',
        'xllx',
        'xllx',
        'xxxx',
    ],
    'f': [
        '  xx',
        ' x  ',
        'xxxx',
        'lxll',
        'lxll',
        'lxll',
    ],
    'r': [
        '    ',
        'x xx',
        'xx  ',
        'xlll',
        'xlll',
        'xlll',
    ],
    'c': [
        '    ',
        'xxxx',
        'x   ',
        'xlll',
        'xlll',
        'xxxx',
    ],
    'e': [
        '    ',
        'xxxx',
        'x  x',
        'xxxx',
        'xlll',
        'xxxx',
    ],
    'a': [
        '    ',
        'xxxx',
        '   x',
        'xxxx',
        'xllx',
        'xxxx',
    ],
    'i': [
        'x',
        ' ',
        'x',
        'x',
        'x',
        'x',
    ],
    '4': [
        '    ',
        '  x ',
        ' xx ',
        'xlxl',
        'xxxx',
        'llxl',
    ],
}

GAP = ' '  # 1 char between letters
WORD = 'todo4ai'


def _render_half_block(top, bot):
    """Map a (top, bottom) pixel pair to an ANSI half-block string."""
    W  = '\033[97m'     # bright white fg
    G  = '\033[90m'     # gray fg
    BW = '\033[107m'    # bright white bg
    BG = '\033[100m'    # gray bg
    R  = '\033[0m'

    if top == ' ' and bot == ' ':
        return ' '
    if top == bot:
        fg = W if top == 'x' else G
        return f'{fg}\u2588{R}'
    if top == ' ':
        fg = W if bot == 'x' else G
        return f'{fg}\u2584{R}'
    if bot == ' ':
        fg = W if top == 'x' else G
        return f'{fg}\u2580{R}'
    # Mixed colors: use upper-half block (top=fg, bottom=bg)
    fg = W if top == 'x' else G
    bg = BW if bot == 'x' else BG
    return f'{fg}{bg}\u2580{R}'


def render_logo():
    """Return the logo as a list of 3 terminal lines."""
    # Build 6 pixel rows
    rows = []
    for row_idx in range(6):
        row = ''
        for i, ch in enumerate(WORD):
            if i > 0:
                row += GAP
            row += LETTERS[ch][row_idx]
        rows.append(row)

    # Pair rows into 3 half-block lines
    lines = []
    for pair in range(3):
        top_row = rows[pair * 2]
        bot_row = rows[pair * 2 + 1]
        max_len = max(len(top_row), len(bot_row))
        top_row = top_row.ljust(max_len)
        bot_row = bot_row.ljust(max_len)
        line = ''.join(_render_half_block(t, b) for t, b in zip(top_row, bot_row))
        lines.append(line)
    return lines


def print_logo(file=None):
    """Print the TODOforAI logo to stderr."""
    if file is None:
        file = sys.stderr
    for line in render_logo():
        print(f'  {line}', file=file)
    print(file=file)
