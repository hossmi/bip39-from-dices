#!/usr/bin/env python3
"""
Generate a 24-word BIP39 seed from six-sided dice rolls.
RUN ONLY ON AN OFFLINE (AIR-GAPPED) COMPUTER.

Method (unbiased):
  - Words 1-23: groups of 5 dice -> base-6 number (0..7775).
    If the value is < 6144 it is accepted: index = value mod 2048.
    Otherwise the whole group is discarded (rejection sampling).
  - Word 24: 3 dice by parity (even = 1, odd = 0) -> 3 bits of entropy,
    plus 8 checksum bits (first byte of SHA-256 over the 256 entropy bits).

Input:
  - Interactive: enter rolls in batches of any size (e.g. 10 dice at a time).
    Spaces, commas and any character other than 1-6 are ignored.
    Commands: 'u' = undo last batch, 's' = status, 'q' = quit without generating.
  - All at once:  python3 bip39_dice.py --rolls "3612545..."
  - From a file:  python3 bip39_dice.py --file rolls.txt
  - Via a pipe:   cat rolls.txt | python3 bip39_dice.py

Output layout:
  The seed is printed as an ASCII grid read left-to-right, top-to-bottom.
  --cols N       number of columns (default 3)
  --rows N       number of rows (default: just enough for 24 words)
  --no-numbers   hide the word numbers
  --svg PATH     also write the grid as an SVG image (standard library only).
                 Letters are drawn as vector strokes from a built-in font, so
                 the file holds no searchable words (defeats grep, desktop
                 indexers and malware scanning files for BIP39 phrases; it does
                 NOT defeat OCR or anyone looking at the image).
  --svg-text     write plain <text> elements instead (searchable).
  --shuffle      place the SVG words in random grid cells, each followed by its
                 real position in parentheses, e.g. "zoo (17)". The terminal
                 grid stays in order. Cannot be combined with --no-numbers.
  --split        write two SVGs that share one random layout instead of one:
                 PATH-words.svg (shuffled words, no positions) and
                 PATH-order.svg (only the positions, in the same cells).
                 Both carry the same random pair id. Implies --shuffle.
                 WARNING: this is a 2-of-2 split; losing either sheet makes
                 the seed practically unrecoverable. The words sheet alone
                 leaves 24!/256 (~2^71) orderings to brute-force: hard, but
                 far below the seed's 256 bits. For real secret sharing use
                 SLIP-39 or a BIP39 passphrase instead.
                 The file is created with owner-only permissions (0600) and is
                 never overwritten if it already exists.
  Example: python3 bip39_dice.py --cols 4 --rows 6 --svg seed.svg

Requires the official BIP39 english.txt wordlist in the same directory
(or pass another path with --wordlist).
"""

import argparse
import hashlib
import os
import secrets
import sys
from xml.sax.saxutils import escape

OFFICIAL_WORDLIST_SHA256 = "2f5eed53a4727b4bf8880d8f3f199efc90e58503646d9ff8eff3a2ed3b24dbda"
WEIGHTS = (1296, 216, 36, 6, 1)  # 6^4 .. 6^0
DICE_PER_WORD = 5
ACCEPT_LIMIT = 6144              # 3 * 2048, largest multiple of 2048 <= 6^5
DICE_WORDS = 23                  # full words generated from dice
FINAL_DICE = 3                   # entropy bits in word 24


def load_wordlist(path):
    try:
        with open(path, "rb") as f:
            data = f.read()
    except FileNotFoundError:
        sys.exit(f"Wordlist not found: {path}")
    if hashlib.sha256(data).hexdigest() != OFFICIAL_WORDLIST_SHA256:
        sys.exit("Wordlist does NOT match the official BIP39 list (hash mismatch). Aborting.")
    words = data.decode().split()
    assert len(words) == 2048
    return words


def parse_dice(text):
    return [int(c) for c in text if c in "123456"]


