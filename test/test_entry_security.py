from app.entry.security import build_security_flags


def test_security_flags_redacts_phone_number() -> None:
    flags = build_security_flags("我的手机号是13812345678")

    assert flags.has_pii is True
    assert flags.redacted_text is not None
    assert "13812345678" not in flags.redacted_text
    assert "138****5678" in flags.redacted_text
    assert flags.text_hash
    assert "pii_redacted" in flags.reasons


def test_security_flags_uses_hash_without_plain_redacted_text_when_no_pii() -> None:
    flags = build_security_flags("普通问题")

    assert flags.has_pii is False
    assert flags.redacted_text is None
    assert flags.text_hash