import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { readStored, writeStored } from "@/lib/storage";
import { en, es, type MessageKey } from "./messages";

export type Locale = "es" | "en";
export type { MessageKey };
type Dictionaries = { en: Record<string, string>; es: Record<string, string | undefined> };

const STORAGE_KEY = "review-studio.locale";
const dictionaries: Dictionaries = { en, es };
let defaultLocale: Locale = "es";

/** Locale used when nothing is stored. The test setup pins it to English. */
export function setDefaultLocale(locale: Locale) { defaultLocale = locale; }

/** Looks `key` up in `locale`, then in English, then returns the key itself. `{name}` placeholders are filled from `vars`. */
export function translate(locale: Locale, key: string, vars?: Record<string, string | number>, source: Dictionaries = dictionaries): string {
  const text = source[locale][key] ?? source.en[key] ?? key;
  return vars ? text.replace(/\{(\w+)\}/g, (match, name: string) => (name in vars ? String(vars[name]) : match)) : text;
}

/** True when `key` is a known message key; lets dynamic keys (like server capability ids) fall back instead of showing the raw key. */
export const hasMessage = (key: string): key is MessageKey => key in en;

/** A server status word in the current language; an unknown word is shown as the server sent it. */
export const statusKey = (prefix: string, status: string): MessageKey | null => hasMessage(`${prefix}.${status}`) ? `${prefix}.${status}` as MessageKey : null;

type I18n = { locale: Locale; setLocale(locale: Locale): void; t(key: MessageKey, vars?: Record<string, string | number>): string };
const I18nContext = createContext<I18n | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(() => { const stored = readStored(STORAGE_KEY); return stored === "es" || stored === "en" ? stored : defaultLocale; });
  const setLocale = useCallback((next: Locale) => { writeStored(STORAGE_KEY, next); setLocaleState(next); }, []);
  const value = useMemo<I18n>(() => ({ locale, setLocale, t: (key, vars) => translate(locale, key, vars) }), [locale, setLocale]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useT(): I18n {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useT must be used inside I18nProvider");
  return value;
}
