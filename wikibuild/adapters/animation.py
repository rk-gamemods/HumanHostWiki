"""Shared selection for Animancer timing, without clip or callback payloads."""

from .schema import NUMBER as N, NumberWithSentinel, fields

# The captured Animancer implementation treats NaN as a default-time/speed marker.
ANIMATION_NUMBER = NumberWithSentinel(frozenset({"nan"}))
ANIMATION_TRANSITION = fields({
    "_FadeDuration": N, "_Speed": ANIMATION_NUMBER, "_NormalizedStartTime": ANIMATION_NUMBER,
    "_Events": fields({"_NormalizedTimes": [ANIMATION_NUMBER]}, "_Callbacks _Names"),
}, "_Clip")
