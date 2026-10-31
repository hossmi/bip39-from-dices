#!/usr/bin/env python3
"""
Generate the SVG image(s) of an existing 12- or 24-word BIP39 seed.
RUN ONLY ON AN OFFLINE (AIR-GAPPED) COMPUTER.

This is the companion of bip39_dice.py: instead of dice rolls it takes the
words of a seed you already have and writes exactly the same SVG layouts
(in order, shuffled or split into two sheets).

Security:
  - The words can NOT be passed on the command line, a file or a pipe (they
    would end up in the shell history, the process list or on disk). The
    script only reads them interactively from the terminal.
  - While you type, each character is shown as an asterisk (*), like a
    password. With --hidden nothing is shown at all (not even the length).
  - The words are never printed back to the terminal.
  - Every word is checked against the official wordlist and the whole phrase
    against the BIP39 checksum before anything is written.

Entering the words:
  - One prompt per word: "Word 3/24: *****". You may also type or paste
    several words (or the whole phrase) on one line, separated by spaces.
  - The first 4 letters of a word are enough (BIP39 guarantees they are
    unique), e.g. "aban" -> "abandon". Words with 3 letters must be complete.
  - Commands: u = undo the last word, q = quit without writing anything.

Output options (same meaning as in bip39_dice.py):
  --svg PATH     SVG file to write (required). Letters are drawn as vector
                 strokes, so the file holds no searchable words.
  --words N      12 or 24 (asked interactively if omitted).
  --cols N       grid columns (default 3).
  --rows N       grid rows (default: just enough for the words).
  --no-numbers   hide the word numbers.
  --svg-text     write plain <text> elements instead (searchable).
  --scribble [N] draw N random translucent red/green brush strokes over the
                 SVG (default: about 6 for 12 words, 10 for 24) to make it a
                 bit harder to read at a glance or with OCR. Words stay readable.
  --shuffle      random cell order, each word followed by its real position.
  --split        PATH-words.svg + PATH-order.svg sharing one random layout.
                 Implies --shuffle. See the WARNING in bip39_dice.py.
  --confirm      ask for the whole phrase twice and require both to match.
  --hidden       show nothing while typing (no asterisks).
  The files are created with owner-only permissions (0600) and are never
  overwritten if they already exist.
  Example: python3 bip39_svg.py --svg seed.svg --words 12 --shuffle

Requires the official BIP39 english.txt wordlist in the same directory
(or pass another path with --wordlist), plus bip39_dice.py and
svg_common.py next to this script.
"""

import argparse
import getpass
import hashlib
import os
import sys

from bip39_dice import load_wordlist
from svg_common import check_svg_destination, write_svg_output

VALID_LENGTHS = (12, 24)
PREFIX_LEN = 4                    # BIP39 english words are unique in 4 letters


# ---------------------------------------------------------------------------
# Masked input: shows "*" per character (or nothing) instead of the text.
# ---------------------------------------------------------------------------

def _read_masked_windows(prompt, mask):
    import msvcrt
    sys.stdout.write(prompt)
    sys.stdout.flush()
    buf = []
    while True:
        ch = msvcrt.getwch()
        if ch in ("\r", "\n"):
            break
        if ch == "\x03":                         # Ctrl+C
            sys.stdout.write("\n")
            raise KeyboardInterrupt
        if ch == "\x1a" and not buf:             # Ctrl+Z on an empty line
            sys.stdout.write("\n")
            raise EOFError
        if ch in ("\x00", "\xe0"):               # arrows, F-keys: 2-char code
            msvcrt.getwch()
            continue
        if ch == "\b":                           # Backspace
            if buf:
                buf.pop()
                if mask:
                    sys.stdout.write("\b \b")
        elif ch == "\x15":                       # Ctrl+U: clear the line
            if mask:
                sys.stdout.write("\b \b" * len(buf))
            buf.clear()
        elif ch.isprintable():
            buf.append(ch)
            sys.stdout.write(mask)
        sys.stdout.flush()
    sys.stdout.write("\n")
    sys.stdout.flush()
    return "".join(buf)


