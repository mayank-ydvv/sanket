import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { en, type MessageKey, ta } from "@/lib/messages";

export type Lang = "en" | "ta";
export type Translate = (key: MessageKey, vars?: Record<string, string | number>) => string;

interface I18nState {
  lang: Lang;
  setLang: (lang: Lang) => void;
  toggle: () => void;
  t: Translate;
}

const STORAGE_KEY = "sanket-lang";
const DICTIONARIES: Record<Lang, Record<MessageKey, string>> = { en, ta };
const I18nContext = createContext<I18nState | null>(null);

function readStored(): Lang {
  try {
    return localStorage.getItem(STORAGE_KEY) === "ta" ? "ta" : "en";
  } catch {
    return "en";
  }
}

/** English / Tamil UI with a remembered choice. Report text is never translated here. */
export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(readStored);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* private mode: the choice just isn't remembered */
    }
  }, []);

  const value = useMemo<I18nState>(() => {
    const dictionary = DICTIONARIES[lang];
    const t: Translate = (key, vars) => {
      const text = dictionary[key];
      return vars ? text.replace(/\{(\w+)\}/g, (match, name: string) => String(vars[name] ?? match)) : text;
    };
    return { lang, setLang, toggle: () => setLang(lang === "en" ? "ta" : "en"), t };
  }, [lang, setLang]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nState {
  const state = useContext(I18nContext);
  if (!state) throw new Error("useI18n must be used inside I18nProvider");
  return state;
}
