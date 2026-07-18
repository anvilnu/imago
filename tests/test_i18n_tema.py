"""Regresiones del catalogo i18n y la fuente unica de estilo."""

import ast
from collections import defaultdict
from pathlib import Path
import re
import unittest

from PySide6.QtGui import QPalette

import i18n
import theme


ROOT = Path(__file__).resolve().parents[1]


def _string_entries():
    """Extrae las entradas literales de _STRINGS sin perder claves repetidas."""
    tree = ast.parse((ROOT / "i18n.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "_STRINGS"
                   for target in node.targets):
            continue
        if not isinstance(node.value, ast.Dict):
            break
        return [(key.value, key.lineno) for key in node.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)]
    raise AssertionError("No se encontro el diccionario literal _STRINGS")


class I18nCatalogTests(unittest.TestCase):
    def test_no_hay_claves_duplicadas_en_el_literal(self):
        lines = defaultdict(list)
        for key, line in _string_entries():
            lines[key].append(line)
        duplicates = {key: positions for key, positions in lines.items()
                      if len(positions) > 1}

        self.assertEqual(duplicates, {}, "Claves i18n duplicadas: %r" % duplicates)

    def test_todas_las_entradas_tienen_es_en_y_fr(self):
        incomplete = {
            key: sorted({"es", "en", "fr"} - set(values))
            for key, values in i18n._STRINGS.items()
            if {"es", "en", "fr"} - set(values)
        }
        self.assertEqual(incomplete, {})


class ThemeSourceTests(unittest.TestCase):
    def tearDown(self):
        theme.use_theme("dark")

    def test_alternar_claro_y_oscuro_restaura_todos_los_tokens(self):
        theme.use_theme("dark")
        dark = {name: getattr(theme, name) for name in theme._THEME_TOKENS}
        theme.use_theme("light")
        self.assertNotEqual(theme.BG_WINDOW, dark["BG_WINDOW"])
        self.assertEqual(theme.MODE, "light")

        theme.use_theme("dark")
        self.assertEqual(
            {name: getattr(theme, name) for name in theme._THEME_TOKENS}, dark)
        self.assertEqual(theme.MODE, "dark")

    def test_qpalette_y_qss_consumen_el_tema_activo(self):
        for mode in ("dark", "light"):
            with self.subTest(mode=mode):
                theme.use_theme(mode)
                palette = theme.application_palette()
                self.assertEqual(palette.color(QPalette.Window).name(),
                                 theme.BG_WINDOW)
                self.assertEqual(palette.color(QPalette.Highlight).name(),
                                 theme.PALETTE_HIGHLIGHT)
                self.assertIn(theme.BG_BUTTON, theme.document_tabs_qss())
                self.assertIn("CANVAS_FRAME", theme._DARK)
                self.assertIn("CANVAS_FRAME", theme._LIGHT)

    def test_main_y_miniaturas_no_incrustan_colores_qss(self):
        color_in_qss = re.compile(
            r"(?i)(?:background(?:-color)?|color|border(?:-color)?)\s*:\s*"
            r"(?:#[0-9a-f]{3,8}|rgba?\(|(?:white|black|red|green|blue)\b)")
        for relative in ("main.py", "widgets/tab_thumbnails.py"):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIsNone(color_in_qss.search(source), relative)


if __name__ == "__main__":
    unittest.main()
