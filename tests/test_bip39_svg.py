"""
Unit tests for bip39_svg.py (standard library `unittest` only).

Run them from the project root folder:

    python -m unittest discover tests -v

The masked terminal input is not exercised here: `collect_words` takes the
reader function as a parameter, so the tests feed it a list of lines instead.
"""

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import bip39_dice  # noqa: E402
import bip39_svg   # noqa: E402
import svg_common  # noqa: E402

WORDS = bip39_dice.load_wordlist(str(PROJECT_ROOT / "english.txt"))
INDEX = {w: i for i, w in enumerate(WORDS)}

# Official BIP39 test vectors (Trezor python-mnemonic vectors.json).
V12_ZERO = ["abandon"] * 11 + ["about"]
V12_7F = "legal winner thank year wave sausage worth useful legal winner thank yellow".split()
V24_ZERO = ["abandon"] * 23 + ["art"]
V24_FF = ["zoo"] * 23 + ["vote"]


def fake_reader(lines):
    """Return a reader that hands out `lines` one by one, like the terminal."""
    it = iter(lines)
    return lambda prompt: next(it)


def collect(n, lines):
    with redirect_stdout(io.StringIO()) as out:
        result = bip39_svg.collect_words(n, WORDS, INDEX, fake_reader(lines))
    return result, out.getvalue()


class TestChecksum(unittest.TestCase):
    def test_official_vectors_are_valid(self):
        for phrase in (V12_ZERO, V12_7F, V24_ZERO, V24_FF):
            self.assertTrue(bip39_svg.checksum_ok(phrase, INDEX), phrase)

    def test_wrong_last_word_is_rejected(self):
        self.assertFalse(bip39_svg.checksum_ok(["abandon"] * 12, INDEX))
        self.assertFalse(bip39_svg.checksum_ok(["abandon"] * 24, INDEX))

    def test_swapped_words_are_rejected(self):
        swapped = V12_7F[:]
        swapped[0], swapped[1] = swapped[1], swapped[0]
        self.assertFalse(bip39_svg.checksum_ok(swapped, INDEX))

    def test_bad_length_is_rejected(self):
        self.assertFalse(bip39_svg.checksum_ok(V12_ZERO[:11], INDEX))


class TestResolveWord(unittest.TestCase):
    def test_full_word(self):
        self.assertEqual(bip39_svg.resolve_word("abandon", WORDS, INDEX), "abandon")

    def test_case_and_spaces(self):
        self.assertEqual(bip39_svg.resolve_word("  ABANDON ", WORDS, INDEX), "abandon")

    def test_four_letter_prefix(self):
        self.assertEqual(bip39_svg.resolve_word("aban", WORDS, INDEX), "abandon")
        self.assertEqual(bip39_svg.resolve_word("yell", WORDS, INDEX), "yellow")

    def test_short_or_unknown(self):
        self.assertIsNone(bip39_svg.resolve_word("aba", WORDS, INDEX))
        self.assertIsNone(bip39_svg.resolve_word("xyzzy", WORDS, INDEX))

    def test_three_letter_words_must_be_complete(self):
        self.assertEqual(bip39_svg.resolve_word("zoo", WORDS, INDEX), "zoo")


class TestCollectWords(unittest.TestCase):
    def test_one_word_per_line(self):
        result, _ = collect(12, V12_ZERO)
        self.assertEqual(result, V12_ZERO)

    def test_whole_phrase_on_one_line(self):
        result, _ = collect(24, [" ".join(V24_ZERO)])
        self.assertEqual(result, V24_ZERO)

    def test_prefixes_and_mixed_lines(self):
        lines = ["lega winn", "than year wave", "saus wort usef lega winn than yell"]
        result, _ = collect(12, lines)
        self.assertEqual(result, V12_7F)

    def test_invalid_line_is_ignored_and_never_echoed(self):
        lines = ["abandon secretword"] + V12_ZERO
        result, out = collect(12, lines)
        self.assertEqual(result, V12_ZERO)
        self.assertIn("Word 2", out)
        self.assertNotIn("secretword", out)
        self.assertNotIn("abandon", out)

    def test_undo(self):
        lines = ["abandon", "zoo", "u"] + V12_ZERO[1:]
        result, _ = collect(12, lines)
        self.assertEqual(result, V12_ZERO)

    def test_too_many_words_on_one_line(self):
        lines = [" ".join(V12_ZERO + ["abandon"])] + V12_ZERO
        result, _ = collect(12, lines)
        self.assertEqual(result, V12_ZERO)

    def test_empty_lines_are_skipped(self):
        result, _ = collect(12, ["", "   "] + V12_ZERO)
        self.assertEqual(result, V12_ZERO)

    def test_quit(self):
        result, _ = collect(12, ["abandon", "q"])
        self.assertIsNone(result)


class TestAskMnemonic(unittest.TestCase):
    def ask(self, n, lines, confirm=False):
        with redirect_stdout(io.StringIO()):
            return bip39_svg.ask_mnemonic(n, WORDS, INDEX, fake_reader(lines), confirm)

    def test_bad_checksum_starts_again(self):
        lines = [" ".join(["abandon"] * 12), " ".join(V12_7F)]
        self.assertEqual(self.ask(12, lines), V12_7F)

    def test_confirm_match(self):
        phrase = " ".join(V24_FF)
        self.assertEqual(self.ask(24, [phrase, phrase], confirm=True), V24_FF)

    def test_confirm_mismatch_starts_again(self):
        a, b = " ".join(V12_ZERO), " ".join(V12_7F)
        self.assertEqual(self.ask(12, [a, b, b, b], confirm=True), V12_7F)


class TestSvgOutput(unittest.TestCase):
    def test_twelve_word_svg_has_no_searchable_words(self):
        svg = svg_common.render_svg(V12_7F, cols=3, rows=4)
        self.assertTrue(svg.startswith("<svg"))
        for w in set(V12_7F):
            self.assertNotIn(w, svg)


if __name__ == "__main__":
    unittest.main()
