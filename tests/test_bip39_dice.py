"""
Unit tests for bip39_dice.py.

They use only Python's built-in `unittest` module, so the project stays
"standard library only". Run them from the project root folder:

    python -m unittest discover tests -v

(If you ever install pytest, `python -m pytest` runs these same tests.)

How a unittest test works:
  - Tests live in a class that inherits from unittest.TestCase.
  - Every method whose name starts with `test_` is one test.
  - Inside it you call the code and check the result with self.assertEqual,
    self.assertTrue, self.assertRaises, etc. A failed check = a failed test.
"""

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

# Make the project root importable, so `import bip39_dice` works no matter
# which folder the tests are started from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import bip39_dice  # noqa: E402  (import after the sys.path tweak on purpose)

WORDLIST_PATH = PROJECT_ROOT / "english.txt"


# ---------------------------------------------------------------------------
# Helpers: turn a known word index / entropy into the dice that produce it.
# This lets us feed official test vectors through the real dice pipeline.
# ---------------------------------------------------------------------------

def dice_for_index(index):
    """Return the 5 dice whose base-6 value equals `index` (0..2047).

    Values below 2048 are always accepted and index = value mod 2048 = value.
    Each die shows (digit + 1), because a die face 1..6 means digit 0..5.
    """
    digits = []
    for _ in range(5):
        digits.append(index % 6)
        index //= 6
    return [d + 1 for d in reversed(digits)]


def dice_for_entropy(entropy_hex):
    """Return a dice sequence that encodes 256 bits of entropy exactly.

    First 253 bits -> 23 words of 11 bits; last 3 bits -> 3 parity dice
    (even die = 1, odd die = 0).
    """
    bits = bin(int(entropy_hex, 16))[2:].zfill(256)
    dice = []
    for w in range(23):
        dice += dice_for_index(int(bits[w * 11:(w + 1) * 11], 2))
    dice += [2 if b == "1" else 1 for b in bits[253:]]
    return dice


# Official BIP39 test vectors (24 words, from the reference implementation,
# trezor/python-mnemonic vectors.json). These are PUBLIC: never use them.
OFFICIAL_VECTORS = [
    ("00" * 32, "abandon " * 23 + "art"),
    ("7f" * 32,
     "legal winner thank year wave sausage worth useful legal winner thank year "
     "wave sausage worth useful legal winner thank year wave sausage worth title"),
    ("80" * 32,
     "letter advice cage absurd amount doctor acoustic avoid letter advice cage "
     "absurd amount doctor acoustic avoid letter advice cage absurd amount doctor "
     "acoustic bless"),
    ("ff" * 32, "zoo " * 23 + "vote"),
    ("68a79eaca2324873eacc50cb9c6eca8cc68ea5d936f98787c60c7ebc74e6ce7c",
     "hamster diagram private dutch cause delay private meat slide toddler razor "
     "book happy fancy gospel tennis maple dilemma loan word shrug inflict delay "
     "length"),
]


# english.txt is listed in .gitignore, so a fresh clone may not have it.
# Tests that need it are skipped (not failed) when it is missing.
needs_wordlist = unittest.skipUnless(
    WORDLIST_PATH.exists(), "english.txt not found in the project folder")


class TestParseDice(unittest.TestCase):

    def test_keeps_only_digits_1_to_6(self):
        self.assertEqual(bip39_dice.parse_dice("1 2,3-4\n5\t6"), [1, 2, 3, 4, 5, 6])

    def test_ignores_0_7_8_9_and_letters(self):
        self.assertEqual(bip39_dice.parse_dice("0789abc3"), [3])

    def test_empty_input_gives_empty_list(self):
        self.assertEqual(bip39_dice.parse_dice(""), [])


class TestProcess(unittest.TestCase):

    def test_lowest_group_gives_index_0(self):
        state = bip39_dice.process([1, 1, 1, 1, 1])
        self.assertEqual(state["indices"], [0])

    def test_value_6143_is_accepted(self):
        # 6143 is the largest accepted value: dice 5,5,3,4,6 -> base-6 "44235".
        state = bip39_dice.process([5, 5, 3, 4, 6])
        self.assertEqual(state["indices"], [6143 % 2048])  # 2047
        self.assertEqual(state["rejected"], 0)

    def test_value_6144_is_rejected(self):
        # 6144 is the first rejected value: dice 5,5,3,5,1 -> base-6 "44240".
        # This boundary is what keeps the result free of modulo bias.
        state = bip39_dice.process([5, 5, 3, 5, 1])
        self.assertEqual(state["indices"], [])
        self.assertEqual(state["rejected"], 1)

    def test_highest_group_is_rejected(self):
        state = bip39_dice.process([6, 6, 6, 6, 6])
        self.assertEqual(state["rejected"], 1)

    def test_rejected_group_does_not_shift_following_words(self):
        state = bip39_dice.process([6, 6, 6, 6, 6] + [1, 1, 1, 1, 2])
        self.assertEqual(state["indices"], [1])
        self.assertEqual(state["used"], 10)

    def test_incomplete_input_is_not_complete(self):
        state = bip39_dice.process([1, 2, 3])
        self.assertFalse(state["complete"])
        self.assertEqual(state["leftover"], 3)

    def test_final_dice_use_parity(self):
        dice = dice_for_index(0) * 23 + [2, 1, 4]   # even, odd, even
        state = bip39_dice.process(dice)
        self.assertTrue(state["complete"])
        self.assertEqual(state["final_bits"], "101")

    def test_extra_dice_are_reported_as_leftover(self):
        dice = dice_for_index(0) * 23 + [1, 1, 1] + [6, 6]
        state = bip39_dice.process(dice)
        self.assertEqual(state["leftover"], 2)

    def test_dice_for_index_helper_round_trips(self):
        # Sanity check on our own helper, so the vector tests can trust it.
        for index in (0, 1, 5, 6, 1295, 2047):
            self.assertEqual(bip39_dice.process(dice_for_index(index))["indices"], [index])


