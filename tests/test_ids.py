from datetime import date

from newsroom.ids import build_briefing_id, build_item_id, normalize_slot


def test_phase1_slot_aliases_map_to_fixed_briefing_hours():
    day = date(2026, 5, 19)

    assert normalize_slot("08:00 早间版") == "morning"
    assert normalize_slot("13") == "noon"
    assert normalize_slot("evening") == "evening"
    assert build_briefing_id(day, "08:00 早间版") == "2026-05-19-08"
    assert build_briefing_id(day, "13:00 午间版") == "2026-05-19-13"
    assert build_briefing_id(day, "20:00 晚间版") == "2026-05-19-20"


def test_item_ids_are_zero_padded_and_1_indexed():
    assert build_item_id("2026-05-19-13", 1) == "2026-05-19-13-001"
    assert build_item_id("2026-05-19-13", 12) == "2026-05-19-13-012"
