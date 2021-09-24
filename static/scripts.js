import{source as s,render as r}from'https://unpkg.com/@lcf.vs/dom-engine/lib/frontend.js';
const l=async({url},p)=>{const response=await fetch(new URL(p,url).toString());return{[s]:await response.text()}};
export{l,r,s};

export const a=(s,t=globalThis.document)=>[...t.querySelectorAll(s)];
export const o=(s,t=globalThis.document)=>t.querySelector(s);