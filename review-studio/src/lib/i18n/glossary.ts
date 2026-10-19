/** Concepts the glossary explains. `glossary.<term>.name` and `.body` live in the message dictionaries (es + en). */
export const glossaryTerms = ["source", "finding", "run", "deliver", "baseline", "evidence", "passport", "attestation", "digest", "node"] as const;
export type GlossaryTerm = (typeof glossaryTerms)[number];