def _read_masked_posix(prompt, mask):
    import termios
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    new = termios.tcgetattr(fd)
    new[3] &= ~(termios.ECHO | termios.ICANON)   # no echo, char-by-char; Ctrl+C still works
    new[6][termios.VMIN] = 1
    new[6][termios.VTIME] = 0
    sys.stdout.write(prompt)
    sys.stdout.flush()
    buf = []
    try:
        termios.tcsetattr(fd, termios.TCSAFLUSH, new)
        while True:
            b = os.read(fd, 1)
            if not b:
                raise EOFError
            ch = b.decode("latin-1")
            if ch in ("\r", "\n"):
                break
            if ch == "\x04":                     # Ctrl+D
                if not buf:
                    sys.stdout.write("\n")
                    raise EOFError
                continue
            if ch == "\x1b":                     # escape sequence (arrows...): skip it
                nxt = os.read(fd, 1)
                if nxt == b"[":
                    while True:
                        c = os.read(fd, 1)
                        if not c or 0x40 <= c[0] <= 0x7E:
                            break
                continue
            if ch in ("\x7f", "\b"):             # Backspace
                if buf:
                    buf.pop()
                    if mask:
                        sys.stdout.write("\b \b")
            elif ch == "\x15":                   # Ctrl+U: clear the line
                if mask:
                    sys.stdout.write("\b \b" * len(buf))
                buf.clear()
            elif ch.isprintable():
                buf.append(ch)
                sys.stdout.write(mask)
            sys.stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSAFLUSH, old)
    sys.stdout.write("\n")
    sys.stdout.flush()
    return "".join(buf)


def read_masked(prompt, mask="*"):
    """Read one line from the terminal without echoing it.
    Each typed character is shown as `mask` ("" shows nothing)."""
    try:
        if os.name == "nt":
            return _read_masked_windows(prompt, mask)
        return _read_masked_posix(prompt, mask)
    except (ImportError, OSError):
        # Unusual console (e.g. some IDEs): fall back to no echo at all.
        return getpass.getpass(prompt)


# ---------------------------------------------------------------------------
# BIP39 validation
# ---------------------------------------------------------------------------

def resolve_word(token, words, index):
    """Return the full wordlist entry for `token`, or None if it is not valid.
    Accepts the complete word or a unique prefix of at least 4 letters."""
    token = token.strip().lower()
    if token in index:
        return token
    if len(token) >= PREFIX_LEN:
        matches = [w for w in words if w.startswith(token)]
        if len(matches) == 1:
            return matches[0]
    return None


