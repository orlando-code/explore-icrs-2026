from src.sources.programme import classify_presentation_type, load_talks


def test_classify_presentation_type_maps_session_kinds() -> None:
    assert classify_presentation_type("poster") == "poster"
    assert classify_presentation_type("session") == "oral"
    assert classify_presentation_type("plenary") == "keynote"
    assert classify_presentation_type("special") == "oral"
    assert classify_presentation_type("") == ""


def test_load_talks_includes_presentation_type() -> None:
    talks = load_talks()
    assert "presentation_type" in talks.columns
    assert set(talks["presentation_type"].dropna().unique()) <= {
        "poster",
        "oral",
        "keynote",
    }
    assert talks["presentation_type"].notna().all()
