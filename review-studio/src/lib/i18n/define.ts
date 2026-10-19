/** An English dictionary and its Spanish twin; the type forces the same keys in both. */
export const defineMessages = <const E extends Record<string, string>>(en: E, es: Record<keyof E, string>) => ({ en, es });
