// Typed client for service health and the capability catalogue.
import type { Transport } from "../http";

export type ApiHealth = { ready: boolean; protocol?: string; version?: string };
export type Capability = { id: string; cli_command: string | null; route: string | null; scopes: string[]; surface: "web+desktop"; slice: string; status: "available" | "planned" };
export type CapabilityGroup = { id: string; capabilities: Capability[] };
export type CapabilityCatalog = { groups: CapabilityGroup[] };

export interface SystemApi {
  health(): Promise<ApiHealth>;
  getCapabilities(): Promise<CapabilityCatalog>;
}

export function createSystemApi(t: Transport): SystemApi {
  return {
    health: () => t.send("../health", { headers: { Accept: "application/json" } }, response => response.json()),
    getCapabilities: () => t.request("capabilities"),
  };
}
