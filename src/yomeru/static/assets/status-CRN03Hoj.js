import{c as n,j as e,a as r}from"./index-Zk3AOcXJ.js";import{D as l}from"./button-i-qY6feV.js";import{X as d}from"./x-B8G7IiM6.js";import{C as c}from"./trash-2-CVqqBSJS.js";/**
 * @license lucide-react v0.441.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const i=n("Ban",[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["path",{d:"m4.9 4.9 14.2 14.2",key:"1m5liu"}]]);/**
 * @license lucide-react v0.441.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const o=n("Circle",[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}]]);/**
 * @license lucide-react v0.441.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const h=n("LoaderCircle",[["path",{d:"M21 12a9 9 0 1 1-6.219-8.56",key:"13zald"}]]);/**
 * @license lucide-react v0.441.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const x=n("RotateCcw",[["path",{d:"M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8",key:"1357e3"}],["path",{d:"M3 3v5h5",key:"1xhq8a"}]]);/**
 * @license lucide-react v0.441.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const p=n("TriangleAlert",[["path",{d:"m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3",key:"wmoenq"}],["path",{d:"M12 9v4",key:"juzpu7"}],["path",{d:"M12 17h.01",key:"p32p05"}]]),m=l("inline-flex items-center gap-1 rounded-[var(--radius-sm)] border px-1.5 py-px font-mono text-[11px] leading-4 font-medium uppercase tracking-wide",{variants:{variant:{default:"border-[hsl(var(--border))] text-[hsl(var(--text-muted))]",pending:"border-[hsl(var(--border))] text-[hsl(var(--text-muted))]",running:"border-[hsl(var(--accent2)/.45)] text-[hsl(var(--accent2))] bg-[hsl(var(--accent2-soft))]",done:"border-[hsl(var(--text)/.25)] text-[hsl(var(--text))]",partial:"border-[hsl(var(--warning)/.6)] text-[hsl(var(--warning-deep))]",stale:"border-[hsl(var(--warning)/.6)] text-[hsl(var(--warning-deep))] border-dashed",cancelled:"border-[hsl(var(--border-strong))] text-[hsl(var(--text-muted))] border-dashed",failed:"border-[hsl(var(--danger)/.45)] text-[hsl(var(--danger))]"}},defaultVariants:{variant:"default"}});function u({className:t,variant:s,...a}){return e.jsx("span",{className:r(m({variant:s}),t),...a})}const g={pending:"pending",running:"running",done:"done",partial:"partial",failed:"failed",stale:"outdated",cancelled:"cancelled"},v={partial:"Some pages failed or only some pages were run",stale:"An earlier phase changed after this one ran — run it again",cancelled:"Stopped before finishing"};function f({status:t,className:s}){const a=r("size-3.5 shrink-0",s);switch(t){case"done":return e.jsx(c,{className:r(a,"text-[hsl(var(--text))]"),strokeWidth:2.5});case"running":return e.jsx(h,{className:r(a,"animate-spin text-[hsl(var(--accent2))]")});case"failed":return e.jsx(d,{className:r(a,"text-[hsl(var(--danger))]"),strokeWidth:2.5});case"partial":return e.jsx(p,{className:r(a,"text-[hsl(var(--warning-deep))]")});case"stale":return e.jsx(x,{className:r(a,"text-[hsl(var(--warning-deep))]")});case"cancelled":return e.jsx(i,{className:r(a,"text-[hsl(var(--text-muted))]")});default:return e.jsx(o,{className:r(a,"text-[hsl(var(--text-faint))]")})}}function w({status:t}){return e.jsxs(u,{variant:t,title:v[t],children:[e.jsx(f,{status:t,className:"size-3"}),g[t]]})}export{h as L,x as R,f as S,p as T,g as a,v as b,w as c};
