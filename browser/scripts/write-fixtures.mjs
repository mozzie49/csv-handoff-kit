import {mkdir,writeFile} from 'node:fs/promises';
import {convertCsv} from '../src/convert.js';
import {sampleCsv} from '../src/sample.js';
await mkdir('.fixtures',{recursive:true});
const edgeRows=[['Value','Description'],
 ['00123','Leading zeros'],['76E9','Scientific-looking ID'],['123456789012345678901234567890','Long ID'],
 ['বাংলা 中文 😀','Unicode'],['é','Composed'],['é','Decomposed'],['','Empty'],['  x  ','Whitespace'],
 ['=1+1','Literal formula'],['+SUM(A1)','Literal plus'],['-1','Literal minus'],['@x','Literal at'],['\t=1','Literal tab formula'],
 ['=HYPERLINK("https://example.invalid","x")','No hyperlink'],
 ['_x0041_','Escape-looking'],['_x000D_','Escape-looking CR'],['_x005F_','Escape-looking underscore'],
 ['_x005F_x0041_','Overlapping escapes'],['_x0041_x0042_','Shared underscore'],['_x0041__x0042_','Adjacent escapes'],
 ['a\rb\nc\r\nd','Exact CR LF CRLF'],['<script>&"\'','XML metacharacters'],['\ufeff','Internal BOM'],['\u2028\u2029','Unicode separators']];
const edgeCsv=edgeRows.map(row=>row.map(value=>'"'+value.replaceAll('"','""')+'"').join(',')).join('\r\n');
const sampleRows=[
 ['Name','Identifier','Phone-like text','Long ID','Literal formula','Notes'],
 ['নমুনা ব্যক্তি','76E9','00000123456','12345678901234567890','=1+1','Fictional sample, not a real contact'],
 ['示例用户','00123','00000987654','98765432109876543210','+SUM(1;2)','Quoted "words" stay intact'],
 ['Example Ω','SEPT2','00000000000','00000000000000000001','@example','First line\r\nSecond line']
];
for(const [name,csv,rows] of [['fictional-sample',sampleCsv,sampleRows],['edge-values',edgeCsv,edgeRows]]){
 const bytes=new TextEncoder().encode(csv),result=convertCsv(bytes);
 await writeFile(`.fixtures/${name}.csv`,bytes);await writeFile(`.fixtures/${name}.xlsx`,result.output);
 await writeFile(`.fixtures/${name}.json`,JSON.stringify(rows));
}
console.log('Wrote two synthetic fixtures for independent readback.');
