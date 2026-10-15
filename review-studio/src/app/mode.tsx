import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { readStored, writeStored } from "@/lib/storage";

export type Mode = "supervise" | "write";

const MODE_KEY = "review-studio.mode";
const ADVANCED_KEY = "review-studio.advanced";

type ModeState = {
  mode: Mode;
  advanced: boolean;
  /** False until the person picks a mode once; the first-run chooser keys off it. */
  hasChosenMode: boolean;
  setMode(mode: Mode): void;
  setAdvanced(advanced: boolean): void;
};

const ModeContext = createContext<ModeState | null>(null);

function storedMode(): Mode | null {
  const value = readStored(MODE_KEY);
  return value === "supervise" || value === "write" ? value : null;
}

/** How the person works (supervise an agent, or write in the UI) plus whether technical areas show. Per browser. */
export function ModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<Mode | null>(storedMode);
  const [advanced, setAdvancedState] = useState(() => readStored(ADVANCED_KEY) === "true");
  const setMode = useCallback((next: Mode) => { writeStored(MODE_KEY, next); setModeState(next); }, []);
  const setAdvanced = useCallback((next: boolean) => { writeStored(ADVANCED_KEY, String(next)); setAdvancedState(next); }, []);
  const value = useMemo<ModeState>(() => ({ mode: mode ?? "supervise", advanced, hasChosenMode: mode !== null, setMode, setAdvanced }), [mode, advanced, setMode, setAdvanced]);
  return <ModeContext.Provider value={value}>{children}</ModeContext.Provider>;
}

export function useMode(): ModeState {
  const value = useContext(ModeContext);
  if (!value) throw new Error("useMode must be used inside ModeProvider");
  return value;
}
