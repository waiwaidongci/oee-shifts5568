import {request} from './client.js';
const PATHS=[['sources','/sources'],['periods','/periods'],['policies','/policies'],['runs','/runs'],
 ['schedules','/schedules'],['deliveries','/deliveries'],['audits','/audits'],
 ['measures','/improve/measures'],['improveruns','/improve/runs']];
export const loadAll=async()=>Object.fromEntries(await Promise.all(PATHS.map(async ([k,p])=>[k,await request(p)])));
export const saveSource=(data,id)=>request('/sources'+(id?'/'+id:''),id?'PUT':'POST',{data});
export const savePolicy=data=>request('/policies','POST',{data});
export const submitRun=data=>request('/runs','POST',data);
export const approveRun=(id,note)=>request('/runs/'+id+'/approve','POST',{note});
export const loadInventory=period=>request('/improve/inventory'+(period&&period!=='全部'?'?period='+encodeURIComponent(period):''));
export const saveMeasure=(data,id)=>request('/improve/measures'+(id?'/'+id:''),id?'PUT':'POST',data);
export const toggleMeasure=id=>request('/improve/measures/'+id+'/toggle','POST',{});
export const submitImprove=data=>request('/improve/runs','POST',data);
