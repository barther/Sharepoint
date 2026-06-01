"""Exclusion-policy sweep (§3 and §16 of the spec).

Distinct from quarantine. Quarantine is technical (empty / corrupt /
password-protected files we cannot read locally). Exclusion is governance
(pastoral care, individual giving, medical, personnel, minors, legal,
denominational confidentiality) — files that we *can* read but must not
expose to any external API.

The operator provides a JSON config listing match patterns and reasons.
Pre-flight applies them during the scan, marks the file as excluded, and
records the decision in `exclusion_log` so it can survive a board review.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# §3 categories. Mirrored from the README so a typo at config-load time
# fails loudly instead of producing an "other"-bucket of un-auditable
# exclusions later.
VALID_REASONS: frozenset[str] = frozenset(
    {
        "pastoral_care",
        "individual_giving",
        "medical",
        "personnel",
        "minor_involving",
        "legal_active",
        "denominational_confidential",
        "other",
    }
)

VALID_MATCH_TYPES: frozenset[str] = frozenset({"path_prefix", "glob"})


@dataclass(frozen=True)
class ExclusionRule:
    match_type: str
    match: str
    reason: str
    detail: str | None = None
    excluded_by: str | None = None
    board_authorization: str | None = None
    disposition: str | None = None

    _compiled_glob: re.Pattern[str] | None = None  # set in __post_init__-style helper

    def matches(self, relative_path: str) -> bool:
        rp = relative_path.replace("\\", "/")
        if self.match_type == "path_prefix":
            prefix = self.match.replace("\\", "/")
            return rp == prefix.rstrip("/") or rp.startswith(prefix.rstrip("/") + "/")
        if self.match_type == "glob":
            return _glob_to_regex(self.match).fullmatch(rp) is not None
        return False


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a path glob to a regex.

    `**` matches across path segments. `*` and `?` match within a single
    segment (no slash). Character classes (`[abc]`) are passed through.
    """
    pat = pattern.replace("\\", "/")
    out: list[str] = []
    i = 0
    while i < len(pat):
        c = pat[i]
        if c == "*":
            if i + 1 < len(pat) and pat[i + 1] == "*":
                out.append(".*")
                i += 2
                if i < len(pat) and pat[i] == "/":
                    i += 1
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = pat.index("]", i)
            out.append(pat[i : j + 1])
            i = j + 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("".join(out))


class ExclusionConfigError(ValueError):
    """Raised on a malformed or invalid exclusion config file."""


def load(path: Path) -> list[ExclusionRule]:
    """Load an exclusion config from disk and validate it.

    Returns an empty list when `path` is None. Raises ExclusionConfigError
    on any structural or semantic problem — we'd rather refuse to run than
    risk silently dropping an exclusion rule because of a typo.
    """
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExclusionConfigError(f"{path}: invalid JSON: {exc}") from exc

    if not isinstance(data, dict) or "exclusions" not in data:
        raise ExclusionConfigError(
            f"{path}: top-level object must contain an 'exclusions' array"
        )
    rules_raw = data["exclusions"]
    if not isinstance(rules_raw, list):
        raise ExclusionConfigError(f"{path}: 'exclusions' must be an array")

    rules: list[ExclusionRule] = []
    for idx, raw in enumerate(rules_raw):
        if not isinstance(raw, dict):
            raise ExclusionConfigError(
                f"{path}: exclusions[{idx}] must be an object"
            )
        match_type = raw.get("match_type")
        match = raw.get("match")
        reason = raw.get("reason")

        if match_type not in VALID_MATCH_TYPES:
            raise ExclusionConfigError(
                f"{path}: exclusions[{idx}].match_type must be one of "
                f"{sorted(VALID_MATCH_TYPES)}, got {match_type!r}"
            )
        if not isinstance(match, str) or not match:
            raise ExclusionConfigError(
                f"{path}: exclusions[{idx}].match must be a non-empty string"
            )
        if reason not in VALID_REASONS:
            raise ExclusionConfigError(
                f"{path}: exclusions[{idx}].reason must be one of "
                f"{sorted(VALID_REASONS)}, got {reason!r}"
            )

        rules.append(
            ExclusionRule(
                match_type=match_type,
                match=match,
                reason=reason,
                detail=raw.get("detail"),
                excluded_by=raw.get("excluded_by"),
                board_authorization=raw.get("board_authorization"),
                disposition=raw.get("disposition"),
            )
        )
    return rules


def match_first(rules: Iterable[ExclusionRule], relative_path: str) -> ExclusionRule | None:
    """Return the first rule that matches the path, or None."""
    for rule in rules:
        if rule.matches(relative_path):
            return rule
    return None
