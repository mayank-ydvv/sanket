import pytest

from app.decision.rules import PrankTracker, SafetyRules, detect_hazards, silent_sos_signal
from app.models import Decision


def low(**overrides: object) -> Decision:
    base: dict[str, object] = {
        "is_emergency": False,
        "emergency_prob": 0.2,
        "department": "none",
        "department_conf": 0.6,
        "severity": 1,
        "alert_now": False,
    }
    return Decision.model_validate(base | overrides)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def rules() -> SafetyRules:
    return SafetyRules(PrankTracker(window_s=600, min_reports=3, clock=FakeClock()))


@pytest.mark.parametrize(
    "text",
    [
        "my son is not breathing properly",  # en
        "papa behosh ho gaye, saans nahi le rahe",  # hinglish
        "बच्चा पानी में फंस गया है",  # hi
        "அப்பாவுக்கு மூச்சு விட முடியவில்லை",  # ta
        "বাবা অজ্ঞান হয়ে পড়ে আছে",  # bn
    ],
)
def test_severity_floor_in_all_languages(rules: SafetyRules, text: str) -> None:
    outcome = rules.apply(text, "sms", None, low())
    assert outcome.decision.severity >= 3
    assert "severity_floor" in outcome.fired
    assert outcome.decision.needs_human_review  # model said non-emergency: a human must look


@pytest.mark.parametrize(
    "text",
    [
        "can't talk, he is outside the door",  # en
        "bol nahi sakti.. woh yahin hai",  # hinglish
        "बोल नहीं सकती, वो यहीं है",  # hi
        "பேச முடியாது, அவன் இங்கே இருக்கிறான்",  # ta
        "কথা বলতে পারছি না, ও এখানে আছে",  # bn
        "1111 1111 1111",
        "... --- ...",
        "asdfgh jkl qwrt zxcv",
    ],
)
def test_silent_sos_in_all_languages(rules: SafetyRules, text: str) -> None:
    outcome = rules.apply(text, "sms", None, low())
    d = outcome.decision
    assert d.silent_sos and d.is_emergency and d.department == "police"
    assert d.needs_human_review and d.severity >= 4
    assert any(f.startswith("silent_sos") for f in outcome.fired)


def test_empty_call_is_silent_sos() -> None:
    assert silent_sos_signal("   ", "call") == "empty_call"


@pytest.mark.parametrize("text", ["Marina beach pe aag lagi hai", "please send help fast", "तीर्थ यात्रा"])
def test_normal_text_is_not_silent_sos(text: str) -> None:
    assert silent_sos_signal(text, "sms") is None


def test_rules_never_lower_severity_or_clear_review(rules: SafetyRules) -> None:
    high = low(is_emergency=True, emergency_prob=0.95, department="fire", severity=5, needs_human_review=True)
    outcome = rules.apply("routine text", "sms", None, high)
    assert outcome.decision.severity == 5 and outcome.decision.needs_human_review


def test_hazards_are_tagged() -> None:
    assert detect_hazards("smell of gas near the lift and smoke on the 5th floor") == ["smoke", "gas"]
    assert "flood_water" in detect_hazards("बाढ़ का पानी घरों में")


def test_prank_score_rises_for_contradicting_repeat_caller() -> None:
    clock = FakeClock()
    tracker = PrankTracker(window_s=600, min_reports=3, clock=clock)
    scores = [tracker.observe("caller", d) for d in ("fire", "police", "medical", "fire", "police")]
    assert scores[:3] == [0.0, 0.0, 0.0]
    assert 0.5 < scores[3] <= scores[4] <= 1.0
    clock.now += 601
    assert tracker.observe("caller", "fire") == 0.0  # window expired


def test_same_department_repeats_are_not_pranks() -> None:
    tracker = PrankTracker(window_s=600, min_reports=3, clock=FakeClock())
    assert max(tracker.observe("worried", "fire") for _ in range(8)) == 0.0


def test_laughter_flags_prank_but_never_dismisses(rules: SafetyRules) -> None:
    outcome = rules.apply("aliens at Pondy Bazaar lol", "sms", None, low())
    assert outcome.decision.prank_score >= 0.5
    assert "prank_suspected" in outcome.fired
