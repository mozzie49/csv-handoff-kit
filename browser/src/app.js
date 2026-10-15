const MAX_INPUT_BYTES=10*1024*1024;
import {sampleCsv,sampleName} from './sample.js';
const $=id=>document.getElementById(id);
let selectedFile=null,worker=null,generation=0,downloadUrl=null;
function clearResult(){
 if(downloadUrl)URL.revokeObjectURL(downloadUrl);
 downloadUrl=null;$('result').hidden=true;$('download').removeAttribute('href');$('preview').replaceChildren();
}
function stop(){generation++;worker?.terminate();worker=null;$('cancel').hidden=true;$('convert').disabled=!selectedFile;}
function message(text,error=false){$('status').textContent=text;$('status').setAttribute('role',error?'alert':'status');$('status').classList.toggle('error',error);}
function selectFile(file){stop();clearResult();selectedFile=file;$('filename').textContent=file?`${file.name} · ${(file.size/1024).toFixed(1)} KiB`:'No file chosen';$('convert').disabled=!file;message(file?'Ready. Every column will be saved as text.':'Choose a UTF-8 CSV, or try the fictional sample.');}
function showPreview(rows){
 const table=document.createElement('table');
 for(let r=0;r<rows.length;r++){
  const tr=document.createElement('tr');
  for(const value of rows[r]){const cell=document.createElement(r===0?'th':'td');cell.textContent=value;if(r===0)cell.scope='col';tr.appendChild(cell);}
  table.appendChild(tr);
 }
 $('preview').replaceChildren(table);
}
async function convert(file){
 stop();clearResult();const id=generation;
 if(file.size>MAX_INPUT_BYTES){message('CSV exceeds 10 MiB. Split the source file.',true);return;}
 $('cancel').hidden=false;$('convert').disabled=true;message('Reading and converting locally…');
 const delimiter=$('delimiter').value;
 try{
  const buffer=await file.arrayBuffer();
  if(id!==generation)return;
  worker=new Worker(new URL('./worker.js',import.meta.url),{type:'module'});
  worker.onmessage=({data})=>{
   if(id!==generation)return;
   stop();
   if(!data.ok){message(data.error,true);return;}
   const blob=new Blob([data.output],{type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
   downloadUrl=URL.createObjectURL(blob);
   $('download').href=downloadUrl;
   const base=file.name.replace(/\.[^.]+$/,'').replace(/[^\p{L}\p{N}._-]/gu,'_').slice(0,70)||'handoff';
   $('download').download=`${base}-all-text.xlsx`;
   $('summary').textContent=`${data.rowCount-1} data row${data.rowCount===2?'':'s'} + header · ${data.columnCount} columns · every cell stored as text`;
   $('preview-note').textContent=`Preview shows up to 5 data rows and 6 columns, with long values shortened here only. The XLSX contains every accepted row, column, and full field value.`;
   showPreview(data.preview);$('result').hidden=false;message('Ready to download. Open the XLSX, not the original CSV.');$('download').focus();
  };
  worker.onerror=()=>{if(id===generation){stop();clearResult();message('The browser could not finish the conversion. No workbook was created. Try a smaller file or a current desktop browser.',true);}};
  worker.postMessage({buffer,delimiter},[buffer]);
 }catch{if(id===generation){stop();clearResult();message('The file could not be read or the conversion worker could not start. No workbook was created.',true);}}
}
$('file').addEventListener('change',event=>{selectFile(event.target.files?.[0]||null);});
$('delimiter').addEventListener('change',()=>{stop();clearResult();message('Separator changed. Convert again to use it.');});
$('convert').addEventListener('click',()=>{if(selectedFile)void convert(selectedFile);});
$('sample').addEventListener('click',()=>{
 $('file').value='';$('delimiter').value=',';
 const file=new File([sampleCsv],sampleName,{type:'text/csv;charset=utf-8'});
 selectFile(file);void convert(file);
});
$('cancel').addEventListener('click',()=>{stop();clearResult();message('Conversion cancelled. Nothing was downloaded.');});
$('clear').addEventListener('click',()=>{$('file').value='';selectFile(null);});
window.addEventListener('pagehide',()=>{stop();clearResult();});