class TestMinDiceRemaining(unittest.TestCase):

    def test_nothing_entered_needs_118_dice(self):
        state = bip39_dice.process([])
        self.assertEqual(bip39_dice.min_dice_remaining(state, 0), 23 * 5 + 3)

    def test_complete_input_needs_zero(self):
        dice = dice_for_entropy("00" * 32)
        state = bip39_dice.process(dice)
        self.assertEqual(bip39_dice.min_dice_remaining(state, len(dice)), 0)


@needs_wordlist
class TestOfficialVectors(unittest.TestCase):
    """The most important tests: known entropy must give the known phrase."""

    @classmethod
    def setUpClass(cls):
        cls.words = bip39_dice.load_wordlist(WORDLIST_PATH)

    def test_official_bip39_vectors(self):
        for entropy_hex, expected in OFFICIAL_VECTORS:
            # subTest reports each vector separately if one fails.
            with self.subTest(entropy=entropy_hex):
                state = bip39_dice.process(dice_for_entropy(entropy_hex))
                self.assertTrue(state["complete"])
                mnemonic = bip39_dice.build_mnemonic(state, self.words)
                self.assertEqual(" ".join(mnemonic), expected)

    def test_checksum_of_random_dice_is_valid(self):
        # Independent check: rebuild the 264 bits from the words and verify
        # the last 8 bits equal the first byte of SHA-256(entropy).
        import random
        rng = random.Random(12345)  # fixed seed -> same "rolls" every run
        dice = [rng.randint(1, 6) for _ in range(200)]
        state = bip39_dice.process(dice)
        mnemonic = bip39_dice.build_mnemonic(state, self.words)
        self.assertEqual(len(mnemonic), 24)
        bits = "".join(f"{self.words.index(w):011b}" for w in mnemonic)
        entropy = int(bits[:256], 2).to_bytes(32, "big")
        self.assertEqual(int(bits[256:], 2), hashlib.sha256(entropy).digest()[0])


class TestLoadWordlist(unittest.TestCase):

    @needs_wordlist
    def test_official_list_loads_2048_words(self):
        words = bip39_dice.load_wordlist(WORDLIST_PATH)
        self.assertEqual(len(words), 2048)
        self.assertEqual(words[0], "abandon")
        self.assertEqual(words[-1], "zoo")

    @needs_wordlist
    def test_modified_list_is_refused(self):
        tampered = WORDLIST_PATH.read_bytes().replace(b"zoo", b"zap")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "english.txt"
            path.write_bytes(tampered)
            # The script calls sys.exit(), which raises SystemExit.
            with self.assertRaises(SystemExit) as ctx:
                bip39_dice.load_wordlist(path)
            self.assertIn("hash mismatch", str(ctx.exception.code))

    def test_missing_file_exits_with_message(self):
        with self.assertRaises(SystemExit) as ctx:
            bip39_dice.load_wordlist(PROJECT_ROOT / "does-not-exist.txt")
        self.assertIn("Wordlist not found", str(ctx.exception.code))


class TestRenderGrid(unittest.TestCase):

    def test_words_read_left_to_right_top_to_bottom(self):
        grid = bip39_dice.render_grid(["aa", "bb", "cc", "dd"], cols=2, rows=2)
        lines = grid.splitlines()
        self.assertEqual(len(lines), 5)          # border, row, border, row, border
        self.assertIn("1 aa", lines[1])
        self.assertIn("2 bb", lines[1])
        self.assertIn("3 cc", lines[3])
        self.assertIn("4 dd", lines[3])

    def test_no_numbers(self):
        grid = bip39_dice.render_grid(["aa", "bb"], cols=2, rows=1, numbered=False)
        self.assertEqual(grid.splitlines()[1], "| aa | bb |")

    def test_empty_cells_when_grid_is_larger(self):
        grid = bip39_dice.render_grid(["aa"], cols=2, rows=1, numbered=False)
        self.assertEqual(grid.splitlines()[1], "| aa |    |")


if __name__ == "__main__":
    unittest.main()
