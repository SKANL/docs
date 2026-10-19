import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { errorMessageKey, technicalDetails } from "@/lib/friendly-error";
import { useT } from "@/lib/i18n";

type Props = { title?: string; message?: string; error?: unknown; onRetry?: () => void; retrying?: boolean };

/**
 * Pass `error` to get a plain-language message with the raw server text, code and request id tucked into a
 * collapsed "Technical details" disclosure. `message` is for text that is already written for people.
 */
export function ErrorState({ title, message, error, onRetry, retrying }: Props) {
  const { t } = useT();
  const details = error === undefined ? [] : technicalDetails(error);
  return <Alert variant="destructive" role="alert">
    <AlertTitle>{title ?? t("error.title")}</AlertTitle>
    <AlertDescription>
      <p>{error === undefined ? message : t(errorMessageKey(error))}</p>
      {details.length > 0 && <details className="mt-2 text-xs">
        <summary className="w-fit cursor-pointer font-medium">{t("error.details")}</summary>
        <dl className="mt-1 grid gap-x-3 gap-y-0.5 sm:grid-cols-[auto_1fr]">{details.map(([field, value]) => <div key={field} className="contents"><dt className="text-muted-foreground">{t(`error.detail.${field}`)}</dt><dd className="break-all">{value}</dd></div>)}</dl>
      </details>}
      {onRetry && <Button type="button" variant="outline" size="sm" className="mt-2" onClick={onRetry} disabled={retrying}>{t("error.retry")}</Button>}
    </AlertDescription>
  </Alert>;
}
