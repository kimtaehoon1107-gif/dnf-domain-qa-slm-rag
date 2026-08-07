from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.v3.korean_particles import (
    attach_object,
    attach_subject,
    has_final_consonant,
    object_particle,
    subject_particle,
    validate_particle_tokens,
)


class KoreanParticlesTest(unittest.TestCase):
    def test_final_consonant_selects_particles(self) -> None:
        self.assertTrue(has_final_consonant("방법"))
        self.assertFalse(has_final_consonant("시기"))
        self.assertEqual(object_particle("방법"), "을")
        self.assertEqual(object_particle("시기"), "를")
        self.assertEqual(subject_particle("방법"), "은")
        self.assertEqual(subject_particle("시기"), "는")
        self.assertEqual(attach_object("구성"), "구성을")
        self.assertEqual(attach_subject("혜택"), "혜택은")

    def test_non_hangul_ending_fails_explicitly(self) -> None:
        for value in ("2.0.19", "URL", "가격 100"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                object_particle(value)

    def test_token_validation_rejects_wrong_or_non_hangul_base(self) -> None:
        valid = [
            SimpleNamespace(form="방법", tag="NNG"),
            SimpleNamespace(form="을", tag="JKO"),
        ]
        self.assertEqual(
            validate_particle_tokens(valid),
            [{"base": "방법", "particle": "을", "tag": "JKO"}],
        )
        for base, particle in (("방법", "를"), ("URL", "은")):
            tokens = [
                SimpleNamespace(form=base, tag="NNG"),
                SimpleNamespace(form=particle, tag="JKO" if particle in {"을", "를"} else "JX"),
            ]
            with self.subTest(base=base, particle=particle), self.assertRaises(ValueError):
                validate_particle_tokens(tokens)


if __name__ == "__main__":
    unittest.main()
