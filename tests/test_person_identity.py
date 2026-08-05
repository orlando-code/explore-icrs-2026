from src.delegates import (
    canonical_person_name,
    delegate_person_key,
    load_person_identity_maps,
    normalize_person_name,
)


def test_talk_and_delegate_middle_initial_share_person_key():
    talk_name = "Ashtyn Isaak"
    delegate_name = "Ashtyn L. Isaak"

    assert delegate_person_key(talk_name) == delegate_person_key(delegate_name)
    assert canonical_person_name(delegate_name) == talk_name
    assert canonical_person_name(talk_name) == talk_name


def test_delegate_only_name_uses_delegate_spelling():
    from src.delegates import load_delegates

    delegates = load_delegates()
    non_speaker = delegates.loc[~delegates["is_speaker"]].iloc[0]
    delegate_name = str(non_speaker["full_name"])
    person_key = delegate_person_key(delegate_name)
    _, key_to_canonical = load_person_identity_maps(use_cache=False)

    assert person_key
    assert key_to_canonical[person_key] == delegate_name


def test_id_review_delegate_id_becomes_person_key():
    talk_name = "Hamzah Abdel Majid"
    delegate_name = "Hamzah Abdel-Majid"

    assert delegate_person_key(talk_name) == delegate_person_key(delegate_name)
    assert delegate_person_key(talk_name).isdigit()
