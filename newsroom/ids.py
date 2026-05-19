from __future__ import annotations

from datetime import date

SLOT_SPECS = {
    'morning': {
        'hour': '08',
        'label': '08:00 早间版',
        'aliases': {'morning', '08', '08:00', '08:00 早间版', '早间版'},
    },
    'noon': {
        'hour': '13',
        'label': '13:00 午间版',
        'aliases': {'noon', '13', '13:00', '13:00 午间版', '午间版'},
    },
    'evening': {
        'hour': '20',
        'label': '20:00 晚间版',
        'aliases': {'evening', '20', '20:00', '20:00 晚间版', '晚间版'},
    },
}

_ALIAS_TO_SLOT = {}
for slot_name, spec in SLOT_SPECS.items():
    for alias in spec['aliases']:
        _ALIAS_TO_SLOT[alias.casefold()] = slot_name


def normalize_slot(value: str) -> str:
    candidate = (value or '').strip()
    if not candidate:
        raise ValueError('slot 不能为空')

    normalized = _ALIAS_TO_SLOT.get(candidate.casefold())
    if normalized:
        return normalized

    compact = candidate.replace('：', ':').replace(' ', '')
    if compact.startswith('08'):
        return 'morning'
    if compact.startswith('13'):
        return 'noon'
    if compact.startswith('20'):
        return 'evening'

    raise ValueError(f'未知 slot: {value}')


def slot_hour(value: str) -> str:
    return SLOT_SPECS[normalize_slot(value)]['hour']


def slot_label(value: str) -> str:
    return SLOT_SPECS[normalize_slot(value)]['label']


def build_briefing_id(day: date, slot: str) -> str:
    return f"{day.isoformat()}-{slot_hour(slot)}"


def build_item_id(briefing_id: str, index: int) -> str:
    if index < 1:
        raise ValueError('item index 必须从 1 开始')
    return f'{briefing_id}-{index:03d}'
