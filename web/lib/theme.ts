/* Theme constants shared by the server layout (pre-paint script) and the client ThemeProvider. */
export type ThemeMode = "light" | "dark" | "system";
export const THEME_KEY = "emvoox-theme";

/** Runs in <head> before first paint: resolves the theme, marks <html>, and hides the body for dark visitors until
    React has applied the antd dark theme (the prerendered HTML is light). */
export const THEME_INIT_SCRIPT = `(function(){try{var m=localStorage.getItem("${THEME_KEY}")||"system";var d=m==="dark"||(m!=="light"&&window.matchMedia&&matchMedia("(prefers-color-scheme: dark)").matches);var e=document.documentElement;e.setAttribute("data-theme",d?"dark":"light");if(d){e.classList.add("theme-pending");setTimeout(function(){e.classList.remove("theme-pending")},3000)}}catch(_){}})();`;
