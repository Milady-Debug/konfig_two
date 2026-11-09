#!/usr/bin/env python3
"""depviz — инструмент визуализации графа зависимостей менеджера пакетов.

Вариант №13. Этап 1. Минимальный прототип с конфигурацией.

Источник настраиваемых параметров — конфигурационный файл формата CSV
(строки вида «ключ,значение»). Настраиваемые параметры:
  - package_name — имя анализируемого пакета;
  - repository   — URL репозитория или путь к файлу тестового репозитория;
  - test_mode    — режим работы с тестовым репозиторием (true/false).

При запуске все параметры выводятся в формате ключ-значение.
Для всех параметров реализована обработка ошибок.
"""

import argparse
import csv
import os
import sys
from urllib.parse import urlparse

# Все допустимые ключи конфигурации (порядок используется при выводе).
ALLOWED_KEYS = ("package_name", "repository", "test_mode")

CSV_COLUMNS = 2  # колонок в строке конфигурации: ключ,значение


class ConfigError(Exception):
    """Ошибка в конфигурационном файле или в значениях параметров."""


def _parse_row(params, row, path, lineno):
    """Разобрать одну строку CSV и записать параметр в params."""
    if not row or all(not cell.strip() for cell in row):
        return  # пустые строки пропускаем
    if len(row) != CSV_COLUMNS:
        raise ConfigError(
            f"{path}:{lineno}: ожидалось {CSV_COLUMNS} колонки "
            f"(ключ,значение), получено {len(row)}"
        )
    key, value = row[0].strip(), row[1].strip()
    if not key:
        raise ConfigError(f"{path}:{lineno}: пустой ключ")
    if key in params:
        raise ConfigError(f"{path}:{lineno}: параметр «{key}» задан повторно")
    params[key] = value


def _read_params(path):
    """Прочитать пары ключ-значение из CSV-файла конфигурации."""
    params = {}
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for lineno, row in enumerate(csv.reader(f), start=1):
                _parse_row(params, row, path, lineno)
    except UnicodeDecodeError:
        raise ConfigError(f"файл {path} не является текстовым CSV в UTF-8")
    except OSError as exc:
        raise ConfigError(f"не удалось прочитать {path}: {exc}")
    return params


def _validate_keys(params):
    """Проверить, что нет ни лишних, ни недостающих параметров."""
    unknown = sorted(set(params) - set(ALLOWED_KEYS))
    if unknown:
        raise ConfigError(f"неизвестные параметры: {', '.join(unknown)}")
    missing = [key for key in ALLOWED_KEYS if key not in params]
    if missing:
        raise ConfigError(f"отсутствуют параметры: {', '.join(missing)}")


def _parse_test_mode(raw):
    """Преобразовать значение test_mode в bool с проверкой."""
    lowered = raw.lower()
    if lowered not in ("true", "false"):
        raise ConfigError(
            f"test_mode должен быть true или false, получено: «{raw}»"
        )
    return lowered == "true"


def _validate_repository(repository, test_mode):
    """Проверить repository с учётом режима работы."""
    if test_mode:
        if not os.path.isfile(repository):
            raise ConfigError(
                f"файл тестового репозитория не найден: {repository}"
            )
        return
    parsed = urlparse(repository)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ConfigError(
            f"repository должен быть URL http(s)://..., "
            f"получено: «{repository}»"
        )


def load_config(path):
    """Загрузить и полностью проверить параметры конфигурации."""
    if not path:
        raise ConfigError("не указан путь к конфигурационному файлу")
    if not os.path.isfile(path):
        raise ConfigError(f"конфигурационный файл не найден: {path}")
    params = _read_params(path)
    _validate_keys(params)
    if not params["package_name"]:
        raise ConfigError("параметр package_name не должен быть пустым")
    if not params["repository"]:
        raise ConfigError("параметр repository не должен быть пустым")
    test_mode = _parse_test_mode(params["test_mode"])
    _validate_repository(params["repository"], test_mode)
    return {
        "package_name": params["package_name"],
        "repository": params["repository"],
        "test_mode": test_mode,
    }


def main(argv=None):
    """Точка входа: разбор аргументов, загрузка конфигурации, вывод."""
    parser = argparse.ArgumentParser(
        description="depviz: визуализация графа зависимостей (этап 1)"
    )
    parser.add_argument(
        "--config",
        default="config.csv",
        help="путь к конфигурационному файлу CSV (по умолчанию config.csv)",
    )
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        return 1
    # Требование этапа 1: вывести все параметры в формате ключ-значение.
    print("Параметры конфигурации:")
    for key in ALLOWED_KEYS:
        print(f"{key}={config[key]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
