/** localStorage that never throws: private mode, blocked site data and quota errors degrade to "nothing stored". */
export function readStored(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}

export function writeStored(key: string, value: string): void {
  try { localStorage.setItem(key, value); } catch { /* ponytail: preference is session-only when storage is blocked */ }
}