def process(dice):
    """Walk the full roll sequence and return the resulting state.
    Deterministic: the same sequence always yields the same result."""
    indices, rejected, pos = [], 0, 0
    while len(indices) < DICE_WORDS and pos + DICE_PER_WORD <= len(dice):
        group = dice[pos:pos + DICE_PER_WORD]
        pos += DICE_PER_WORD
        value = sum((d - 1) * w for d, w in zip(group, WEIGHTS))
        if value < ACCEPT_LIMIT:
            indices.append(value % 2048)
        else:
            rejected += 1
    final_bits = None
    if len(indices) == DICE_WORDS and pos + FINAL_DICE <= len(dice):
        final_bits = "".join("1" if d % 2 == 0 else "0"
                             for d in dice[pos:pos + FINAL_DICE])
        pos += FINAL_DICE
    return {
        "indices": indices,
        "final_bits": final_bits,
        "rejected": rejected,
        "used": pos,
        "leftover": len(dice) - pos,
        "complete": final_bits is not None,
    }


def min_dice_remaining(state, total):
    missing_words = DICE_WORDS - len(state["indices"])
    pending = total - state["used"]  # dice entered but not yet consumed
    if missing_words > 0:
        return max(0, missing_words * DICE_PER_WORD + FINAL_DICE - pending)
    return max(0, FINAL_DICE - pending)


def build_mnemonic(state, words):
    bits = "".join(f"{i:011b}" for i in state["indices"]) + state["final_bits"]
    entropy = int(bits, 2).to_bytes(32, "big")
    checksum = hashlib.sha256(entropy).digest()[0]
    last = (int(state["final_bits"], 2) << 8) | checksum
    return [words[i] for i in state["indices"]] + [words[last]]


def print_status(state, total):
    print(f"  Dice entered: {total} | words: {len(state['indices'])}/{DICE_WORDS}"
          f" | rejected groups: {state['rejected']}"
          f" | minimum remaining: {min_dice_remaining(state, total)} dice")


def render_grid(mnemonic, cols, rows, numbered=True):
    """Render the words as an ASCII grid, read left-to-right, top-to-bottom."""
    n = len(mnemonic)
    num_w = len(str(n))
    word_w = max(len(w) for w in mnemonic)
    cell_w = (num_w + 1 if numbered else 0) + word_w
    sep = "+" + "+".join("-" * (cell_w + 2) for _ in range(cols)) + "+"

    lines = [sep]
    for r in range(rows):
        cells = []
        for c in range(cols):
            i = r * cols + c
            if i < n:
                text = f"{i + 1:>{num_w}} {mnemonic[i]}" if numbered else mnemonic[i]
            else:
                text = ""
            cells.append(f" {text:<{cell_w}} ")
        lines.append("|" + "|".join(cells) + "|")
        lines.append(sep)
    return "\n".join(lines)


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


def print_mnemonic(mnemonic, state, cols, rows, numbered):
    title = f" BIP39 SEED ({len(mnemonic)} words) "
    grid = render_grid(mnemonic, cols, rows, numbered)
    width = len(grid.splitlines()[0])
    print("\n" + title.center(width, "="))
    print(grid)
    print(f"Rejected groups: {state['rejected']}")
    if state["leftover"]:
        print(f"Unused leftover dice: {state['leftover']} (normal; ignored)")
    print("Write the words down, verify them in your wallet and close this window.")


def emit_result(mnemonic, state, layout, svg):
    """svg: None or dict(path, as_paths, shuffle, split)."""
    print_mnemonic(mnemonic, state, *layout)
    if not svg:
        return
    cols, rows, numbered = layout
    try:
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
    except OSError as e:
        print(f"Could not write SVG ({e}). The seed above is still valid.")


