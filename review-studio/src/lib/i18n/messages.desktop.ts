import { defineMessages } from "./define";

/** Desktop-only screens: the startup wait and the service-failure screen. */
export const desktop = defineMessages({
  "sidecar.starting.title": "Starting Review Studio",
  "sidecar.starting.body": "Getting everything ready. The first start can take a minute.",
  "sidecar.failed.title": "Review Studio could not start",
  "sidecar.failed.body": "The part of the app that does the work did not start. Try again, or open the log to see what happened.",
  "sidecar.retry": "Retry",
  "sidecar.viewLog": "View log",
  "sidecar.log": "Service log",
  "sidecar.logEmpty": "The log is empty.",
  "sidecar.logFailed": "Could not read the log: {error}",
}, {
  "sidecar.starting.title": "Iniciando Review Studio",
  "sidecar.starting.body": "Preparando todo. El primer inicio puede tardar un minuto.",
  "sidecar.failed.title": "Review Studio no pudo iniciar",
  "sidecar.failed.body": "La parte de la aplicación que hace el trabajo no arrancó. Inténtalo de nuevo o abre el registro para ver qué pasó.",
  "sidecar.retry": "Reintentar",
  "sidecar.viewLog": "Ver registro",
  "sidecar.log": "Registro del servicio",
  "sidecar.logEmpty": "El registro está vacío.",
  "sidecar.logFailed": "No se pudo leer el registro: {error}",
});
