import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

type Props = { title?: string; message: string; onRetry?: () => void; retrying?: boolean };

export function ErrorState({ title = "Something went wrong", message, onRetry, retrying }: Props) {
  return <Alert variant="destructive" role="alert">
    <AlertTitle>{title}</AlertTitle>
    <AlertDescription>
      <p>{message}</p>
      {onRetry && <Button type="button" variant="outline" size="sm" className="mt-2" onClick={onRetry} disabled={retrying}>Try again</Button>}
    </AlertDescription>
  </Alert>;
}
