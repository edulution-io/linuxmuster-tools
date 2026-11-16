"""
School-qualified LINBO group ids.

On a multi-school server every school other than default-school gets the id
``<school>__<group>`` for its hardware groups, so two schools can use the same
group name without sharing one start.conf. default-school keeps the plain
group. The id is what names ``start.conf.<id>`` and ``<id>.cfg``.

The rule is the one of linuxmuster-base7 (``getLinboGroupId()``,
``splitLinboGroupId()`` and ``LINBO_GROUP_SEPARATOR`` in
``linuxmuster_base7.functions``), which generates the files, and of linbo7's
``linbo_sync`` (``${HOSTGROUP#*__}``). Keep the three in step. A school name
cannot contain ``_`` (it is part of every device hostname), so the first
separator always ends the school.
"""

DEFAULT_SCHOOL = 'default-school'
LINBO_GROUP_SEPARATOR = '__'


def get_linbo_group_id(school, group):
    """
    :param school: School name, e.g. 'default-school' or 'abc'
    :param group: Group as in devices.csv, e.g. 'raum101'
    :return: 'raum101' for default-school, 'abc__raum101' otherwise
    """

    if not school or school == DEFAULT_SCHOOL:
        return group
    return f'{school}{LINBO_GROUP_SEPARATOR}{group}'


def split_linbo_group_id(group_id):
    """
    :param group_id: LINBO group id, e.g. 'raum101' or 'abc__raum101'
    :return: (school, group), ('default-school', group_id) without separator
    """

    school, separator, group = group_id.partition(LINBO_GROUP_SEPARATOR)
    if not separator:
        return DEFAULT_SCHOOL, group_id
    return school, group
