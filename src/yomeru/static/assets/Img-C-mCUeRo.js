import{c as i,a as t,j as a,r as c}from"./index-DKmUj7rH.js";import{K as w}from"./badge-CkOakEEa.js";import{X as T}from"./x-rmtLyxiB.js";import{C as b}from"./trash-2-Oo-Tr3qN.js";/**
 * @license lucide-react v0.441.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const A=i("Ban",[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["path",{d:"m4.9 4.9 14.2 14.2",key:"1m5liu"}]]);/**
 * @license lucide-react v0.441.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const L=i("Circle",[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}]]);/**
 * @license lucide-react v0.441.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const z=i("LoaderCircle",[["path",{d:"M21 12a9 9 0 1 1-6.219-8.56",key:"13zald"}]]);/**
 * @license lucide-react v0.441.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const E=i("RotateCcw",[["path",{d:"M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8",key:"1357e3"}],["path",{d:"M3 3v5h5",key:"1xhq8a"}]]);/**
 * @license lucide-react v0.441.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const $=i("TriangleAlert",[["path",{d:"m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3",key:"wmoenq"}],["path",{d:"M12 9v4",key:"juzpu7"}],["path",{d:"M12 17h.01",key:"p32p05"}]]),C={pending:"pending",running:"running",done:"done",partial:"partial",failed:"failed",stale:"outdated",cancelled:"cancelled"},I={partial:"Some pages failed or only some pages were run",stale:"An earlier phase changed after this one ran — run it again",cancelled:"Stopped before finishing"};function R({status:e,className:r}){const s=t("size-3.5 shrink-0",r);switch(e){case"done":return a.jsx(b,{className:t(s,"text-[hsl(var(--text))]"),strokeWidth:2.5});case"running":return a.jsx(z,{className:t(s,"animate-spin text-[hsl(var(--accent2))]")});case"failed":return a.jsx(T,{className:t(s,"text-[hsl(var(--danger))]"),strokeWidth:2.5});case"partial":return a.jsx($,{className:t(s,"text-[hsl(var(--warning-deep))]")});case"stale":return a.jsx(E,{className:t(s,"text-[hsl(var(--warning-deep))]")});case"cancelled":return a.jsx(A,{className:t(s,"text-[hsl(var(--text-muted))]")});default:return a.jsx(L,{className:t(s,"text-[hsl(var(--text-faint))]")})}}function U({status:e}){return a.jsxs(w,{variant:e,title:I[e],children:[a.jsx(R,{status:e,className:"size-3"}),C[e]]})}const M=[160,320,640,1024,1600,2400],B=2;function d(e,r){return`${e}${e.includes("?")?"&":"?"}w=${r}`}function X({src:e,sizes:r="100vw",maxWidth:s=2400,aspect:u,className:y,imgClassName:m,alt:j="",...k}){const[p,h]=c.useState(!1),[x,f]=c.useState(!1),[l,g]=c.useState(0);c.useEffect(()=>{h(!1),f(!1),g(0)},[e]);const S=()=>{if(l>=B)return f(!0);setTimeout(()=>g(n=>n+1),800*2**l)},v=l?`${e}${e.includes("?")?"&":"?"}retry=${l}`:e,o=M.filter(n=>n<=s),N=o.map(n=>`${d(v,n)} ${n}w`).join(", ");return a.jsxs("div",{className:t("relative overflow-hidden bg-[hsl(var(--bg-subtle))]",y),style:u?{aspectRatio:u}:void 0,children:[!p&&!x&&a.jsx("img",{src:d(e,32),alt:"","aria-hidden":!0,className:t("absolute inset-0 size-full scale-110 object-cover blur-xl",m)}),x?a.jsx("div",{className:"grid size-full min-h-24 place-items-center text-xs text-[hsl(var(--text-muted))]",children:"image unavailable"}):c.createElement("img",{...k,alt:j,key:l,src:d(v,o[o.length-1]),srcSet:N,sizes:r,decoding:"async",onLoad:()=>h(!0),onError:S,className:t("relative block size-full transition-opacity duration-300",p?"opacity-100":"opacity-0",m)})]})}export{X as I,z as L,E as R,R as S,$ as T,C as a,I as b,U as c};
