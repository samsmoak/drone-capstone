"""The kit's own tests: build a throwaway multi-repo project, run the kit on it,
and check that every dependency is generated, nothing is overwritten, and the
generated checker catches the faults it exists to catch.

    python3 -m unittest discover -s ~/.claude/feature-kit/tests -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent / "kit.py"
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def run(cwd, *args):
    return subprocess.run([sys.executable, str(KIT), *args], cwd=cwd, capture_output=True,
                          text=True, env=ENV)


def write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def commit(repo):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, env=ENV, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, env=ENV, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, env=ENV, check=True)


class KitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.api, self.web, self.app, self.other = (root / n for n in ("api", "web", "app", "other"))
        write(self.api / "go.mod", "module x/api\n\ngo 1.22\n")
        write(self.api / "internal/orders/service.go", "package orders\n")
        write(self.api / "CLAUDE.md", "Backend for ../web and ../app.\n")
        write(self.web / "package.json", json.dumps({"scripts": {"lint": "x", "build": "y"},
                                                     "dependencies": {"next": "15"}}))
        write(self.web / "tsconfig.json", "{}")
        write(self.web / "src/lib/endpoints.ts", "export const Endpoints = { a: '/a' };\n")
        write(self.web / "src/app/orders/page.tsx",
              "// PARITY: app/lib/orders_screen.dart\nexport default function P(){return null}\n")
        write(self.app / "pubspec.yaml", "name: app\n")
        write(self.app / "lib/api_endpoints.dart", "class ApiEndpoints { static const a = '/a'; }\n")
        write(self.app / "lib/orders_screen.dart", "class OrdersScreen {}\n")
        write(self.other / "package.json", "{}")
        for r in (self.api, self.web, self.app, self.other):
            commit(r)

    def tearDown(self):
        self.tmp.cleanup()

    def test_doctor_reports_missing_then_init_generates_everything(self):
        r = run(self.api, "doctor")
        self.assertEqual(r.returncode, 1)
        self.assertIn("[MISSING] profile", r.stdout)
        r = run(self.api, "init")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        docs = self.api / "docs"
        for f in ("PROJECT_PROFILE.txt", "README.md", "_templates/feature.txt", "graph.config.json",
                  "graph_check.py", "GRAPH_STATE.txt", "design/PREFERENCES.txt", "design/components.txt"):
            self.assertTrue((docs / f).exists(), f)
        for d in ("features", "design", "platform"):
            self.assertTrue((docs / d).is_dir(), d)
        self.assertEqual(run(self.api, "doctor").returncode, 0)

    def test_unrelated_sibling_is_not_included(self):
        run(self.api, "init")
        cfg = json.loads((self.api / "docs/graph.config.json").read_text())
        names = {r["name"] for r in cfg["repos"]}
        self.assertEqual(names, {"api", "web", "app"})
        self.assertIn("other", (self.api / "docs/PROJECT_PROFILE.txt").read_text())

    def test_a_dotted_identifier_does_not_pull_in_a_sibling(self):
        # "com.other.app" names no repo; only "../x" or a standalone word does.
        write(self.api / "CLAUDE.md", "Backend for ../web and ../app. Bundle com.other.app.\n")
        run(self.api, "init")
        cfg = json.loads((self.api / "docs/graph.config.json").read_text())
        self.assertNotIn("other", {r["name"] for r in cfg["repos"]})

    def test_an_existing_config_decides_the_repos(self):
        run(self.api, "init")
        cfgp = self.api / "docs/graph.config.json"
        cfg = json.loads(cfgp.read_text())
        cfg["repos"].append({"name": "other", "path": "../../other"})
        cfgp.write_text(json.dumps(cfg))
        (self.api / "docs/PROJECT_PROFILE.txt").unlink()
        run(self.api, "init")
        self.assertIn("  other\n    path", (self.api / "docs/PROJECT_PROFILE.txt").read_text())

    def test_detects_gates_roles_and_endpoints(self):
        run(self.api, "init")
        prof = (self.api / "docs/PROJECT_PROFILE.txt").read_text()
        self.assertIn("go vet ./...", prof)
        self.assertIn("flutter analyze", prof)
        self.assertIn("npm run lint", prof)
        self.assertIn("ApiEndpoints.<name>", prof)
        cfg = json.loads((self.api / "docs/graph.config.json").read_text())
        self.assertIn(".dart", cfg["endpoint_refs"])
        self.assertIn(".tsx", cfg["endpoint_refs"])

    def test_init_never_overwrites(self):
        run(self.api, "init")
        router = self.api / "docs/README.md"
        router.write_text("MINE\n")
        cfgp = self.api / "docs/graph.config.json"
        cfg = json.loads(cfgp.read_text())
        cfg["project"] = "custom"
        cfgp.write_text(json.dumps(cfg))
        r = run(self.api, "init")
        self.assertIn("nothing to create", r.stdout)
        self.assertEqual(router.read_text(), "MINE\n")
        self.assertEqual(json.loads(cfgp.read_text())["project"], "custom")

    def test_upgrade_replaces_only_the_checker(self):
        run(self.api, "init")
        chk = self.api / "docs/graph_check.py"
        chk.write_text(chk.read_text().replace("KIT_VERSION = ", "KIT_VERSION = 0 and "))
        cfg_before = (self.api / "docs/graph.config.json").read_text()
        self.assertIn("OUTDATED", run(self.api, "doctor").stdout)
        run(self.api, "upgrade")
        self.assertNotIn("OUTDATED", run(self.api, "doctor").stdout)
        self.assertEqual((self.api / "docs/graph.config.json").read_text(), cfg_before)

    def test_hub_is_found_from_another_repo(self):
        run(self.api, "init")
        r = run(self.web, "doctor")
        self.assertIn(f"docs hub: {self.api.resolve()}", r.stdout)

    def test_checker_catches_one_way_stale_and_parity(self):
        run(self.api, "init")
        feats = self.api / "docs/features"
        write(feats / "orders-app.txt",
              "Last verified: 2099-01-01\nSOURCE: app/lib/orders_screen.dart\n"
              "depends-on        orders-web.txt\n")
        write(feats / "orders-web.txt",
              "Last verified: 2000-01-01\nSOURCE: web/src/app/orders/page.tsx\n")
        out = run(self.api, "check").stdout
        self.assertIn("ONE-WAY", out)
        self.assertIn("STALE", out)
        self.assertIn("declare no copied-from/copied-to edge", out)
        self.assertNotIn("PREFERENCES.txt — no edges", out)

    def test_checker_refuses_a_clean_report_on_zero_docs(self):
        run(self.api, "init")
        for p in (self.api / "docs/design").glob("*.txt"):
            p.unlink()
        r = run(self.api, "check")
        self.assertEqual(r.returncode, 2)
        self.assertIn("refusing to report a clean graph", r.stdout)

    def test_parity_ledger_is_created_once(self):
        run(self.api, "init")
        r1 = run(self.api, "parity-ledger", str(self.web), "Orders port", "--source", "app")
        r2 = run(self.api, "parity-ledger", str(self.web), "Orders port", "--source", "app")
        self.assertIn("Created", r1.stdout)
        self.assertIn("Exists", r2.stdout)
        self.assertTrue((self.web / "ORDERS_PORT_PARITY.txt").exists())


if __name__ == "__main__":
    unittest.main()
