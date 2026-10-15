import {parse} from 'csv-parse/browser/esm/sync';
import {zipSync, strToU8, deflateSync} from 'fflate';
import {staticParts} from './xlsx-parts.js';

export const LIMITS=Object.freeze({bytes:10*1024*1024,rows:10000,columns:256,cells:250000,cellUnits:32767,part:20*1024*1024,total:40*1024*1024});
export class InputError extends Error {}
const requireInput=(condition,message)=>{if(!condition)throw new InputError(message);};
export function checkText(value){
 requireInput(typeof value==='string','Every value must be text.');
 requireInput(value.length<=LIMITS.cellUnits,'A field exceeds 32,767 UTF-16 code units. Split or shorten the source.');
 // Iterate code points: paired surrogates are valid Unicode, lone surrogates are not.
 for(const char of value){const n=char.codePointAt(0);requireInput(!((n<32&&n!==9&&n!==10&&n!==13)||(n>=0xd800&&n<=0xdfff)||n===0xfffe||n===0xffff),'Unsupported control or surrogate character in CSV.');}
 return value;
}
export function parseCsv(bytes,delimiter=','){
 requireInput(bytes instanceof Uint8Array,'Expected CSV file bytes.');
 requireInput(bytes.byteLength<=LIMITS.bytes,'CSV exceeds 10 MiB. Split the source file.');
 requireInput([',',';','\t','|'].includes(delimiter),'Choose comma, semicolon, tab, or pipe as the separator.');
 let text;
 try{text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);}catch{throw new InputError('CSV must be valid UTF-8. An initial UTF-8 BOM is allowed.');}
 let rowCount=0,cellCount=0,headers;
 try{
  const rows=parse(text,{
   bom:false,cast:(value,context)=>{requireInput(context.index<LIMITS.columns,'CSV exceeds 256 columns.');return checkText(value);},columns:false,delimiter,quote:'"',escape:'"',
   record_delimiter:['\r\n','\n','\r'],relax_quotes:false,relax_column_count:false,
   skip_empty_lines:false,skip_records_with_error:false,trim:false,raw:true,
   max_record_size:LIMITS.bytes,
   on_record({record,raw}){
    requireInput(++rowCount<=LIMITS.rows,'CSV exceeds 10,000 rows including the header.');
    requireInput(record.length<=LIMITS.columns,'CSV exceeds 256 columns.');
    requireInput((cellCount+=record.length)<=LIMITS.cells,'CSV exceeds 250,000 cells.');
    requireInput(!/^(?:\r\n|\n|\r)$/.test(raw),'Blank lines are not supported. Quote an intentional empty field as "".');
    record.forEach(checkText);
    if(!headers){headers=record;requireInput(headers.every(Boolean)&&new Set(headers).size===headers.length,'Header names must be nonempty and unique.');}
    return record;
   }
  });
  requireInput(rows.length>0,'CSV must contain a nonempty header row.');
  return rows;
 }catch(error){
  if(error instanceof InputError)throw error;
  const line=Number.isSafeInteger(error.lines)?` near line ${error.lines}`:'';
  throw new InputError(`Malformed CSV${line}. Use the selected separator, double quoted fields, doubled quotes inside fields, and the same column count on every row.`);
 }
}
export function xmlText(value){
 return value.replace(/_(?=x[0-9a-fA-F]{4}_)/g,'_x005F_').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\r/g,'&#13;');
}
function columnName(index){let name='';for(;index;index=Math.floor((index-1)/26))name=String.fromCharCode(65+(index-1)%26)+name;return name;}
export function buildXlsx(rows){
 requireInput(Array.isArray(rows)&&rows.length>0&&rows.length<=LIMITS.rows,'Invalid row count.');
 const width=rows[0].length;
 requireInput(width>0&&width<=LIMITS.columns&&rows.length*width<=LIMITS.cells,'Invalid column or cell count.');
 requireInput(rows[0].every(Boolean)&&new Set(rows[0]).size===width,'Header names must be nonempty and unique.');
 const chunks=[];let byteCount=0;
 const append=part=>{byteCount+=strToU8(part).length;requireInput(byteCount<=LIMITS.part,'Generated worksheet exceeds 20 MiB. Split the source.');chunks.push(part);};
 append('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">');
 append(`<dimension ref="A1:${columnName(width)}${rows.length}"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><sheetFormatPr defaultRowHeight="18"/><cols>`);
 for(let c=0;c<width;c++){
  let longest=14;
  for(const row of rows){requireInput(Array.isArray(row)&&row.length===width,'Every row must match the header width.');checkText(row[c]);longest=Math.max(longest,Math.min(48,Array.from(row[c]).length+2));}
  append(`<col min="${c+1}" max="${c+1}" width="${longest}" customWidth="1"/>`);
 }
 append('</cols><sheetData>');
 rows.forEach((row,r)=>{
  append(`<row r="${r+1}">`);
  row.forEach((value,c)=>append(`<c r="${columnName(c+1)}${r+1}" t="inlineStr" s="${r===0?3:1}"><is><t xml:space="preserve">${xmlText(value)}</t></is></c>`));
  append('</row>');
 });
 append('</sheetData></worksheet>');
 const parts={...staticParts,'xl/worksheets/sheet1.xml':chunks.join('')};
 const files={};let total=0;
 for(const [name,text] of Object.entries(parts)){
  const data=strToU8(text);total+=data.length;
  requireInput(data.length<=LIMITS.part&&total<=LIMITS.total,'Generated workbook exceeds the expanded-size limits. Split the source.');
  // Avoid producing an extreme-ratio package, even for highly repetitive CSVs.
  const compressed=deflateSync(data,{level:6});
  const level=data.length/Math.max(compressed.length,1)>1000?0:6;
  files[name]=[data,{level,mtime:new Date(1980,0,1)}];
 }
 const output=zipSync(files);
 requireInput(output.length<=LIMITS.bytes,'Generated XLSX exceeds 10 MiB. Split the source.');
 return output;
}
export function convertCsv(bytes,delimiter=','){
 const rows=parseCsv(bytes,delimiter);
 const output=buildXlsx(rows);
 return {output,rowCount:rows.length,columnCount:rows[0].length,preview:rows.slice(0,6).map(row=>row.slice(0,6).map(value=>Array.from(value).slice(0,100).join('')))};
}
