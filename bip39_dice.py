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
  --scribble [N] draw N random translucent red/green brush strokes over the
                 SVG (default: about 6 for 12 words, 10 for 24) to make it a
                 bit harder to read at a glance or with OCR. Words stay readable.
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
(or pass another path with --wordlist) and svg_common.py next to the script.
"""

import argparse
import hashlib
import os
import sys

from svg_common import check_svg_destination, write_svg_output

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
    if state["complete"]:
        return 0
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
    try:
        write_svg_output(mnemonic, *layout, svg)
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
    ap.add_argument("--scribble", metavar="N", type=int, nargs="?", const=None, default=0,
                    help="draw N random translucent brush strokes over the SVG "
                         "(N omitted: automatic, about 6 for 12 words, 10 for 24)")
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
    if args.scribble is not None and args.scribble < 0:
        ap.error("--scribble N must be 0 or more")
    if args.scribble != 0 and not args.svg:
        ap.error("--scribble only applies to the SVG output; add --svg PATH")

    # Check the SVG destination up front so no dice rolls are wasted.
    svg = None
    if args.svg:
        error = check_svg_destination(args.svg, args.split)
        if error:
            ap.error(error)
        svg = {"path": args.svg, "as_paths": not args.svg_text,
               "shuffle": args.shuffle, "split": args.split,
               "scribbles": args.scribble}

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
