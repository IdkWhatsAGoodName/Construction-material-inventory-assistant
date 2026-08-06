from inventory_assistant.application.matching import all_tokens_match, normalize_text


def test_normalization_uses_only_the_approved_aliases_and_fillers() -> None:
    assert normalize_text("The 3/8 INCH sheets_for our beams") == "3 8 in sheet beam"
    assert normalize_text("6 METRES of Rebars") == "6 m rebar"


def test_every_meaningful_query_token_is_required() -> None:
    fields = ("25M reinforcing bar", "rebar", "400W", "each")

    assert all_tokens_match("25M rebars", fields)
    assert not all_tokens_match("25M epoxy rebars", fields)
