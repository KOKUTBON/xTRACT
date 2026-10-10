import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTAL_DIR = ROOT / "apps" / "operator-portal"


class FrontendStructureTests(unittest.TestCase):
    def test_index_html_loads_module_script(self):
        html = (PORTAL_DIR / "index.html").read_text("utf-8")
        self.assertIn('<script type="module" src="./app.js"></script>', html)
        self.assertNotIn("access_token", html)

    def test_app_js_and_modules_exist(self):
        self.assertTrue((PORTAL_DIR / "app.js").is_file())
        self.assertTrue((PORTAL_DIR / "modules" / "api.js").is_file())
        self.assertTrue((PORTAL_DIR / "modules" / "ui.js").is_file())

    def test_no_access_token_query_params_constructed(self):
        for js_file in PORTAL_DIR.rglob("*.js"):
            content = js_file.read_text("utf-8")
            self.assertNotRegex(
                content,
                r"access_token=",
                f"Found access_token query param in {js_file.name}",
            )

    def test_tokens_use_session_storage(self):
        api_js = (PORTAL_DIR / "modules" / "api.js").read_text("utf-8")
        self.assertIn("window.sessionStorage.getItem(key)", api_js)
        self.assertIn('readSessionStorage("xtract.token")', api_js)
        self.assertNotIn('localStorage.getItem("xtract.token")', api_js)

    def test_source_blob_manager_cleanup(self):
        app_js = (PORTAL_DIR / "app.js").read_text("utf-8")
        self.assertIn("sourceBlobManager.revoke()", app_js)
        self.assertIn("fetchSourceBlob", app_js)

    def test_icon_sprite_covers_every_referenced_icon(self):
        html = (PORTAL_DIR / "index.html").read_text("utf-8")
        defined = set(re.findall(r'<symbol id="i-([a-z-]+)"', html))
        referenced = set(re.findall(r'href="#i-([a-z-]+)"', html))
        for js_file in PORTAL_DIR.rglob("*.js"):
            content = js_file.read_text("utf-8")
            referenced |= set(re.findall(r'icon\("([a-z-]+)"', content))
            for block in re.findall(
                r"(?:STAGE_ICONS|TOAST_ICONS|THEME_ICONS) = \{([^}]*)\}", content
            ):
                referenced |= set(re.findall(r':\s*"([a-z-]+)"', block))
        self.assertTrue(defined)
        self.assertLessEqual(referenced, defined, f"Missing icons: {referenced - defined}")

    def test_no_inline_scripts_or_styles_for_csp(self):
        html = (PORTAL_DIR / "index.html").read_text("utf-8")
        self.assertNotRegex(html, r"<script(?![^>]*\ssrc=)[^>]*>")
        self.assertNotIn("style=", html)
        self.assertNotIn("<style", html)

    def test_theme_is_applied_before_stylesheet(self):
        html = (PORTAL_DIR / "index.html").read_text("utf-8")
        self.assertLess(html.index("./modules/theme.js"), html.index("./styles.css"))
        self.assertIn('[data-theme="dark"]', (PORTAL_DIR / "styles.css").read_text("utf-8"))

    def test_branding_assets_exist(self):
        for name in ("logo.svg", "logo-dark.svg", "logo-mark.svg", "logo-app-icon.png"):
            self.assertTrue((ROOT / "assets" / "branding" / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