def interactive_mode(words, layout, svg):
    batches = []

    def flat():
        return [d for b in batches for d in b]

    print("Enter your rolls in batches (e.g. 10 dice: 3 6 1 2 5 4 4 2 6 1).")
    print("Commands: u = undo last batch, s = status, q = quit.\n")
    while True:
        dice = flat()
        state = process(dice)
        if state["complete"]:
            emit_result(build_mnemonic(state, words), state, layout, svg)
            return
        try:
            line = input(f"Batch {len(batches) + 1} > ").strip().lower()
        except EOFError:
            print("\nInput ended before enough dice were entered.")
            return
        if line == "q":
            print("Quitting without generating a seed.")
            return
        if line == "u":
            if batches:
                removed = batches.pop()
                print(f"  Undid batch: {''.join(map(str, removed))}")
            else:
                print("  Nothing to undo.")
            print_status(process(flat()), len(flat()))
            continue
        if line == "s":
            print_status(state, len(dice))
            continue
        batch = parse_dice(line)
        if not batch:
            print("  No 1-6 digits found on that line.")
            continue
        invalid = [c for c in line if c.isdigit() and c not in "123456"]
        if invalid:
            print(f"  Warning: ignored invalid digits: {' '.join(invalid)}")
        batches.append(batch)
        print(f"  Read ({len(batch)} dice): {' '.join(map(str, batch))}")
        print_status(process(flat()), len(flat()))


def main():
    ap = argparse.ArgumentParser(description="24-word BIP39 seed from d6 dice rolls.")
    ap.add_argument("--rolls", help="all rolls at once (digits 1-6)")
    ap.add_argument("--file", help="text file containing the rolls")
    ap.add_argument("--cols", type=int, default=3,
                    help="grid columns (default: 3)")
    ap.add_argument("--rows", type=int,
                    help="grid rows (default: enough rows for 24 words)")
    ap.add_argument("--no-numbers", action="store_true",
                    help="hide the word numbers in the grid")
    ap.add_argument("--svg", metavar="PATH",
                    help="also write the grid as an SVG image to PATH "
                         "(letters drawn as vector strokes, no searchable text)")
    ap.add_argument("--shuffle", action="store_true",
                    help="place the SVG words in random order, each tagged with "
                         "its real position in parentheses (requires --svg)")
    ap.add_argument("--split", action="store_true",
                    help="write two SVGs sharing one random layout: PATH-words.svg "
                         "(shuffled words, no positions) and PATH-order.svg "
                         "(positions only). Implies --shuffle; requires --svg")
    ap.add_argument("--svg-text", action="store_true",
                    help="write the SVG words as plain <text> instead of strokes")
    ap.add_argument("--wordlist",
                    default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "english.txt"),
                    help="path to the official BIP39 wordlist (english.txt)")
    args = ap.parse_args()

    total_words = DICE_WORDS + 1
    if args.cols < 1:
        ap.error("--cols must be at least 1")
    rows = args.rows if args.rows is not None else -(-total_words // args.cols)
    if rows < 1 or args.cols * rows < total_words:
        ap.error(f"a {args.cols}x{rows} grid has {args.cols * rows} cells; "
                 f"at least {total_words} are needed")
    layout = (args.cols, rows, not args.no_numbers)

    if args.split:
        args.shuffle = True
    if args.shuffle and not args.svg:
        ap.error("--shuffle/--split only apply to the SVG output; add --svg PATH")
    if args.shuffle and args.no_numbers:
        ap.error("--shuffle/--split need the position numbers; remove --no-numbers")

    # Check the SVG destination up front so no dice rolls are wasted.
    svg = None
    if args.svg:
        targets = split_svg_paths(args.svg) if args.split else (args.svg,)
        for t in targets:
            if os.path.exists(t):
                ap.error(f"{t} already exists; refusing to overwrite it")
        parent = os.path.dirname(os.path.abspath(args.svg))
        if not os.path.isdir(parent) or not os.access(parent, os.W_OK):
            ap.error(f"cannot write to directory {parent}")
        svg = {"path": args.svg, "as_paths": not args.svg_text,
               "shuffle": args.shuffle, "split": args.split}

    words = load_wordlist(args.wordlist)

    text = None
    if args.rolls:
        text = args.rolls
    elif args.file:
        with open(args.file) as f:
            text = f.read()
    elif not sys.stdin.isatty():
        text = sys.stdin.read()

    if text is None:
        interactive_mode(words, layout, svg)
        return

    dice = parse_dice(text)
    state = process(dice)
    if not state["complete"]:
        print_status(state, len(dice))
        sys.exit("Not enough dice. Add more rolls or use interactive mode.")
    emit_result(build_mnemonic(state, words), state, layout, svg)


if __name__ == "__main__":
    main()
