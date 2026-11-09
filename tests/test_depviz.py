"""Тесты depviz (этап 2): конфигурация и разбор Maven pom.xml.

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

    def test_bad_test_mode(self):
        path = self._config(test_mode="yes")
        with self.assertRaisesRegex(depviz.ConfigError, "test_mode"):
            depviz.load_config(path)

    def test_repository_not_url(self):
        path = self._config(repository="not-a-url", test_mode="false")
        with self.assertRaisesRegex(depviz.ConfigError, "URL"):
            depviz.load_config(path)


class TestMaven(unittest.TestCase):
    """Проверки разбора координат, URL и pom.xml."""

    def test_coordinates(self):
        result = depviz.parse_maven_coordinates("org.x:lib:1.0")
        self.assertEqual(result, ("org.x", "lib", "1.0"))

    def test_bad_coordinates(self):
        with self.assertRaises(depviz.AppError):
            depviz.parse_maven_coordinates("only-two:parts")

    def test_pom_url(self):
        url = depviz.build_pom_url("https://repo", "org.apache", "lib", "2.0")
        self.assertEqual(
            url, "https://repo/org/apache/lib/2.0/lib-2.0.pom"
        )

    def test_parse_pom_with_property(self):
        pom = (
            "<project><groupId>g</groupId><artifactId>a</artifactId>"
            "<version>1.0</version><dependencies><dependency>"
            "<groupId>dep</groupId><artifactId>d</artifactId>"
            "<version>${project.version}</version>"
            "</dependency></dependencies></project>"
        )
        deps = depviz.parse_pom_dependencies(pom)
        self.assertEqual(len(deps), 1)
        self.assertEqual(deps[0]["version"], "1.0")
        self.assertEqual(deps[0]["scope"], "compile")

    def test_parse_pom_parent_inheritance(self):
        pom = (
            "<project><parent><groupId>parent.g</groupId>"
            "<version>2.0</version></parent>"
            "<artifactId>a</artifactId><dependencies><dependency>"
            "<groupId>d</groupId><artifactId>x</artifactId>"
            "<version>${project.version}</version>"
            "</dependency></dependencies></project>"
        )
        deps = depviz.parse_pom_dependencies(pom)
        self.assertEqual(deps[0]["version"], "2.0")

    def test_parse_pom_invalid_xml(self):
        with self.assertRaises(depviz.AppError):
            depviz.parse_pom_dependencies("not xml at all")


if __name__ == "__main__":
    unittest.main()
