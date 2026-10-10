"""Build the standalone Pages demo with only the Python standard library."""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "demo"
PORTAL = ROOT / "apps" / "operator-portal"


def main():
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    shutil.copytree(PORTAL, OUTPUT)
    shutil.copytree(ROOT / "assets" / "branding", OUTPUT / "branding")
    index = OUTPUT / "index.html"
    html = index.read_text(encoding="utf-8")
    html = html.replace(
        '<meta charset="utf-8">',
        '<meta charset="utf-8">\n    <meta name="xtract-mode" content="demo">',
        1,
    )
    html = html.replace(
        "  <body>",
        """  <body>
    <div class="demo-notice" role="note">
      <strong>Interactive demo</strong>
      <span>Sample data · simulated services · changes stay in this tab</span>
      <button type="button" class="btn small" id="demo-reset">Reset demo</button>
    </div>""",
        1,
    )
    index.write_text(html, encoding="utf-8")
    with (OUTPUT / "styles.css").open("a", encoding="utf-8") as style:
        style.write("""
body { display: flex; flex-direction: column; }
.app { flex: 1; min-height: 0; height: auto; }
.demo-notice { flex-shrink: 0; display: flex; align-items: center; flex-wrap: wrap; gap: 8px 16px;
  padding: 8px 16px; background: var(--warn-soft); color: var(--ink); border-bottom: 1px solid var(--line); }
.demo-notice span { flex: 1; font-size: 12px; }
.workspace { container-type: inline-size; }
@container (max-width: 750px) {
  .workspace-grid { grid-template-columns: minmax(0, 1fr); }
  .viewer { position: static; }
  .ocr-lines { max-height: 420px; }
}
""")
    with (OUTPUT / "app.js").open("a", encoding="utf-8") as app:
        app.write("""
$("#demo-reset").addEventListener("click", () => {
  window.history.replaceState(null, "", window.location.pathname);
  window.location.reload();
});
""")
    (OUTPUT / ".nojekyll").touch()
    print(f"Demo built at {OUTPUT}")


if __name__ == "__main__":
    main()
