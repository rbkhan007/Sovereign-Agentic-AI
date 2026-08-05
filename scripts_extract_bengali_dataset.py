"""Extract Bengali character repertoire from Noto Sans Bengali TTF and build
a LoRA text-training dataset (saved to lora_datasets/).

Fonts cannot be fed to an LLM trainer directly, but their cmap tables tell us
exactly which Unicode characters the family supports. We use that to generate a
curriculum of Bengali characters and syllables suitable for fine-tuning a text
model that otherwise has no Bengali awareness.

Usage: python scripts_extract_bengali_dataset.py
"""

import json
import os
import sys
import unicodedata
from fontTools.ttLib import TTFont

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(
    BASE_DIR,
    "Training Folder",
    "Noto_Sans_Bengali",
    "NotoSansBengali-VariableFont_wdth,wght.ttf",
)
OUT_DIR = os.path.join(BASE_DIR, "lora_datasets")
ALPHABET_TXT = os.path.join(OUT_DIR, "bengali_alphabet.txt")
WORDS_TXT = os.path.join(OUT_DIR, "bengali_words.txt")
META_JSON = os.path.join(OUT_DIR, "bengali_extract_meta.json")

BENGALI_RANGE = range(0x0980, 0x0A00)  # U+0980–U+09FF
DIGITS = "০১২৩৪৫৬৭৮৯"
VOWEL_SIGNS = "ািীুূৃেৈোৌ"


def load_cmap(path):
    font = TTFont(path, lazy=True)
    cmap = font.getBestCmap()
    font.close()
    return set(cmap.keys())


def main():
    if not os.path.exists(FONT):
        print(f"Font not found: {FONT}")
        sys.exit(1)

    supported = load_cmap(FONT)
    bengali = sorted(cp for cp in BENGALI_RANGE if cp in supported)
    print(f"Font supports {len(supported):,} total codepoints; "
          f"{len(bengali)} in the Bengali block (U+0980–U+09FF).")

    consonants = []
    independent_vowels = []
    matras = []
    digits_in_font = []
    other = []
    for cp in bengali:
        ch = chr(cp)
        name = unicodedata.name(ch, "?")
        if ch in DIGITS:
            digits_in_font.append(ch)
        elif name.startswith("BENGALI LETTER"):
            if ch in "অআইঈউঊঋএঐওঔ":
                independent_vowels.append(ch)
            else:
                consonants.append(ch)
        elif name.startswith("BENGALI VOWEL SIGN"):
            matras.append(ch)
        elif name.startswith("BENGALI DIGIT"):
            digits_in_font.append(ch)
        else:
            other.append((ch, name))

    print(f"  Consonants: {len(consonants)}")
    print(f"  Independent vowels: {len(independent_vowels)}")
    print(f"  Vowel signs (matras): {len(matras)}")
    print(f"  Digits: {len(digits_in_font)}")
    print(f"  Other (signs/symbols/punct): {len(other)}")

    if not consonants:
        print("ERROR: No Bengali consonants found in cmap; aborting.")
        sys.exit(1)

    os.makedirs(OUT_DIR, exist_ok=True)

    alphabet_lines = []
    for cp in bengali:
        alphabet_lines.append(chr(cp))
    for d in digits_in_font:
        alphabet_lines.append(d)
    for c in consonants:
        for m in matras:
            alphabet_lines.append(c + m)
    alphabet_lines.append("")
    alphabet_lines = list(dict.fromkeys(alphabet_lines))

    with open(ALPHABET_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(alphabet_lines))

    words = []
    two_letter = [c + m + " " + c + m for c in consonants for m in matras]
    words.extend(two_letter)
    if len(consonants) >= 2:
        for c in consonants:
            for c2 in consonants:
                words.append(c + c2)
                for m in matras:
                    words.append(c + c2 + m)
    words = list(dict.fromkeys(words))[:800]
    with open(WORDS_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(words))

    meta = {
        "font": os.path.basename(FONT),
        "supported_codepoints": len(supported),
        "bengali_block_codepoints": len(bengali),
        "consonants": len(consonants),
        "independent_vowels": len(independent_vowels),
        "vowel_signs": len(matras),
        "digits": len(digits_in_font),
        "other": len(other),
        "alphabet_dataset_lines": len(alphabet_lines),
        "words_dataset_lines": len(words),
        "alphabet_file": os.path.basename(ALPHABET_TXT),
        "words_file": os.path.basename(WORDS_TXT),
        "notes": (
            "Character-level Bengali curriculum extracted from the font cmap. "
            "Consonants are paired with every vowel sign (matra) to teach "
            "syllable formation. Fonts cannot produce real sentences; for "
            "meaningful LoRA tuning pair this with a text corpus."
        ),
    }
    with open(META_JSON, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"\nWrote {ALPHABET_TXT} ({len(alphabet_lines)} lines)")
    print(f"Wrote {WORDS_TXT} ({len(words)} lines)")
    print(f"Wrote {META_JSON}")


if __name__ == "__main__":
    main()
