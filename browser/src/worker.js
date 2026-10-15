import {convertCsv,InputError} from './convert.js';
self.onmessage=({data})=>{
 try{
  const result=convertCsv(new Uint8Array(data.buffer),data.delimiter);
  self.postMessage({ok:true,...result},[result.output.buffer]);
 }catch(error){self.postMessage({ok:false,error:error instanceof InputError?error.message:'Conversion failed. No workbook was created. Try a smaller valid UTF-8 CSV.'});}
};
