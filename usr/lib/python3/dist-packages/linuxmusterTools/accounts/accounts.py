"""
Create and delete administrators and bind users.

sophomorix creates the account. The password is set afterwards and never given
on its command line, where every local user could read it.
"""

import re
import logging
import secrets
import string
import subprocess

from ..ldapconnector.ldap_writer import LdapWriter
from ..ldapconnector.models import LMNUserModel
from ..ldapconnector.urls import router as lr
from ..passwords import PasswordPolicyProvider


logger = logging.getLogger(__name__)

# sAMAccountName limit of AD, same start rule as sophomorix
NAME_PATTERN = re.compile(r'[a-z0-9][a-z0-9._-]{1,19}')

ACCOUNT_TYPES = {
    'globaladministrator': {'option': 'global-admin', 'route': 'globaladministrators', 'school': False},
    'schooladministrator': {'option': 'school-admin', 'route': 'schooladministrators', 'school': True},
    'globalbinduser': {'option': 'global-binduser', 'route': 'globalbindusers', 'school': False},
    'schoolbinduser': {'option': 'school-binduser', 'route': 'schoolbindusers', 'school': True},
}

# Accounts linuxmuster itself needs.
PROTECTED_ACCOUNTS = ('administrator', 'global-admin', 'global-binduser', 'pgmadmin', 'dns-admin')


class AccountError(RuntimeError):
    """Raised when an account could not be created or deleted."""


class AccountExistsError(AccountError):
    """Raised when the name is already used in the directory."""


class AccountNotFoundError(AccountError):
    """Raised when there is no account of this type with this name."""


class _Account:
    """What LdapWriter needs to modify an existing account."""

    model = LMNUserModel

    def __init__(self, data):
        self.data = data


def _run(args):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace')
    # Never log or raise the whole output, it contains the first password.
    errors = [line.strip() for line in result.stdout.splitlines() if line.strip().startswith('ERROR')]
    if result.returncode != 0 or errors:
        message = errors[0] if errors else f'{args[0]} failed with exit code {result.returncode}'
        if 'exists already' in message:
            raise AccountExistsError(message)
        raise AccountError(message)


def _set_password(name, data, password):
    from ..samba_util import samba_tool

    samba_tool.load_samba_bindings()
    samdb = samba_tool.SamDB(
        url=samba_tool.SAMDB_PATH, session_info=samba_tool.system_session(),
        credentials=samba_tool.creds, lp=samba_tool.lp,
    )
    samdb.setpassword(f'samaccountname={name}', password)
    LdapWriter()._setattr(_Account(data), data={'sophomorixFirstPassword': password})


def _generate_password(role, school, name):
    policy = PasswordPolicyProvider().get_policy(role, school=school)
    characters = string.ascii_letters + string.digits + '!@#$%&*+-?'
    for _ in range(100):
        password = ''.join(secrets.choice(characters) for _ in range(20))
        if policy.validate(password, username=name).ok:
            return password
    raise AccountError('Could not generate a password satisfying the policy')


def get_account(account_type, name):
    """
    :return: Details of the account, {} if there is none of this type
    """

    return lr.get(f"/{ACCOUNT_TYPES[account_type]['route']}/{name}")


def check_new_account(account_type, name, school=None):
    """
    :raises ValueError: invalid name, or school missing or not expected
    """

    if not NAME_PATTERN.fullmatch(name):
        raise ValueError(f'{name!r} is not a valid name')
    if bool(school) != ACCOUNT_TYPES[account_type]['school']:
        raise ValueError(
            'A school is required for this account' if ACCOUNT_TYPES[account_type]['school']
            else 'This account has no school'
        )


def check_deletable(account_type, name):
    """
    :raises ValueError: the account is needed by linuxmuster
    :raises AccountNotFoundError: no such account of this type
    """

    if not NAME_PATTERN.fullmatch(name.lower()) or name.lower() in PROTECTED_ACCOUNTS:
        raise ValueError(f'{name} can not be deleted')
    if not get_account(account_type, name):
        raise AccountNotFoundError(f'{name} not found')


def create_account(account_type, name, school=None, password=None):
    """
    :param account_type: One of ACCOUNT_TYPES
    :param name: samaccountname of the new account
    :param school: Required for a school account only
    :param password: Generated if not given
    :return: The password of the account
    :raises ValueError: invalid name, or school missing or not expected
    :raises AccountExistsError: the name is already used
    :raises AccountError: refused by sophomorix or by the password rules of Samba
    """

    check_new_account(account_type, name, school)
    details = ACCOUNT_TYPES[account_type]

    if password is None:
        password = _generate_password(account_type, school or 'global', name)

    args = ['sophomorix-admin', f"--create-{details['option']}", name, '--random-passwd-show']
    if school:
        args += ['--school', school]
    _run(args)

    try:
        data = get_account(account_type, name)
        if not data:
            raise AccountError(f'{name} was not found after its creation')
        _set_password(name, data, password)
    except Exception as error:
        # Do not leave an account behind whose password nobody knows.
        try:
            _run(['sophomorix-admin', '--kill', name])
        except AccountError as kill_error:
            logger.error(f'Could not remove the incomplete account {name}: {kill_error}')
        raise AccountError(f'Could not set the password of {name}: {error}') from error

    return password


def delete_account(account_type, name):
    """
    :raises ValueError: the account is needed by linuxmuster
    :raises AccountNotFoundError: no such account of this type
    :raises AccountError: refused by sophomorix
    """

    check_deletable(account_type, name)
    _run(['sophomorix-admin', '--kill', name])
