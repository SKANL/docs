import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useMode, type Mode } from "@/app/mode";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const modes: Mode[] = ["supervise", "write"];

/** Mode switch, Advanced switch, theme and language toggles. */
export function ShellControls() {
  const { t, locale, setLocale } = useT();
  const { mode, setMode, advanced, setAdvanced } = useMode();
  const { resolvedTheme, setTheme } = useTheme();
  return <div className="flex flex-wrap items-center gap-3">
    <div role="group" aria-label={t("mode.label")} className="inline-flex rounded-md border p-0.5">
      {modes.map(item => <Button key={item} type="button" size="sm" variant={mode === item ? "default" : "ghost"} aria-pressed={mode === item} className={cn("h-7", mode !== item && "text-muted-foreground")} onClick={() => setMode(item)}>{t(`mode.${item}`)}</Button>)}
    </div>
    <div className="flex items-center gap-2">
      <Switch id="advanced-toggle" size="sm" checked={advanced} onCheckedChange={setAdvanced} />
      <Label htmlFor="advanced-toggle" className="text-sm">{t("advanced.label")}</Label>
    </div>
    <Button type="button" variant="outline" size="sm" aria-label={t("language.label")} title={t("language.label")} onClick={() => setLocale(locale === "es" ? "en" : "es")}>{locale.toUpperCase()}</Button>
    <Button type="button" variant="outline" size="icon-sm" aria-label={t("theme.label")} title={t("theme.label")} onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}>
      {resolvedTheme === "dark" ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
    </Button>
  </div>;
}
