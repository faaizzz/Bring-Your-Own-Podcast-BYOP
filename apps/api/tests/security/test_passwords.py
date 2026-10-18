from byop.security.passwords import hash_password, verify_password


def test_hash_verifies_only_the_right_password() -> None:
    hashed = hash_password("s3cret")

    assert hashed != "s3cret"
    assert verify_password("s3cret", hashed)
    assert not verify_password("wrong", hashed)


def test_hashes_are_salted() -> None:
    assert hash_password("same") != hash_password("same")


def test_malformed_hash_is_a_failed_check_not_an_error() -> None:
    assert not verify_password("anything", "not-a-bcrypt-hash")
