"""
SVG rendering shared by bip39_dice.py and bip39_svg.py (standard library only).

Draws a BIP39 mnemonic as a printable grid, either as vector strokes from a
built-in font (no searchable text in the file) or as plain <text>, in order,
shuffled, or split into a words sheet and an order sheet.
"""

import os
import secrets
from xml.sax.saxutils import escape

# Stroke font used by the obfuscated SVG output. Each glyph is an SVG path in a
# 6-unit-wide monospace cell: ascender top y=0, x-height y=3, baseline y=7,
# descender bottom y=10. Glyphs are drawn as strokes, never as <text>, so the
# SVG file contains no readable words.
STROKE_FONT = {
    "a": "M4.5,3 V7 M0.5,5 A2,2 0 1 0 4.5,5 A2,2 0 1 0 0.5,5",
    "b": "M0.5,0 V7 M0.5,5 A2,2 0 1 1 4.5,5 A2,2 0 1 1 0.5,5",
    "c": "M4.3,4 A2,2 0 1 0 4.3,6",
    "d": "M4.5,0 V7 M4.5,5 A2,2 0 1 0 0.5,5 A2,2 0 1 0 4.5,5",
    "e": "M0.5,5 H4.5 A2,2 0 1 0 4,6.3",
    "f": "M4,0.5 H3 A1.5,1.5 0 0 0 1.5,2 V7 M0.3,3 H3.7",
    "g": "M4.5,3 V8 A2,2 0 0 1 0.8,9 M0.5,5 A2,2 0 1 0 4.5,5 A2,2 0 1 0 0.5,5",
    "h": "M0.5,0 V7 M0.5,5 A2,2 0 0 1 4.5,5 V7",
    "i": "M2.5,3 V7 M2.5,1.3 h0.01",
    "j": "M3.5,3 V8.5 A1.5,1.5 0 0 1 0.5,8.5 M3.5,1.3 h0.01",
    "k": "M0.5,0 V7 M4,3 L0.5,5.5 M1.8,4.6 L4.5,7",
    "l": "M2,0 V6 A1,1 0 0 0 3,7 H3.5",
    "m": "M0.5,3 V7 M0.5,4.5 A1,1.5 0 0 1 2.5,4.5 V7 M2.5,4.5 A1,1.5 0 0 1 4.5,4.5 V7",
    "n": "M0.5,3 V7 M0.5,5 A2,2 0 0 1 4.5,5 V7",
    "o": "M2.5,3 A2,2 0 1 1 2.5,7 A2,2 0 1 1 2.5,3",
    "p": "M0.5,3 V10 M0.5,5 A2,2 0 1 1 4.5,5 A2,2 0 1 1 0.5,5",
    "q": "M4.5,3 V10 M4.5,5 A2,2 0 1 0 0.5,5 A2,2 0 1 0 4.5,5",
    "r": "M0.5,3 V7 M0.5,5.2 A2.2,2.2 0 0 1 4.2,3.6",
    "s": "M4.2,3.6 C3.5,2.7 0.6,2.8 0.8,4.2 C1,5.3 4.2,4.8 4.3,6 C4.4,7.4 1.2,7.4 0.5,6.4",
    "t": "M2,1 V6 A1,1 0 0 0 3,7 H4 M0.5,3 H4",
    "u": "M0.5,3 V5 A2,2 0 0 0 4.5,5 M4.5,3 V7",
    "v": "M0.5,3 L2.5,7 L4.5,3",
    "w": "M0.2,3 L1.3,7 L2.5,4 L3.7,7 L4.8,3",
    "x": "M0.5,3 L4.5,7 M4.5,3 L0.5,7",
    "y": "M0.5,3 L2.5,7 M4.5,3 L1,10",
    "z": "M0.5,3 H4.5 L0.5,7 H4.5",
    "0": "M2.5,0 A2,3.5 0 1 1 2.5,7 A2,3.5 0 1 1 2.5,0",
    "1": "M1,1.5 L2.8,0 V7 M1,7 H4.5",
    "2": "M0.6,1.6 A2,1.9 0 0 1 4.4,2 C4.4,3.5 0.5,5 0.5,7 H4.5",
    "3": "M0.7,1 A1.9,1.7 0 1 1 2.3,3.5 A2,1.75 0 1 1 0.5,6",
    "4": "M3.5,7 V0 L0.3,5 H4.7",
    "5": "M4.3,0.3 H1.1 L0.8,3.4 C1.5,2.8 4.5,2.6 4.5,5 C4.5,7.6 1.2,7.4 0.5,6.3",
    "6": "M3.8,0.4 C1.8,0.6 0.5,2.5 0.5,5 A2,2 0 1 0 4.5,5 A2,2 0 1 0 0.5,5",
    "7": "M0.5,0 H4.5 L1.8,7",
    "8": "M2.5,0.1 A1.65,1.65 0 1 1 2.5,3.4 A1.65,1.65 0 1 1 2.5,0.1 "
         "M2.5,3.4 A1.9,1.8 0 1 1 2.5,7 A1.9,1.8 0 1 1 2.5,3.4",
    "9": "M4.5,2 A2,2 0 1 0 0.5,2 A2,2 0 1 0 4.5,2 C4.5,4.5 3.2,6.4 1.2,6.6",
    "(": "M3,0 Q1,3.5 3,8",
    ")": "M2,0 Q4,3.5 2,8",
    " ": "",
}
GLYPH_ADVANCE = 6      # font units per character
GLYPH_ASCENT = 7       # font units from ascender top to baseline


