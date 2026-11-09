#!/usr/bin/env python3
"""depviz — инструмент визуализации графа зависимостей менеджера пакетов.

Вариант №13. Этап 3. Основные операции.

Строит граф зависимостей (с учётом транзитивности) алгоритмом DFS
с рекурсией, корректно обрабатывает циклические зависимости.
Поддерживается режим тестирования: вместо URL реального репозитория
пользователь указывает путь к файлу описания графа репозитория,
где пакеты называются большими латинскими буквами.
"""

import argparse
import csv
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

# Все допустимые ключи конфигурации (порядок используется при выводе).
ALLOWED_KEYS = ("package_name", "repository", "test_mode")

CSV_COLUMNS = 2   # колонок в строке конфигурации: ключ,значение
MAVEN_PARTS = 3   # частей в координатах: groupId:artifactId:version
HTTP_TIMEOUT = 15  # секунд на один HTTP-запрос

_PROP_RE = re.compile(r"\$\{([^}]+)\}")
_NAME_RE = re.compile(r"[A-Z]+")


class ConfigError(Exception):
    """Ошибка в конфигурационном файле или в значениях параметров."""


class AppError(Exception):
    """Ошибка при получении или разборе данных о зависимостях."""


# ---------------------------------------------------------------------------
# Конфигурация (этап 1)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Maven: получение прямых зависимостей (этап 2)
# ---------------------------------------------------------------------------

def parse_maven_coordinates(name):
    """Разобрать имя пакета вида groupId:artifactId:version."""
    parts = [p.strip() for p in name.split(":")]
    if len(parts) != MAVEN_PARTS or any(not p for p in parts):
        raise AppError(
            f"имя Maven-пакета должно иметь вид groupId:artifactId:version, "
            f"получено: «{name}»"
        )
    return tuple(parts)


def build_pom_url(repository, group_id, artifact_id, version):
    """Построить URL файла pom.xml по координатам пакета."""
    group_path = group_id.replace(".", "/")
    return (
        f"{repository.rstrip('/')}/{group_path}/{artifact_id}/{version}/"
        f"{artifact_id}-{version}.pom"
    )


def fetch_text(url):
    """Загрузить текстовый ресурс по URL (стандартная библиотека)."""
    try:
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise AppError(f"HTTP-ошибка при загрузке {url}: {exc.code}")
    except urllib.error.URLError as exc:
        raise AppError(f"не удалось подключиться к {url}: {exc.reason}")


def _local_name(tag):
    """Имя XML-тега без пространства имён Maven."""
    return tag.split("}")[-1]


def _child(element, tag):
    """Первый дочерний узел с заданным именем или None."""
    for child in element:
        if _local_name(child.tag) == tag:
            return child
    return None


def _text(element, tag, default=""):
    """Текст дочернего тега; при отсутствии — default."""
    child = _child(element, tag) if element is not None else None
    if child is None or child.text is None:
        return default
    return child.text.strip()


def _collect_properties(root):
    """Собрать словарь свойств pom для подстановки ${...}."""
    parent = _child(root, "parent")
    group = _text(root, "groupId") or _text(parent, "groupId")
    version = _text(root, "version") or _text(parent, "version")
    props = {
        "project.groupId": group,
        "pom.groupId": group,
        "project.version": version,
        "pom.version": version,
        "project.artifactId": _text(root, "artifactId"),
    }
    properties_el = _child(root, "properties")
    if properties_el is not None:
        for prop in properties_el:
            props[_local_name(prop.tag)] = (prop.text or "").strip()
    return props


def parse_pom_dependencies(pom_text):
    """Разобрать pom.xml и вернуть список прямых зависимостей.

    Каждая зависимость — словарь с полями groupId, artifactId,
    version, scope. Поддерживается подстановка простейших ${property}.
    """
    try:
        root = ET.fromstring(pom_text)
    except ET.ParseError as exc:
        raise AppError(f"некорректный XML в POM-файле: {exc}")
    props = _collect_properties(root)

    def resolve(value):
        return _PROP_RE.sub(lambda m: props.get(m.group(1), m.group(0)),
                            value)

    dependencies = []
    dependencies_el = _child(root, "dependencies")
    if dependencies_el is None:
        return dependencies
    for dep in dependencies_el:
        if _local_name(dep.tag) != "dependency":
            continue
        dependencies.append({
            "groupId": resolve(_text(dep, "groupId")),
            "artifactId": resolve(_text(dep, "artifactId")),
            "version": resolve(_text(dep, "version")),
            "scope": resolve(_text(dep, "scope")) or "compile",
        })
    return dependencies


def maven_dependency_name(dep):
    """Координаты зависимости в виде groupId:artifactId:version."""
    return f"{dep['groupId']}:{dep['artifactId']}:{dep['version'] or '*'}"


# ---------------------------------------------------------------------------
# Тестовый репозиторий (этап 3)
# ---------------------------------------------------------------------------

def _check_name(name, path, lineno, what):
    """Проверить, что имя состоит из больших латинских букв."""
    if not _NAME_RE.fullmatch(name):
        raise AppError(
            f"{path}:{lineno}: {what} должно состоять из больших "
            f"латинских букв, получено: «{name}»"
        )


