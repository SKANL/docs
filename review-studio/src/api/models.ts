export type Status = "passed" | "warnings" | "failed" | "unverified";
export type Run = { id:string; document:string; template:string; startedAt:string; duration:string; status:Status; findings:number; artifactCount:number };
export type Finding = { id:string; title:string; severity:"critical"|"high"|"medium"|"low"; status:Status; location:string; summary:string; owner:string; updated:string };
export type Artifact = { id:string; name:string; kind:"DOCX"|"PDF"|"HTML"|"PNG"; size:string; status:Status; pages?:number; checksum:string };
export type EvidencePassport = { id:string; runId:string; verifiedAt:string; coverage:number; attestations:number; sources:number; claims:number; unresolved:number };
export type GraphNode = { id:string; label:string; type:"claim"|"source"|"artifact"|"section"; confidence:number; x:number; y:number };
export type GraphEdge = { from:string; to:string; relation:string };
export type GraphQuery = "claims_without_evidence"|"findings_affected_by_revision"|"artifacts_derived_from_input"|"unused_references"|"unmet_requirements";
export type GraphQueryItem = { id:string; kind:string; label:string; confidence?:number; attributes?:Record<string, unknown> };
export type GraphQueryResult = { items:GraphQueryItem[]; graphUnavailable?:boolean; warnings?:string[]; context?:Record<string, unknown> };
export type Template = { id:string; name:string; version:string; sections:number; contract:Status; updated:string };
export type Baseline = { id:string; name:string; scope:string; created:string; status:Status; delta:string };
export type Revision = { id:string; message:string; author:string; date:string; status:Status; files:number };
export type Publication = { id:string; environment:string; artifact:string; status:Status; publishedAt:string; approver:string };
export interface ReviewApi { listRuns():Promise<Run[]>; listFindings():Promise<Finding[]>; listArtifacts():Promise<Artifact[]>; getPassport(runId:string):Promise<EvidencePassport>; getGraph():Promise<{nodes:GraphNode[];edges:GraphEdge[]}>; getGraphQuery(query:GraphQuery,id?:string):Promise<GraphQueryResult>; listTemplates():Promise<Template[]>; listBaselines():Promise<Baseline[]>; listRevisions():Promise<Revision[]>; listPublications():Promise<Publication[]>; }
