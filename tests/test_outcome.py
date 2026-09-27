from datetime import datetime, timedelta, timezone

from vinted_tracker.models import Status
from vinted_tracker.outcome import Outcome, compute_outcome

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
A, R, S, H, D, U = Status.AVAILABLE, Status.RESERVED, Status.SOLD, Status.HIDDEN, Status.DELETED, Status.UNKNOWN
STOP = timedelta(days=30)
GAP = timedelta(hours=48)


def obs(*pairs):
    return [(T0 + timedelta(hours=h), s) for h, s in pairs]


def outcome(observations, now_hours):
    return compute_outcome(T0, observations, T0 + timedelta(hours=now_hours), stop_age=STOP, uncertain_gap=GAP)


def test_sold_between_last_available_and_first_sold():
    result = outcome(obs((0.1, A), (2, A), (4, S), (6, S)), 6)
    assert result == Outcome("sold", timedelta(hours=2), timedelta(hours=4), False)


def test_reserved_counts_as_live():
    assert outcome(obs((0.1, A), (2, R), (4, S)), 4).sold_after_min == timedelta(hours=2)


def test_unknown_observations_are_ignored():
    assert outcome(obs((0.1, A), (2, U), (4, S)), 4).sold_after_min == timedelta(hours=0.1)


def test_long_gap_is_uncertain():
    result = outcome(obs((0.1, A), (60, S)), 60)
    assert result.final_status == "sold"
    assert result.uncertain is True


def test_deleted_is_final_and_uncertain():
    assert outcome(obs((0.1, A), (5, D)), 5) == Outcome("deleted", None, None, True)


def test_still_tracking():
    assert outcome(obs((0.1, A), (2, A)), 3) == Outcome(None, None, None, False)


def test_hidden_is_not_final_before_stop():
    assert outcome(obs((0.1, A), (2, H)), 3).final_status is None


def test_unsold_after_stop():
    assert outcome(obs((0.1, A), (700, A)), 720).final_status == "unsold_30d"


def test_hidden_at_stop():
    assert outcome(obs((0.1, A), (700, H)), 720).final_status == "hidden"
