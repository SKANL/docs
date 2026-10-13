import type { Capability, CapabilityCatalog, ReviewApi } from "../api/models";

export type CapabilityAction = Capability & { enabled: boolean };

export function flattenCapabilities(catalog: CapabilityCatalog): CapabilityAction[] {
  return catalog.groups.flatMap(group => group.capabilities).map(capability => ({
    ...capability,
    enabled: capability.status === "available" && capability.route !== null,
  }));
}

export async function loadCapabilityActions(api: ReviewApi): Promise<CapabilityAction[]> {
  if (!api.getCapabilities) return [];
  return flattenCapabilities(await api.getCapabilities());
}
