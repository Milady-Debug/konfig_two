"""Тесты depviz (этап 1): конфигурация из CSV.

Запуск из корня репозитория: python -m unittest discover tests
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import depviz


class TestLoadConfig(unittest.TestCase):
    """Проверки загрузки и валидации конфигурационного файла."""

    def setUp(self):
        fd, self.repo_file = tempfile.mkstemp()
        os.close(fd)

    def tearDown(self):
        os.unlink(self.repo_file)

    def _write_config(self, text):
        fd, path = tempfile.mkstemp(suffix=".csv", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        self.addCleanup(os.unlink, path)
        return path

    def _config(self, **overrides):
        values = {
            "package_name": "A",
            "repository": self.repo_file,
            "test_mode": "true",
        }
        values.update(overrides)
        text = "".join(f"{k},{v}\n" for k, v in values.items())
        return self._write_config(text)

    def test_valid_config(self):
        config = depviz.load_config(self._config())
        self.assertEqual(config["package_name"], "A")
        self.assertTrue(config["test_mode"])

    def test_missing_file(self):
        with self.assertRaises(depviz.ConfigError):
            depviz.load_config("no_such_config.csv")

    def test_unknown_key(self):
        path = self._config(foo="bar")
        with self.assertRaisesRegex(depviz.ConfigError, "неизвестные"):
            depviz.load_config(path)

    def test_missing_key(self):
        fd, path = tempfile.mkstemp(suffix=".csv", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("package_name,A\ntest_mode,true\n")
        self.addCleanup(os.unlink, path)
        with self.assertRaisesRegex(depviz.ConfigError, "отсутствуют"):
            depviz.load_config(path)

    def test_bad_test_mode(self):
        path = self._config(test_mode="yes")
        with self.assertRaisesRegex(depviz.ConfigError, "test_mode"):
            depviz.load_config(path)

    def test_repository_not_url(self):
        path = self._config(repository="not-a-url", test_mode="false")
        with self.assertRaisesRegex(depviz.ConfigError, "URL"):
            depviz.load_config(path)

    def test_test_repo_file_missing(self):
        path = self._config(repository="missing_repo.txt")
        with self.assertRaisesRegex(depviz.ConfigError, "не найден"):
            depviz.load_config(path)

    def test_wrong_columns(self):
        path = self._write_config(
            f"package_name,A,extra\nrepository,{self.repo_file}\n"
            "test_mode,true\n"
        )
        with self.assertRaisesRegex(depviz.ConfigError, "колонки"):
            depviz.load_config(path)


if __name__ == "__main__":
    unittest.main()
