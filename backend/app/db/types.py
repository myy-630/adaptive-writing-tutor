from enum import Enum


def enum_values(enum_class: type[Enum]) -> list[str]:
    return [item.value for item in enum_class]
