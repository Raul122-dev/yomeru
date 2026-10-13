import{c as n,j as a,a as t,r as c}from"./index-CenG5esd.js";import{E as y}from"./button-CstsSrfD.js";import{X as j}from"./x-0pwFlGl-.js";import{C as w}from"./trash-2-DENy4xJi.js";/**
 * @license lucide-react v0.441.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const k=n("Ban",[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["path",{d:"m4.9 4.9 14.2 14.2",key:"1m5liu"}]]);/**
 * @license lucide-react v0.441.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const N=n("Circle",[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}]]);/**
 * @license lucide-react v0.441.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const S=n("LoaderCircle",[["path",{d:"M21 12a9 9 0 1 1-6.219-8.56",key:"13zald"}]]);/**
 * @license lucide-react v0.441.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const L=n("RotateCcw",[["path",{d:"M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8",key:"1357e3"}],["path",{d:"M3 3v5h5",key:"1xhq8a"}]]);/**
 * @license lucide-react v0.441.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const T=n("TriangleAlert",[["path",{d:"m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3",key:"wmoenq"}],["path",{d:"M12 9v4",key:"juzpu7"}],["path",{d:"M12 17h.01",key:"p32p05"}]]),z=y("inline-flex items-center gap-1 rounded-[var(--radius-sm)] border px-1.5 py-px font-mono text-[11px] leading-4 font-medium uppercase tracking-wide",{variants:{variant:{default:"border-[hsl(var(--border))] text-[hsl(var(--text-muted))]",pending:"border-[hsl(var(--border))] text-[hsl(var(--text-muted))]",running:"border-[hsl(var(--accent2)/.45)] text-[hsl(var(--accent2))] bg-[hsl(var(--accent2-soft))]",done:"border-[hsl(var(--text)/.25)] text-[hsl(var(--text))]",partial:"border-[hsl(var(--warning)/.6)] text-[hsl(var(--warning-deep))]",stale:"border-[hsl(var(--warning)/.6)] text-[hsl(var(--warning-deep))] border-dashed",cancelled:"border-[hsl(var(--border-strong))] text-[hsl(var(--text-muted))] border-dashed",failed:"border-[hsl(var(--danger)/.45)] text-[hsl(var(--danger))]"}},defaultVariants:{variant:"default"}});function A({className:e,variant:s,...r}){return a.jsx("span",{className:t(z({variant:s}),e),...r})}const C={pending:"pending",running:"running",done:"done",partial:"partial",failed:"failed",stale:"outdated",cancelled:"cancelled"},E={partial:"Some pages failed or only some pages were run",stale:"An earlier phase changed after this one ran — run it again",cancelled:"Stopped before finishing"};function I({status:e,className:s}){const r=t("size-3.5 shrink-0",s);switch(e){case"done":return a.jsx(w,{className:t(r,"text-[hsl(var(--text))]"),strokeWidth:2.5});case"running":return a.jsx(S,{className:t(r,"animate-spin text-[hsl(var(--accent2))]")});case"failed":return a.jsx(j,{className:t(r,"text-[hsl(var(--danger))]"),strokeWidth:2.5});case"partial":return a.jsx(T,{className:t(r,"text-[hsl(var(--warning-deep))]")});case"stale":return a.jsx(L,{className:t(r,"text-[hsl(var(--warning-deep))]")});case"cancelled":return a.jsx(k,{className:t(r,"text-[hsl(var(--text-muted))]")});default:return a.jsx(N,{className:t(r,"text-[hsl(var(--text-faint))]")})}}function q({status:e}){return a.jsxs(A,{variant:e,title:E[e],children:[a.jsx(I,{status:e,className:"size-3"}),C[e]]})}const B=[160,320,640,1024,1600,2400];function d(e,s){return`${e}${e.includes("?")?"&":"?"}w=${s}`}function H({src:e,sizes:s="100vw",maxWidth:r=2400,aspect:o,className:v,imgClassName:h,alt:g="",...f}){const[u,x]=c.useState(!1),[p,m]=c.useState(!1);c.useEffect(()=>{x(!1),m(!1)},[e]);const i=B.filter(l=>l<=r),b=i.map(l=>`${d(e,l)} ${l}w`).join(", ");return a.jsxs("div",{className:t("relative overflow-hidden bg-[hsl(var(--bg-subtle))]",v),style:o?{aspectRatio:o}:void 0,children:[!u&&!p&&a.jsx("img",{src:d(e,32),alt:"","aria-hidden":!0,className:t("absolute inset-0 size-full scale-110 object-cover blur-xl",h)}),p?a.jsx("div",{className:"grid size-full min-h-24 place-items-center text-xs text-[hsl(var(--text-muted))]",children:"image unavailable"}):a.jsx("img",{...f,alt:g,src:d(e,i[i.length-1]),srcSet:b,sizes:s,decoding:"async",onLoad:()=>x(!0),onError:()=>m(!0),className:t("relative block size-full transition-opacity duration-300",u?"opacity-100":"opacity-0",h)})]})}export{H as I,S as L,L as R,I as S,T,C as a,E as b,q as c};