def svg_text(x, baseline, text, size, color, bold, as_paths):
    """Return SVG for one string, as <text> or as stroked glyph paths.
    `size` is the height in px from ascender top to baseline."""
    if not as_paths:
        weight = ' font-weight="bold"' if bold else ""
        return (f'<text x="{x:.1f}" y="{baseline:.1f}" font-size="{size / 0.72:.1f}" '
                f'fill="{color}"{weight} xml:space="preserve">{escape(text)}</text>')
    scale = size / GLYPH_ASCENT
    stroke = 0.85 if bold else 0.55
    parts = [f'<g transform="translate({x:.1f},{baseline - size:.1f}) scale({scale:.3f})" '
             f'fill="none" stroke="{color}" stroke-width="{stroke}" '
             f'stroke-linecap="round" stroke-linejoin="round">']
    for k, ch in enumerate(text):
        d = STROKE_FONT[ch]
        if d:
            parts.append(f'<path transform="translate({k * GLYPH_ADVANCE},0)" d="{d}"/>')
    parts.append("</g>")
    return "".join(parts)


def text_width(text, size):
    return len(text) * GLYPH_ADVANCE * size / GLYPH_ASCENT


def render_svg(mnemonic, cols, rows, numbered=True, as_paths=True, shuffle=False,
               part="both", order=None, pair_id=None):
    """Render the words as an SVG grid, read left-to-right, top-to-bottom.

    as_paths=True  every character is drawn as vector strokes, so the file
                   contains no searchable text.
    shuffle=True   cells are placed in a random order (CSPRNG) and each word
                   carries its real position in parentheses, e.g. "zoo (17)".
    part           "both"  -> words (and positions) in one image (default);
                   "words" -> shuffled words only, no positions;
                   "order" -> positions only, in the same cells as "words".
                   For the split parts pass the same `order` and `pair_id` to
                   both calls so the two grids line up cell by cell.
    """
    n = len(mnemonic)
    num_w = len(str(n))
    size = 14                         # px from ascender top to baseline
    pad_x, cell_h, margin, title_h = 14, 40, 20, 48
    split = part in ("words", "order")

    if order is None:
        order = list(range(n))        # order[k] = original index shown in cell k
        if shuffle or split:
            secrets.SystemRandom().shuffle(order)
    if split:
        shuffle = True
    word_w = text_width("m" * max(len(w) for w in mnemonic), size)

    if split:
        label_w = tag_w = 0           # identical geometry for both parts
    elif shuffle:
        numbered = True               # positions are mandatory when shuffled
        label_w = 0
        tag_w = text_width(" " + "(" + "0" * num_w + ")", size)
    else:
        label_w = text_width(" " * (num_w + 1), size) if numbered else 0
        tag_w = 0
    cell_w = round(label_w + word_w + tag_w + 2 * pad_x)
    width = 2 * margin + cols * cell_w
    height = 2 * margin + title_h + rows * cell_h

    if split:
        title = f"bip39 {part} (set {pair_id})" if pair_id else f"bip39 {part}"
    else:
        title = f"bip39 seed ({n} words)" if as_paths else f"BIP39 SEED ({n} words)"
    title_size = 17
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        '<g font-family="DejaVu Sans Mono, Consolas, Menlo, monospace">',
        svg_text((width - text_width(title, title_size)) / 2, margin + 26,
                 title, title_size, "#000000", True, as_paths),
    ]
    top = margin + title_h
    for r in range(rows):
        for c in range(cols):
            i = r * cols + c
            x, y = margin + c * cell_w, top + r * cell_h
            out.append(f'<rect x="{x}" y="{y}" width="{cell_w}" height="{cell_h}" '
                       f'fill="none" stroke="#000000" stroke-width="1"/>')
            if i >= n:
                continue
            j = order[i]               # original position of the word in this cell
            baseline = y + cell_h / 2 + size / 2
            tx = x + pad_x
            if part == "order":
                label = str(j + 1)
                out.append(svg_text(x + (cell_w - text_width(label, size)) / 2, baseline,
                                    label, size, "#000000", True, as_paths))
                continue
            if numbered and not shuffle:
                out.append(svg_text(tx, baseline, f"{j + 1:>{num_w}}", size,
                                    "#666666", False, as_paths))
                tx += label_w
            out.append(svg_text(tx, baseline, mnemonic[j], size,
                                "#000000", True, as_paths))
            if shuffle and not split:
                out.append(svg_text(tx + word_w + text_width(" ", size), baseline,
                                    f"({j + 1})", size, "#000000", False, as_paths))
    out += ["</g>", "</svg>", ""]
    return "\n".join(out)


