// Applies the saved colour theme before first paint to avoid a light/dark flash.
(function applyStoredTheme() {
  try {
    var theme = window.localStorage.getItem("xtract.theme");
    if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  } catch (error) { /* storage unavailable: follow the system theme */ }
})();
