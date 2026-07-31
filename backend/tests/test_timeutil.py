import pytest

from app.timeutil import TimeParseError, format_hhmm, format_time, parse_time


@pytest.mark.parametrize(
    "text,expected",
    [
        ("00:00", 0),
        ("00:00:00", 0),
        ("8:15", 8 * 3600 + 15 * 60),
        ("08:15:30", 8 * 3600 + 15 * 60 + 30),
        ("23:59:59", 86_399),
        # The whole reason times are stored as seconds from the service-day
        # start: a trip at 01:10 on Tuesday's service is 25:10, not 01:10.
        ("25:10:00", 25 * 3600 + 10 * 60),
        ("47:59:59", 47 * 3600 + 59 * 60 + 59),
    ],
)
def test_parse_accepts_service_day_times(text, expected):
    assert parse_time(text) == expected


@pytest.mark.parametrize("bad", ["", "abc", "8", "08:60", "08:15:61", "-1:00", None, "49:00"])
def test_parse_rejects_nonsense(bad):
    with pytest.raises(TimeParseError):
        parse_time(bad)


def test_format_round_trip():
    for text in ("00:00:00", "06:30:00", "25:10:00"):
        assert format_time(parse_time(text)) == text


def test_format_hhmm_wraps_past_midnight():
    # Printed timetables show the wall clock, not the service-day hour.
    assert format_hhmm(parse_time("25:10:00")) == "01:10"
    assert format_hhmm(parse_time("13:05:00")) == "13:05"


def test_format_time_handles_none():
    assert format_time(None) is None
