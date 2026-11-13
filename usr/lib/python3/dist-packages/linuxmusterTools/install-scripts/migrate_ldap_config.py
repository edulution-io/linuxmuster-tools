#!/usr/bin/python3
"""
Move the LDAP settings out of the webui's config file.

Until linuxmuster-tools7 7.4.20 the LDAP search base was read from
/etc/linuxmuster/webui/config.yml - a file owned by linuxmuster-webui7. On a
server without the webui there was nothing to create it, so tools7, cli7 and
api7 lost their LDAP access with it. The settings are linuxmusterTools' own,
so they now live in /etc/linuxmuster/tools/ldap.yml.

Reads the old file and writes the new one to stdout. Prints nothing and exits
1 if the old file holds no ldap section, so that the caller can tell "nothing
to migrate" from "migrated".

Deliberately uses the system interpreter and only PyYAML, not the linuxmuster
venv: it runs from debian/postinst, where the venv may be mid-rebuild.
"""

import sys

import yaml

OLD = '/etc/linuxmuster/webui/config.yml'
KEYS = ('binddn', 'bindpw', 'host', 'searchdn')


def main():
    try:
        with open(OLD, 'r') as handle:
            old = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as error:
        print(f'{OLD}: {error}', file=sys.stderr)
        return 1

    ldap = (old.get('linuxmuster') or {}).get('ldap') or {}
    migrated = {key: ldap[key] for key in KEYS if ldap.get(key)}

    if 'searchdn' not in migrated:
        print(f'{OLD} holds no ldap searchdn, nothing to migrate.', file=sys.stderr)
        return 1

    print(f'# Migrated from {OLD} by linuxmuster-tools7.')
    print('# linuxmuster-base7 rewrites this file on every linuxmuster-setup run.')
    # safe_dump quotes whatever needs quoting - a bind password may contain
    # anything, and an all-digit one would otherwise be read back as an int.
    print(yaml.safe_dump(migrated, default_flow_style=False, sort_keys=False), end='')
    return 0


if __name__ == '__main__':
    sys.exit(main())
