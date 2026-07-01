"""Multi-account support: two accounts of the SAME provider stay distinct."""

from __future__ import annotations

from unittest.mock import MagicMock

from quota_sentinel.daemon import _poll_all_providers
from quota_sentinel.providers.base import UsageProvider, UsageResult, WindowUsage
from quota_sentinel.store import Store


def _reg(store: Store, iid: str, key: str, account: str | None = None) -> None:
    store.register_instance(
        instance_id=iid,
        project_name="p",
        framework="opencode",
        poll_interval=120,
        providers={"claude": MagicMock(spec=UsageProvider)},
        keys={"claude": key},
        accounts={"claude": account} if account else None,
    )


def _claude(store: Store):
    return [pe for pe in store.unique_providers() if pe.provider_name == "claude"]


def test_two_accounts_same_provider_are_distinct_entries():
    store = Store()
    _reg(store, "i1", "tokenA", "personal")
    _reg(store, "i2", "tokenB", "work")
    entries = _claude(store)
    assert len(entries) == 2
    assert {pe.account for pe in entries} == {"personal", "work"}
    assert {pe.account_label for pe in entries} == {"personal", "work"}
    # distinct fingerprints (different tokens)
    assert len({pe.fingerprint for pe in entries}) == 2


def test_account_label_falls_back_to_fingerprint_when_unset():
    store = Store()
    _reg(store, "i1", "tokenA")  # no friendly label
    pe = _claude(store)[0]
    assert pe.account == ""
    assert pe.account_label == pe.fingerprint
    assert pe.account_label  # non-empty → still a usable discriminator


def test_poll_keeps_each_account_result_separate():
    """Regression: the daemon used to dedup the fetch by provider NAME and copy
    one account's result onto every same-named entry, merging two accounts."""
    store = Store()
    p1 = MagicMock(spec=UsageProvider)
    p1.fetch.return_value = UsageResult(
        provider="claude", windows={"seven_day": WindowUsage(84.0)}
    )
    p2 = MagicMock(spec=UsageProvider)
    p2.fetch.return_value = UsageResult(
        provider="claude", windows={"seven_day": WindowUsage(9.0)}
    )
    store.register_instance(
        instance_id="i1",
        project_name="p",
        framework="oc",
        poll_interval=120,
        providers={"claude": p1},
        keys={"claude": "tokenA"},
        accounts={"claude": "personal"},
    )
    store.register_instance(
        instance_id="i2",
        project_name="p",
        framework="oc",
        poll_interval=120,
        providers={"claude": p2},
        keys={"claude": "tokenB"},
        accounts={"claude": "work"},
    )

    _poll_all_providers(store)

    by_account = {
        pe.account: pe.last_result.windows["seven_day"].utilization
        for pe in _claude(store)
    }
    assert by_account == {"personal": 84.0, "work": 9.0}
    # both providers were actually polled (no name-based dedup)
    p1.fetch.assert_called_once()
    p2.fetch.assert_called_once()


def test_same_key_is_one_entry_and_label_can_be_set_on_reregister():
    store = Store()
    _reg(store, "i1", "tokenA")  # same key, no label
    _reg(store, "i2", "tokenA", "personal")  # same key → same entry, adds label
    entries = _claude(store)
    assert len(entries) == 1
    assert entries[0].account == "personal"
