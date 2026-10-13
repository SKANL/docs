import{r as m,j as s}from"./react-Dr4p0F8r.js";import{Toaster as A}from"./index-048nbvdV.js";import{c as d,L as M}from"./index-BLcLX-kQ.js";/**
 * @license lucide-react v1.52.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const x={name:"circle-check",size:24,node:[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["path",{d:"m16 9-5.5 5.5L8 12",key:"xofnsj"}]],aliases:["check-circle-2"]};x.node;const S=d(x);/**
 * @license lucide-react v1.52.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const k={name:"info",size:24,node:[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["path",{d:"M12 16v-4",key:"1dtifu"}],["path",{d:"M12 8h.01",key:"e9boi3"}]]};k.node;const T=d(k);/**
 * @license lucide-react v1.52.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const v={name:"octagon-x",size:24,node:[["path",{d:"m15 9-6 6",key:"1uzhvr"}],["path",{d:"M2.586 16.726A2 2 0 0 1 2 15.312V8.688a2 2 0 0 1 .586-1.414l4.688-4.688A2 2 0 0 1 8.688 2h6.624a2 2 0 0 1 1.414.586l4.688 4.688A2 2 0 0 1 22 8.688v6.624a2 2 0 0 1-.586 1.414l-4.688 4.688a2 2 0 0 1-1.414.586H8.688a2 2 0 0 1-1.414-.586z",key:"2d38gg"}],["path",{d:"m9 9 6 6",key:"z0biqf"}]],aliases:["x-octagon"]};v.node;const w=d(v);/**
 * @license lucide-react v1.52.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const z={name:"triangle-alert",size:24,node:[["path",{d:"m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3",key:"wmoenq"}],["path",{d:"M12 9v4",key:"juzpu7"}],["path",{d:"M12 17h.01",key:"p32p05"}]],aliases:["alert-triangle"]};z.node;const L=d(z);var N=(t,o,p,n,c,a,h,u)=>{let r=document.documentElement,y=["light","dark"];function i(e){(Array.isArray(t)?t:[t]).forEach(l=>{let g=l==="class",_=g&&a?c.map(f=>a[f]||f):c;g?(r.classList.remove(..._),r.classList.add(a&&a[e]?a[e]:e)):r.setAttribute(l,e)}),b(e)}function b(e){u&&y.includes(e)&&(r.style.colorScheme=e)}function j(){return window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"}if(n)i(n);else try{let e=localStorage.getItem(o)||p,l=h&&e==="system"?j():e;i(l)}catch{}},C=m.createContext(void 0),$={setTheme:t=>{},themes:[]},E=()=>{var t;return(t=m.useContext(C))!=null?t:$};m.memo(({forcedTheme:t,storageKey:o,attribute:p,enableSystem:n,enableColorScheme:c,defaultTheme:a,value:h,themes:u,nonce:r,scriptProps:y})=>{let i=JSON.stringify([p,o,a,t,u,h,n,c]).slice(1,-1);return m.createElement("script",{...y,suppressHydrationWarning:!0,nonce:typeof window>"u"?r:"",dangerouslySetInnerHTML:{__html:`(${N.toString()})(${i})`}})});const q=({...t})=>{const{theme:o="system"}=E();return s.jsx(A,{theme:o,className:"toaster group",icons:{success:s.jsx(S,{className:"size-4"}),info:s.jsx(T,{className:"size-4"}),warning:s.jsx(L,{className:"size-4"}),error:s.jsx(w,{className:"size-4"}),loading:s.jsx(M,{className:"size-4 animate-spin"})},style:{"--normal-bg":"var(--popover)","--normal-text":"var(--popover-foreground)","--normal-border":"var(--border)","--border-radius":"var(--radius)"},...t})};export{q as Toaster};
