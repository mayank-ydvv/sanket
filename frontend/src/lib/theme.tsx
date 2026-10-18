import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";

export type ThemeChoice = "light" | "dark" | "system";
type Resolved = "light" | "dark";

interface ThemeState {
  theme: ThemeChoice;
  systemTheme: Resolved;
  resolved: Resolved;
  setTheme: (theme: ThemeChoice) => void;
  toggle: () => void;
}

const STORAGE_KEY = "sanket-theme";
const ThemeContext = createContext<ThemeState | null>(null);

function readStored(): ThemeChoice {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" || value === "system" ? value : "system";
  } catch {
    return "system";
  }
}

function systemPreference(): Resolved {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Light/dark theme with a remembered choice; "system" follows the OS. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeChoice>(readStored);
  const [systemTheme, setSystemTheme] = useState<Resolved>(systemPreference);
  const resolved = theme === "system" ? systemTheme : theme;

  useEffect(() => {
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setSystemTheme(query.matches ? "dark" : "light");
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", resolved === "dark");
    document.documentElement.style.colorScheme = resolved;
  }, [resolved]);

  const setTheme = useCallback((next: ThemeChoice) => {
    setThemeState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* private mode: the choice just isn't remembered */
    }
  }, []);

  const value = useMemo(
    () => ({ theme, systemTheme, resolved, setTheme, toggle: () => setTheme(resolved === "dark" ? "light" : "dark") }),
    [theme, systemTheme, resolved, setTheme],
  );
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeState {
  const state = useContext(ThemeContext);
  if (!state) throw new Error("useTheme must be used inside ThemeProvider");
  return state;
}
