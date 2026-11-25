"""
Set the quotas of a user and apply them, through sophomorix.
"""

import re
import subprocess

GLOBAL_SHARE = 'linuxmuster-global'
COMMENT_PATTERN = re.compile(r'[\w .!?()/+-]{0,100}')
MAX_QUOTA = 2**31 - 1


class QuotaError(RuntimeError):
    """Raised when sophomorix refused a quota command."""


def _run(args):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace')
    errors = [line.strip() for line in result.stdout.splitlines() if line.strip().startswith('ERROR')]
    if result.returncode != 0 or errors:
        raise QuotaError(errors[0] if errors else f'{args[0]} failed with exit code {result.returncode}')
    return result.stdout


def _check_number(quota):
    if quota is not None and (isinstance(quota, bool) or not isinstance(quota, int) or not -1 <= quota <= MAX_QUOTA):
        raise ValueError(f'{quota!r} is not a valid quota')
    return '---' if quota is None else str(quota)


def _check_comment(comment):
    comment = comment or '---'
    if not COMMENT_PATTERN.fullmatch(comment):
        raise ValueError(f'{comment!r} is not a valid comment')
    return comment


def build_user_quota_args(user, school, quotas=None, mailquota=None):
    """
    :param user: samaccountname
    :param school: School of the user
    :param quotas: List of {'share', 'quota', 'comment'}, quota in MiB, None for the default of the role
    :param mailquota: {'quota', 'comment'} or None to leave it as it is
    :return: argv of sophomorix-user
    :raises ValueError: invalid share, number or comment
    """

    if not quotas and not mailquota:
        raise ValueError('Nothing to set')

    args = ['sophomorix-user', '--user', user]
    if quotas:
        values = []
        for entry in quotas:
            if entry['share'] not in (school, GLOBAL_SHARE):
                raise ValueError(f"{entry['share']} is not a share of the user, allowed are {school} and {GLOBAL_SHARE}")
            values.append(f"{entry['share']}:{_check_number(entry['quota'])}:{_check_comment(entry.get('comment'))}")
        args += ['--quota', ','.join(values)]
    if mailquota:
        args += ['--mailquota', f"{_check_number(mailquota['quota'])}:{_check_comment(mailquota.get('comment'))}"]
    return args


def set_user_quota(user, school, quotas=None, mailquota=None, apply=True):
    """
    Set the individual quotas of a user. See build_user_quota_args().

    :param apply: Also write them to the shares
    :raises QuotaError: refused by sophomorix
    """

    _run(build_user_quota_args(user, school, quotas, mailquota))
    if apply:
        apply_user_quota(user)


def apply_user_quota(user):
    """Write the quotas of one user to the shares, even if sophomorix sees no change."""

    _run(['sophomorix-quota', '--set', '--user', user])


def apply_school_quota(school):
    """
    Write the quotas of all users of a school to the shares, where sophomorix
    sees a change.

    :return: Output of sophomorix-quota
    """

    return _run(['sophomorix-quota', '--school', school])[-5000:]
