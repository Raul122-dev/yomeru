import{c as r,a as t,j as a,r as c}from"./index-CFAHLwg-.js";import{F as j}from"./badge-Bp-NO69P.js";import{X as k}from"./x-oPYRr-DJ.js";import{C as S}from"./trash-2-Bezbx-Bo.js";/**
 * @license lucide-react v0.441.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const N=r("Ban",[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["path",{d:"m4.9 4.9 14.2 14.2",key:"1m5liu"}]]);/**
 * @license lucide-react v0.441.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const w=r("Circle",[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}]]);/**
 * @license lucide-react v0.441.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const b=r("LoaderCircle",[["path",{d:"M21 12a9 9 0 1 1-6.219-8.56",key:"13zald"}]]);/**
 * @license lucide-react v0.441.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const L=r("RotateCcw",[["path",{d:"M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8",key:"1357e3"}],["path",{d:"M3 3v5h5",key:"1xhq8a"}]]);/**
 * @license lucide-react v0.441.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const T=r("TriangleAlert",[["path",{d:"m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3",key:"wmoenq"}],["path",{d:"M12 9v4",key:"juzpu7"}],["path",{d:"M12 17h.01",key:"p32p05"}]]),z={pending:"pending",running:"running",done:"done",partial:"partial",failed:"failed",stale:"outdated",cancelled:"cancelled"},A={partial:"Some pages failed or only some pages were run",stale:"An earlier phase changed after this one ran — run it again",cancelled:"Stopped before finishing"};function C({status:e,className:n}){const s=t("size-3.5 shrink-0",n);switch(e){case"done":return a.jsx(S,{className:t(s,"text-[hsl(var(--text))]"),strokeWidth:2.5});case"running":return a.jsx(b,{className:t(s,"animate-spin text-[hsl(var(--accent2))]")});case"failed":return a.jsx(k,{className:t(s,"text-[hsl(var(--danger))]"),strokeWidth:2.5});case"partial":return a.jsx(T,{className:t(s,"text-[hsl(var(--warning-deep))]")});case"stale":return a.jsx(L,{className:t(s,"text-[hsl(var(--warning-deep))]")});case"cancelled":return a.jsx(N,{className:t(s,"text-[hsl(var(--text-muted))]")});default:return a.jsx(w,{className:t(s,"text-[hsl(var(--text-faint))]")})}}function $({status:e}){return a.jsxs(j,{variant:e,title:A[e],children:[a.jsx(C,{status:e,className:"size-3"}),z[e]]})}const I=[160,320,640,1024,1600,2400];function o(e,n){return`${e}${e.includes("?")?"&":"?"}w=${n}`}function W({src:e,sizes:n="100vw",maxWidth:s=2400,aspect:d,className:f,imgClassName:u,alt:g="",...v}){const[h,m]=c.useState(!1),[p,x]=c.useState(!1);c.useEffect(()=>{m(!1),x(!1)},[e]);const i=I.filter(l=>l<=s),y=i.map(l=>`${o(e,l)} ${l}w`).join(", ");return a.jsxs("div",{className:t("relative overflow-hidden bg-[hsl(var(--bg-subtle))]",f),style:d?{aspectRatio:d}:void 0,children:[!h&&!p&&a.jsx("img",{src:o(e,32),alt:"","aria-hidden":!0,className:t("absolute inset-0 size-full scale-110 object-cover blur-xl",u)}),p?a.jsx("div",{className:"grid size-full min-h-24 place-items-center text-xs text-[hsl(var(--text-muted))]",children:"image unavailable"}):a.jsx("img",{...v,alt:g,src:o(e,i[i.length-1]),srcSet:y,sizes:n,decoding:"async",onLoad:()=>m(!0),onError:()=>x(!0),className:t("relative block size-full transition-opacity duration-300",h?"opacity-100":"opacity-0",u)})]})}export{W as I,b as L,L as R,C as S,T,z as a,A as b,$ as c};
