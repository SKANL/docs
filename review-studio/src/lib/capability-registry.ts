import { useQuery } from "@tanstack/react-query";
import { useApi } from "@/app/providers";
import type { Capability, CapabilityCatalog, ReviewApi } from "../api/models";

export type CapabilityAction = Capability & { enabled: boolean };

function flattenCapabilities(catalog: CapabilityCatalog): CapabilityAction[] {
  return catalog.groups.flatMap(group => group.capabilities).map(capability => ({
    ...capability,
    enabled: capability.status === "available" && capability.route !== null,
  }));
}

async function loadCapabilityActions(api: ReviewApi): Promise<CapabilityAction[]> {
  if (!api.getCapabilities) return [];
  return flattenCapabilities(await api.getCapabilities());
}

/** The server's capability catalogue, loaded once per app and shared by the gate and the command palette. */
export function useCapabilityActions({ enabled = true }: { enabled?: boolean } = {}) {
  const api = useApi();
  return useQuery({ queryKey: ["capabilities"], queryFn: () => loadCapabilityActions(api), enabled });
}

/** Capability gate: true only when the server catalogue lists the capability as available. */
export function useCapability() {
  const { data } = useCapabilityActions();
  return (id: string) => data?.some(item => item.id === id && item.enabled) ?? false;
}
