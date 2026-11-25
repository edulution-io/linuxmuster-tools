from datetime import datetime, timezone

import ldap
import ldap.filter

from ..connector import LdapConnector


ACCOUNTDISABLE = 0x0002
# Seconds between 1601-01-01 (FILETIME) and 1970-01-01
EPOCH_OFFSET = 11644473600


def get_account_state(dn):
    """
    Read what decides whether a session of an account is still valid.

    :param dn: distinguishedName of the account
    :type dn: basestring
    :return: {'disabled': bool, 'pwd_last_set': datetime in UTC or None, 'pwd_marker': basestring},
        None if there is no such account
    :rtype: dict
    """

    ldap_filter = f"(&(objectClass=user)(distinguishedName={ldap.filter.escape_filter_chars(dn)}))"
    results = [entry for entry in LdapConnector()._get(ldap_filter) if entry and entry[0]]
    if not results:
        return None

    attributes = results[0][1]
    control = int(attributes.get('userAccountControl', [b'0'])[0])
    filetime = int(attributes.get('pwdLastSet', [b'0'])[0])
    changed = None
    if filetime > 0:
        changed = datetime.fromtimestamp(filetime / 10**7 - EPOCH_OFFSET, tz=timezone.utc)

    return {'disabled': bool(control & ACCOUNTDISABLE), 'pwd_last_set': changed, 'pwd_marker': str(filetime)}


def password_marker(state):
    """
    Value which changes with every password change, at the full precision of
    the directory.

    :param state: Result of get_account_state()
    :type state: dict
    :return: Marker, None without an account
    :rtype: basestring
    """

    return state['pwd_marker'] if state else None