def split_svg_paths(path):
    """seed.svg -> (seed-words.svg, seed-order.svg)"""
    root, ext = os.path.splitext(path)
    ext = ext or ".svg"
    return f"{root}-words{ext}", f"{root}-order{ext}"


def render_svg_split(mnemonic, cols, rows, as_paths=True):
    """Return (words_svg, order_svg): two grids sharing one random layout."""
    order = list(range(len(mnemonic)))
    secrets.SystemRandom().shuffle(order)
    pair_id = secrets.token_hex(2)    # printed on both sheets to pair them
    common = dict(cols=cols, rows=rows, as_paths=as_paths, order=order, pair_id=pair_id)
    return (render_svg(mnemonic, part="words", **common),
            render_svg(mnemonic, part="order", **common),
            pair_id)


def write_private_file(path, content):
    """Create a new file readable only by the owner; refuse to overwrite."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)


def check_svg_destination(path, split=False):
    """Return an error message if the SVG(s) for `path` cannot be written,
    or None if the destination is fine. Call it before asking for secrets."""
    targets = split_svg_paths(path) if split else (path,)
    for t in targets:
        if os.path.exists(t):
            return f"{t} already exists; refusing to overwrite it"
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent) or not os.access(parent, os.W_OK):
        return f"cannot write to directory {parent}"
    return None


def write_svg_output(mnemonic, cols, rows, numbered, svg):
    """Write the SVG file(s) described by `svg` and report where they went.
    svg: dict(path, as_paths, shuffle, split). Raises OSError on failure."""
    if svg["split"]:
        words_path, order_path = split_svg_paths(svg["path"])
        words_svg, order_svg, pair_id = render_svg_split(mnemonic, cols, rows,
                                                         svg["as_paths"])
        write_private_file(words_path, words_svg)
        write_private_file(order_path, order_svg)
        print(f"SVG words written to: {words_path}")
        print(f"SVG order written to: {order_path}")
        print(f"Pair id on both sheets: {pair_id}. Permissions 0600. "
              "You need BOTH sheets to recover the seed; store them apart "
              "and delete the files securely once printed.")
    else:
        write_private_file(svg["path"], render_svg(
            mnemonic, cols, rows, numbered,
            as_paths=svg["as_paths"], shuffle=svg["shuffle"]))
        print(f"SVG written to: {svg['path']} (permissions 0600). "
              "Delete it securely once printed.")
