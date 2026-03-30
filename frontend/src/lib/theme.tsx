import { createContext, useContext, useEffect, useState } from "react";

type Theme = "light" | "dark" | "system";

interface ThemeContext {
  theme: Theme;
  resolved: "light" | "dark";
  setTheme: (t: Theme) => void;
}

const Ctx = createContext<ThemeContext>({
  theme: "system",
  resolved: "light",
  setTheme: () => {},
});

const STORAGE_KEY = "yomeru-theme";

function getSystemTheme(): "light" | "dark" {
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(
    () => (localStorage.getItem(STORAGE_KEY) as Theme) ?? "system",
  );

  const resolved = theme === "system" ? getSystemTheme() : theme;

  useEffect(() => {
    const root = document.documentElement;
    root.classList.remove("light", "dark");
    root.classList.add(resolved);
  }, [resolved]);

  // listen for system preference changes
  useEffect(() => {
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => {
      document.documentElement.classList.remove("light", "dark");
      document.documentElement.classList.add(getSystemTheme());
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [theme]);

  const setTheme = (t: Theme) => {
    localStorage.setItem(STORAGE_KEY, t);
    setThemeState(t);
  };

  return (
    <Ctx.Provider value={{ theme, resolved, setTheme }}>
      {children}
    </Ctx.Provider>
  );
}

export const useTheme = () => useContext(Ctx);
