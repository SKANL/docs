import { useQuery } from "@tanstack/react-query";
import { ApiError } from "@/api/errors";
import { useApi } from "@/app/providers";

export const authoringKeys = {
  sections: (doc: string) => ["authoring", doc, "sections"],
  classification: (doc: string) => ["authoring", doc, "classification"],
  context: (doc: string) => ["authoring", doc, "context"],
  assets: (doc: string) => ["authoring", doc, "assets"],
  revisions: () => ["authoring", "revisions"],
};

export function useSections(doc: string) {
  const api = useApi();
  return useQuery({ queryKey: authoringKeys.sections(doc), queryFn: () => api.listDocumentSections!(doc), enabled: !!api.listDocumentSections });
}

export function useClassification(doc: string) {
  const api = useApi();
  return useQuery({
    queryKey: authoringKeys.classification(doc),
    // A 404 classification_unavailable means no queue exists yet; that is "nothing pending", not a failure.
    queryFn: async () => {
      try { return (await api.getClassificationQueue!(doc)).items; }
      catch (error) { if (error instanceof ApiError && error.code === "classification_unavailable") return []; throw error; }
    },
    enabled: !!api.getClassificationQueue,
  });
}

export function useContextStatus(doc: string) {
  const api = useApi();
  return useQuery({ queryKey: authoringKeys.context(doc), queryFn: () => api.getDocumentContext!(doc), enabled: !!api.getDocumentContext });
}
