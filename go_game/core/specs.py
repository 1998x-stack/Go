"""Immutable compatibility contract for the existing Python Go rules engine."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RuleSpec:
    """PSK + no suicide + simplified Chinese area scoring.

    The existing engine does *not* adjudicate dead stones. Japanese scoring
    and situational superko require separate future rulesets.
    """
    rule_id: str = "research-psk-v1"
    board_size: int = 9
    komi_half_points: int = 11
    handicap: int = 0

    def __post_init__(self):
        if self.rule_id not in ("legacy-psk-v1", "research-psk-v1"):
            raise ValueError("Unsupported ruleset; do not silently change ko semantics")
        if type(self.board_size) is not int or not 2 <= self.board_size <= 26:
            raise ValueError("board_size must be an integer from 2 to 26")
        if type(self.komi_half_points) is not int:
            raise ValueError("komi_half_points must be an integer")
        if type(self.handicap) is not int or not 0 <= self.handicap <= 9:
            raise ValueError("handicap must be an integer between 0 and 9")
        if self.handicap and (self.board_size != 19 or self.komi_half_points != 0):
            raise ValueError("Legacy handicap requires a 19x19 board and zero komi")

    def to_dict(self):
        return dict(asdict(self), schema="rules-v1", ko_rule="positional_superko",
                    suicide="forbidden", scoring="area_simple",
                    end_protocol="two_pass_no_adjudication")

    @classmethod
    def from_dict(cls, value):
        required = {"rule_id", "board_size", "komi_half_points", "handicap"}
        if not isinstance(value, dict) or value.get("schema") != "rules-v1":
            raise ValueError("Unknown rule specification schema")
        if any(value.get(k) != v for k, v in (
            ("ko_rule", "positional_superko"), ("suicide", "forbidden"),
            ("scoring", "area_simple"), ("end_protocol", "two_pass_no_adjudication")
        )):
            raise ValueError("Unsupported rule configuration")
        if not required.issubset(value):
            raise ValueError("Missing rule configuration fields")
        return cls(**{key: value[key] for key in required})
