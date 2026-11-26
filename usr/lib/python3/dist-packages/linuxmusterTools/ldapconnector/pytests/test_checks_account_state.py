import pytest

from linuxmusterTools.ldapconnector.checks import account_state, get_account_state, password_marker


@pytest.fixture
def entries(monkeypatch):
    entries = []

    class Connector:
        def _get(self, ldap_filter):
            return entries

    monkeypatch.setattr(account_state, 'LdapConnector', Connector)
    return entries


def test_state_and_marker_of_an_account(entries):
    # Two changes within the same second have different markers
    markers = set()
    for filetime in (b'134084160000000001', b'134084160000000002'):
        entries[:] = [('CN=jdoe', {'userAccountControl': [b'514'], 'pwdLastSet': [filetime], 'objectGUID': [b'\x01\x02']})]
        state = get_account_state('CN=jdoe')
        assert state['disabled'] and state['pwd_last_set'].year == 2025 and state['guid'] == '0102'
        markers.add(password_marker(state))
    assert len(markers) == 2


def test_no_account(entries):
    assert get_account_state('CN=nobody') is None
    assert password_marker(None) is None
