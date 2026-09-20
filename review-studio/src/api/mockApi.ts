import type { GraphQuery, ReviewApi } from "./models";
const runs = [
{id:"run-2026-09-15-1432",document:"Safety case — northstar.docx",template:"Technical report SRS",startedAt:"Sep 15, 2026 · 14:32",duration:"3m 42s",status:"warnings",findings:7,artifactCount:12},
{id:"run-2026-09-14-0911",document:"Safety case — northstar.docx",template:"Technical report SRS",startedAt:"Sep 14, 2026 · 09:11",duration:"3m 18s",status:"passed",findings:2,artifactCount:12},
{id:"run-2026-09-12-1748",document:"Q3 operations review.docx",template:"Institutional report",startedAt:"Sep 12, 2026 · 17:48",duration:"2m 54s",status:"failed",findings:11,artifactCount:9}] as const;
const findings = [
{id:"F-104",title:"Evidence passport missing source locator",severity:"high",status:"failed",location:"§3.2 · Methodology · p. 6",summary:"Claim C-238 cannot be traced to a page-level source locator.",owner:"Unassigned",updated:"12 min ago"},
{id:"F-102",title:"Figure caption differs from baseline",severity:"medium",status:"warnings",location:"Figure 4 · p. 11",summary:"The generated caption changed after the latest renderer update.",owner:"M. Chen",updated:"38 min ago"},
{id:"F-099",title:"Heading hierarchy skips level",severity:"medium",status:"failed",location:"§4 · Results · p. 14",summary:"Heading 3 appears before a sibling Heading 2.",owner:"A. Rivera",updated:"1 hr ago"},
{id:"F-094",title:"Alt text is present and descriptive",severity:"low",status:"passed",location:"Figure 2 · p. 8",summary:"Visual alternative meets the configured content contract.",owner:"A. Rivera",updated:"Yesterday"},
{id:"F-091",title:"PDF visual comparison not available",severity:"low",status:"unverified",location:"Artifact northstar.pdf",summary:"The visual adapter is unavailable in this environment.",owner:"System",updated:"Yesterday"}] as const;
const artifacts = [
{id:"a-docx",name:"northstar-draft.docx",kind:"DOCX",size:"842 KB",status:"passed",pages:18,checksum:"sha256: a83f…c91d"},
{id:"a-pdf",name:"northstar-draft.pdf",kind:"PDF",size:"1.8 MB",status:"warnings",pages:18,checksum:"sha256: 4b12…8ed0"},
{id:"a-html",name:"northstar-draft.html",kind:"HTML",size:"96 KB",status:"passed",checksum:"sha256: 78da…144e"},
{id:"a-preview",name:"page-011.png",kind:"PNG",size:"188 KB",status:"unverified",pages:1,checksum:"sha256: 09c0…4a10"}] as const;
export const mockApi:ReviewApi = {
async listRuns(){return [...runs]}, async listFindings(){return [...findings]}, async listArtifacts(){return [...artifacts]},
async getPassport(runId){return {id:"passport-284",runId,verifiedAt:"Sep 15, 2026 · 14:36 UTC",coverage:92,attestations:48,sources:31,claims:124,unresolved:3}},
async getGraph(){return {nodes:[{id:"claim",label:"C-238: locator required",type:"claim",confidence:.82,x:50,y:32},{id:"source",label:"Source S-031",type:"source",confidence:.99,x:18,y:67},{id:"artifact",label:"northstar.pdf",type:"artifact",confidence:.96,x:82,y:67},{id:"section",label:"§3.2 Methodology",type:"section",confidence:.91,x:50,y:78}],edges:[{from:"source",to:"claim",relation:"supports"},{from:"claim",to:"section",relation:"appears in"},{from:"section",to:"artifact",relation:"rendered as"}]}},
async getGraphQuery(query:GraphQuery,id?:string){return {items:[],context:{source:"mock graph",query,id:id??null}}},
async listTemplates(){return [{id:"srs",name:"Technical report SRS",version:"v2.4",sections:8,contract:"passed",updated:"Sep 12, 2026"},{id:"institutional",name:"Institutional report",version:"v1.8",sections:11,contract:"warnings",updated:"Aug 28, 2026"}]},
async listBaselines(){return [{id:"base-31",name:"Northstar release candidate",scope:"18 pages · DOCX + PDF",created:"Sep 14, 2026",status:"passed",delta:"0.4% visual delta"},{id:"base-27",name:"Operations Q3",scope:"9 pages · PDF",created:"Sep 10, 2026",status:"warnings",delta:"3.8% visual delta"}]},
async listRevisions(){return [{id:"rev-18",message:"Add page-level source locator to C-238",author:"M. Chen",date:"Sep 15 · 16:04",status:"warnings",files:2},{id:"rev-17",message:"Regenerate figures with renderer 0.9.6",author:"A. Rivera",date:"Sep 15 · 14:39",status:"passed",files:6}]},
async listPublications(){return [{id:"pub-09",environment:"Staging",artifact:"northstar-draft.pdf",status:"warnings",publishedAt:"Sep 15, 2026 · 16:12",approver:"M. Chen"},{id:"pub-08",environment:"Production",artifact:"northstar-body.docx",status:"passed",publishedAt:"Sep 14, 2026 · 09:35",approver:"A. Rivera"}]}
};