def checksum_ok(mnemonic, index):
    """True if the phrase carries a correct BIP39 checksum."""
    n = len(mnemonic)
    if n % 3 or not 12 <= n <= 24:
        return False
    bits = "".join(f"{index[w]:011b}" for w in mnemonic)
    cs_len = n // 3
    ent_bits, cs_bits = bits[:-cs_len], bits[-cs_len:]
    entropy = int(ent_bits, 2).to_bytes(len(ent_bits) // 8, "big")
    expected = f"{hashlib.sha256(entropy).digest()[0]:08b}"[:cs_len]
    return cs_bits == expected


def collect_words(n, words, index, reader):
    """Ask for `n` words with `reader(prompt)` and return them as a list,
    or None if the user quits. Words are never echoed back."""
    width = len(str(n))
    result = []
    while len(result) < n:
        line = reader(f"Word {len(result) + 1:>{width}}/{n}: ")
        tokens = line.split()
        if not tokens:
            continue
        if len(tokens) == 1 and tokens[0].lower() == "q":
            return None
        if len(tokens) == 1 and tokens[0].lower() == "u":
            if result:
                result.pop()
                print(f"  Undid word {len(result) + 1}.")
            else:
                print("  Nothing to undo.")
            continue
        room = n - len(result)
        if len(tokens) > room:
            print(f"  {len(tokens)} words typed but only {room} missing; line ignored.")
            continue
        resolved = [resolve_word(t, words, index) for t in tokens]
        bad = [len(result) + k + 1 for k, w in enumerate(resolved) if w is None]
        if bad:
            label = "Word" if len(bad) == 1 else "Words"
            print(f"  {label} {', '.join(map(str, bad))} not in the BIP39 list "
                  "(or prefix not unique); line ignored, type it again.")
            continue
        result.extend(resolved)
    return result


def ask_mnemonic(n, words, index, reader, confirm):
    """Loop until a checksum-valid phrase is entered (and confirmed)."""
    while True:
        print(f"\nType your {n} words (u = undo last word, q = quit).")
        mnemonic = collect_words(n, words, index, reader)
        if mnemonic is None:
            return None
        if not checksum_ok(mnemonic, index):
            print("  Invalid checksum: at least one word is wrong or out of order. "
                  "Start again.")
            continue
        if confirm:
            print("\nConfirm: type the same words again.")
            again = collect_words(n, words, index, reader)
            if again is None:
                return None
            if again != mnemonic:
                print("  The two entries do not match. Start again.")
                continue
        return mnemonic


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def ask_length():
    while True:
        try:
            ans = input("Number of words (12/24): ").strip()
        except EOFError:
            sys.exit("\nNo input.")
        if ans in ("12", "24"):
            return int(ans)
        print("  Please type 12 or 24.")


def main():
    ap = argparse.ArgumentParser(
        description="Write the SVG of an existing 12/24-word BIP39 seed. "
                    "The words are asked interactively (never on the command line).")
    ap.add_argument("--svg", metavar="PATH", required=True,
                    help="SVG file to write (letters drawn as vector strokes)")
    ap.add_argument("--words", type=int, choices=VALID_LENGTHS,
                    help="number of words in the seed (asked if omitted)")
    ap.add_argument("--cols", type=int, default=3, help="grid columns (default: 3)")
    ap.add_argument("--rows", type=int,
                    help="grid rows (default: enough rows for all the words)")
    ap.add_argument("--no-numbers", action="store_true",
                    help="hide the word numbers in the grid")
    ap.add_argument("--shuffle", action="store_true",
                    help="place the words in random order, each tagged with its "
                         "real position in parentheses")
    ap.add_argument("--split", action="store_true",
                    help="write PATH-words.svg and PATH-order.svg sharing one "
                         "random layout. Implies --shuffle")
    ap.add_argument("--svg-text", action="store_true",
                    help="write the words as plain <text> instead of strokes")
    ap.add_argument("--scribble", metavar="N", type=int, nargs="?", const=None, default=0,
                    help="draw N random translucent brush strokes over the SVG "
                         "(N omitted: automatic, about 6 for 12 words, 10 for 24)")
    ap.add_argument("--confirm", action="store_true",
                    help="ask for the phrase twice and require both to match")
    ap.add_argument("--hidden", action="store_true",
                    help="show nothing while typing (default: one * per character)")
    ap.add_argument("--wordlist",
                    default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "english.txt"),
                    help="path to the official BIP39 wordlist (english.txt)")
    args = ap.parse_args()

    if not sys.stdin.isatty():
        ap.error("the words must be typed in an interactive terminal; "
                 "piping or redirecting them is not allowed")

    if args.split:
        args.shuffle = True
    if args.shuffle and args.no_numbers:
        ap.error("--shuffle/--split need the position numbers; remove --no-numbers")
    if args.scribble is not None and args.scribble < 0:
        ap.error("--scribble N must be 0 or more")
    if args.cols < 1:
        ap.error("--cols must be at least 1")

    n = args.words or ask_length()
    rows = args.rows if args.rows is not None else -(-n // args.cols)
    if rows < 1 or args.cols * rows < n:
        ap.error(f"a {args.cols}x{rows} grid has {args.cols * rows} cells; "
                 f"at least {n} are needed")

    # Check the SVG destination before asking for the words.
    error = check_svg_destination(args.svg, args.split)
    if error:
        ap.error(error)
    svg = {"path": args.svg, "as_paths": not args.svg_text,
           "shuffle": args.shuffle, "split": args.split,
           "scribbles": args.scribble}

    words = load_wordlist(args.wordlist)
    index = {w: i for i, w in enumerate(words)}
    mask = "" if args.hidden else "*"

    try:
        mnemonic = ask_mnemonic(n, words, index,
                                lambda p: read_masked(p, mask), args.confirm)
    except (KeyboardInterrupt, EOFError):
        print("\nAborted. Nothing was written.")
        sys.exit(1)
    if mnemonic is None:
        print("Quitting. Nothing was written.")
        return

    print("\nChecksum OK.")
    try:
        write_svg_output(mnemonic, args.cols, rows, not args.no_numbers, svg)
    except OSError as e:
        sys.exit(f"Could not write SVG ({e}).")
    finally:
        mnemonic.clear()           # best effort; Python cannot wipe memory


if __name__ == "__main__":
    main()