def _parse_repo_line(repo, line, path, lineno):
    """Разобрать строку тестового репозитория и записать в repo."""
    if not line or line.startswith("#"):
        return  # пустые строки и комментарии пропускаем
    if ":" not in line:
        raise AppError(
            f"{path}:{lineno}: ожидался формат «ИМЯ: ЗАВ1 ЗАВ2 ...»"
        )
    name, _, deps_part = line.partition(":")
    name = name.strip()
    _check_name(name, path, lineno, "имя пакета")
    if name in repo:
        raise AppError(f"{path}:{lineno}: пакет «{name}» описан повторно")
    deps = deps_part.split()
    for dep in deps:
        _check_name(dep, path, lineno, "имя зависимости")
    repo[name] = deps


def load_test_repository(path):
    """Загрузить тестовый репозиторий из файла.

    Формат строк: «ИМЯ: ЗАВ1 ЗАВ2 ...», пакеты называются большими
    латинскими буквами; строки с «#» — комментарии.
    """
    repo = {}
    try:
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                _parse_repo_line(repo, line.strip(), path, lineno)
    except OSError as exc:
        raise AppError(f"не удалось прочитать репозиторий {path}: {exc}")
    if not repo:
        raise AppError(f"тестовый репозиторий {path} пуст")
    return repo


# ---------------------------------------------------------------------------
# Построение графа зависимостей: DFS с рекурсией (этап 3)
# ---------------------------------------------------------------------------

def build_graph_dfs(root, get_dependencies):
    """Построить граф зависимостей (с транзитивностью): DFS с рекурсией.

    get_dependencies(node) — функция, возвращающая список имён прямых
    зависимостей узла; при AppError узел считается листом, сообщение
    попадает в warnings. Возвращает (graph, cycles, warnings).
    Циклы: обратное ребро фиксируется, обход по нему не продолжается.
    """
    graph = {}
    cycles = []
    warnings = []
    state = {}  # узел -> "visiting" (в текущем пути) / "done" (обработан)
    path = []   # текущий путь DFS от корня

    def dfs(node):
        state[node] = "visiting"
        path.append(node)
        try:
            deps = get_dependencies(node)
        except AppError as exc:
            deps = []
            warnings.append(str(exc))
        graph[node] = deps
        for dep in deps:
            if state.get(dep) == "visiting":
                # Обратное ребро — циклическая зависимость.
                cycle = path[path.index(dep):] + [dep]
                cycles.append(cycle)
            elif state.get(dep) != "done":
                dfs(dep)
        path.pop()
        state[node] = "done"

    dfs(root)
    return graph, cycles, warnings


def print_graph(graph, cycles):
    """Вывести граф зависимостей и найденные циклы."""
    print("Граф зависимостей (с учётом транзитивности):")
    for node in graph:
        if graph[node]:
            for dep in graph[node]:
                print(f"  {node} -> {dep}")
        else:
            print(f"  {node} (зависимостей нет)")
    print(f"Всего пакетов в графе: {len(graph)}")
    if cycles:
        print("Обнаружены циклические зависимости:")
        for cycle in cycles:
            print("  " + " -> ".join(cycle))
    else:
        print("Циклических зависимостей не обнаружено.")


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

def _test_getter(config):
    """Функция зависимостей для тестового репозитория."""
    repo = load_test_repository(config["repository"])
    name = config["package_name"]
    if not _NAME_RE.fullmatch(name):
        raise AppError(
            f"в тестовом режиме имя пакета должно состоять из больших "
            f"латинских букв, получено: «{name}»"
        )

    def get_dependencies(node):
        if node not in repo:
            raise AppError(
                f"пакет «{node}» отсутствует в тестовом репозитории"
            )
        return repo[node]

    return get_dependencies


def _maven_getter(config):
    """Функция зависимостей для реального Maven-репозитория."""
    repository = config["repository"]
    parse_maven_coordinates(config["package_name"])  # проверка корня

    def get_dependencies(node):
        group_id, artifact_id, version = parse_maven_coordinates(node)
        url = build_pom_url(repository, group_id, artifact_id, version)
        pom_text = fetch_text(url)
        deps = parse_pom_dependencies(pom_text)
        return [maven_dependency_name(dep) for dep in deps]

    return get_dependencies


def _make_dependency_getter(config):
    """Создать функцию получения зависимостей по режиму работы."""
    if config["test_mode"]:
        return _test_getter(config)
    return _maven_getter(config)


def main(argv=None):
    """Точка входа: конфигурация, построение графа, вывод."""
    parser = argparse.ArgumentParser(
        description="depviz: визуализация графа зависимостей (этап 3)"
    )
    parser.add_argument(
        "--config",
        default="config.csv",
        help="путь к конфигурационному файлу CSV (по умолчанию config.csv)",
    )
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        get_dependencies = _make_dependency_getter(config)
        graph, cycles, warnings = build_graph_dfs(
            config["package_name"], get_dependencies
        )
    except (ConfigError, AppError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"Предупреждение: {warning}", file=sys.stderr)
    print_graph(graph, cycles)
    return 0


if __name__ == "__main__":
    sys.exit(main())
