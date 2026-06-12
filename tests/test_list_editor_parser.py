import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_URL = (ROOT / "dashboard" / "modules" / "list-editor.js").as_uri()


class ListEditorParserTests(unittest.TestCase):
    def _parse(self, value: str) -> list[str]:
        script = f"""
          import {{ splitListEditor }} from {json.dumps(MODULE_URL)};
          const input = {json.dumps(value)};
          process.stdout.write(JSON.stringify(splitListEditor(input)));
        """
        result = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def test_comma_rich_lines_remain_whole_entries(self):
        value = (
            "Product/web operations involving CMS, e-commerce, QA\n"
            "Marketing communications roles when content, brand, web, product, or event focused\n"
            "Creative automation involving design, visuals, prototypes, or operations"
        )

        self.assertEqual(self._parse(value), value.splitlines())

    def test_semicolons_and_slashes_are_preserved(self):
        self.assertEqual(
            self._parse("UX/UI; AI-assisted prototyping"),
            ["UX/UI; AI-assisted prototyping"],
        )

    def test_bullets_blank_lines_windows_endings_and_duplicates_are_normalized(self):
        self.assertEqual(
            self._parse(
                "- Junior UX/UI Designer\r\n"
                "\r\n"
                "* Product Designer\r\n"
                "\u2022 Digital Designer\r\n"
                "1. Creative Technologist\r\n"
                "junior ux/ui designer\r\n"
            ),
            [
                "Junior UX/UI Designer",
                "Product Designer",
                "Digital Designer",
                "Creative Technologist",
            ],
        )


if __name__ == "__main__":
    unittest.main()
