import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import audit  # noqa: E402


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class AuditFixture(unittest.TestCase):
    """Every size below is hand counted: chars // 4."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        c = self.config = Path(self.tmp.name) / "cfg"
        plugin = Path(self.tmp.name) / "plugin"
        write(c / "CLAUDE.md", "x" * 40 + "\n@extra.md\n")       # 51 chars -> 12
        write(c / "extra.md", "y" * 80)                          # 20
        write(c / "rules" / "a.md", "z" * 100)                   # 25
        write(c / "skills" / "s1" / "SKILL.md", "---\nname: s1\ndescription: abcd\n---\nbody " * 1)
        write(c / "agents" / "ag.md", "---\ndescription: >\n  folded text\n---\n")
        write(plugin / "skills" / "p1" / "SKILL.md", "---\nname: p1\ndescription: hi\n---\n")
        write(Path(self.tmp.name) / "off" / "skills" / "q" / "SKILL.md", "---\nname: q\n---\n")
        write(c / "settings.json", json.dumps({"enabledPlugins": {"p@m": True, "off@m": False}}))
        write(c / "plugins" / "installed_plugins.json", json.dumps({"plugins": {
            "p@m": [{"scope": "user", "installPath": str(plugin)}],
            "off@m": [{"scope": "user", "installPath": str(Path(self.tmp.name) / "off")}]}}))
        self.project = Path(self.tmp.name) / "proj"
        self.project.mkdir()
        write(c / "projects" / audit.project_slug(self.project) / "memory" / "MEMORY.md", "m" * 48)  # 12

    def tearDown(self):
        self.tmp.cleanup()

    def test_totals_match_hand_count(self):
        rows = dict(audit.audit(self.config, self.project))
        claude = [t for k, t in rows.items() if k.startswith("CLAUDE.md")]
        self.assertEqual(sorted(claude), [12, 20])
        self.assertEqual(rows["rule a.md"], 25)
        self.assertEqual(rows["memory index MEMORY.md"], 12)
        self.assertEqual(rows["skills listing (user), 1 items"], len("- s1: abcd\n") // 4)
        self.assertEqual(rows["agents listing (user), 1 items"], len("- ag: folded text\n") // 4)
        self.assertEqual(rows["skills listing (plugins), 1 items"], len("- p1: hi\n") // 4)

    def test_disabled_plugin_and_missing_memory_are_skipped(self):
        rows = dict(audit.audit(self.config))
        self.assertNotIn("memory index MEMORY.md", rows)
        self.assertEqual(sum(1 for k in rows if "plugins" in k), 1)

    def test_import_cycle_counted_once(self):
        write(self.config / "extra.md", "@CLAUDE.md\n")
        rows = audit.audit(self.config)
        self.assertEqual(sum(1 for k, _ in rows if k.startswith("CLAUDE.md")), 2)

    def test_largest_first(self):
        sizes = [t for _, t in audit.audit(self.config, self.project)]
        self.assertEqual(sizes, sorted(sizes, reverse=True))

    def test_missing_config_dir_exits_2(self):
        self.assertEqual(audit.main(["--config", str(Path(self.tmp.name) / "nope")]), 2)


if __name__ == "__main__":
    unittest.main()
