import {test} from 'node:test';
import assert from 'node:assert/strict';
import {unzipSync,strFromU8} from 'fflate';
import {parseCsv,buildXlsx,convertCsv,xmlText,checkText,LIMITS,InputError} from '../src/convert.js';
import {sampleCsv} from '../src/sample.js';
const bytes=text=>new TextEncoder().encode(text);
const parse=(text,delimiter)=>parseCsv(bytes(text),delimiter);
const reject=(text,pattern=/./)=>assert.throws(()=>parse(text),pattern);

test('fictional sample preserves Bengali, IDs, formula text, quoted comma/quotes/CRLF',()=>{
 const rows=parse(sampleCsv);
 assert.equal(rows.length,4);assert.equal(rows[1][0],'নমুনা ব্যক্তি');
 assert.deepEqual(rows[1].slice(1,5),['76E9','00000123456','12345678901234567890','=1+1']);
 assert.equal(rows[1][5],'Fictional sample, not a real contact');
 assert.equal(rows[2][5],'Quoted "words" stay intact');assert.equal(rows[3][5],'First line\r\nSecond line');
});
test('exact UTF8 including one BOM removed, second/internal BOM retained',()=>{
 assert.deepEqual(parse('\ufeffName\na'),[['Name'],['a']]);
 assert.deepEqual(parse('\ufeff\ufeffName\na\ufeffb'),[['\ufeffName'],['a\ufeffb']]);
 assert.deepEqual(parse('h\né\né\n😀\n中文\nবাংলা\n\u2028\u2029'),[['h'],['é'],['é'],['😀'],['中文'],['বাংলা'],['\u2028\u2029']]);
});
for(const [label,input] of Object.entries({utf16:[255,254,65,0],continuation:[128],truncated:[0xe2,0x82],overlong:[0xc0,0xaf],surrogate:[0xed,0xa0,0x80]}))test(`reject invalid UTF8: ${label}`,()=>assert.throws(()=>parseCsv(new Uint8Array(input)),/UTF-8/));
test('mixed outer endings and quoted line endings remain exact',()=>assert.deepEqual(parse('a,b\r\n1,"x\ry\nz\r\nw"\n2,3\r4,5'),[['a','b'],['1','x\ry\nz\r\nw'],['2','3'],['4','5']]));
test('empty quoted values, whitespace, comments, and terminal newline remain exact',()=>{
 assert.deepEqual(parse('h\n""\n  x  \n#comment\n"a\n\nb"\n'),[['h'],[''],['  x  '],['#comment'],['a\n\nb']]);
 assert.deepEqual(parse('a,b\nx,\n'),[['a','b'],['x','']]);
});
for(const bad of ['h\n\n','h\r\n\r\n','h\r\r','h\n"x','h\nfoo"bar','h\n"x"suffix','h\n "x"','h\n"x" ','h\n"x\\"y"','a,b\n1\n','a,b\n1,2,3\n'])test(`reject malformed ${JSON.stringify(bad)}`,()=>reject(bad));
test('empty, duplicate and missing headers fail closed',()=>{for(const text of ['', '\ufeff','a,a\n1,2',',b\n1,2','""\n1'])reject(text);});
test('explicit separator choices, never guessed',()=>{
 for(const d of [';', '\t','|'])assert.deepEqual(parse(`a${d}b\n001${d}76E9`,d),[['a','b'],['001','76E9']]);
 assert.deepEqual(parse('a;b\n1;2'),[['a;b'],['1;2']]);
 assert.throws(()=>parse('a\nb',':'),/separator/);
});
test('control characters and lone surrogates rejected, valid whitespace/emoji allowed',()=>{
 for(const c of ['\0','\x01','\x0b','\ufffe','\uffff'])reject(`h\n"a${c}b"`,/control/);
 assert.throws(()=>checkText('\ud800'),/surrogate/);assert.throws(()=>checkText('\udfff'),/surrogate/);
 assert.equal(checkText('\t\r\n😀'),'\t\r\n😀');
});
test('field size uses UTF16 units, not aggregate row length',()=>{
 assert.equal(parse('a,b\n'+'x'.repeat(20000)+','+'y'.repeat(20000))[1][0].length,20000);
 assert.equal(checkText('x'.repeat(32767)).length,32767);
 assert.equal(checkText('😀'.repeat(16383)+'x').length,32767);
 assert.throws(()=>checkText('😀'.repeat(16383)+'xy'),/32,767/);
 reject('h\n'+'x'.repeat(32768),/32,767/);
});
test('row limits include header',()=>{
 assert.equal(parse('h\n'+'x\n'.repeat(9999)).length,10000);
 reject('h\n'+'x\n'.repeat(10000),/10,000/);
});
test('column cap enforced during field emission, including a comma storm',()=>{
 const headers=Array.from({length:256},(_,i)=>`c${i}`).join(',');
 assert.equal(parse(headers)[0].length,256);
 reject(headers+',extra',/256/);reject(','.repeat(1024*1024),/256/);
});
test('250,000-cell budget includes headers',()=>{
 const header=Array.from({length:25},(_,i)=>`c${i}`).join(',')+'\n';
 const row=Array(25).fill('x').join(',')+'\n';
 assert.equal(parse(header+row.repeat(9999)).length*25,250000);
 const header26=Array.from({length:26},(_,i)=>`c${i}`).join(',')+'\n';
 reject(header26+(Array(26).fill('x').join(',')+'\n').repeat(9615),/250,000/);
});
test('10MiB input accepted at boundary and +1 byte rejected before parsing',()=>{
 const prefix='h\n';const chunks=[];let remaining=LIMITS.bytes-prefix.length;
 while(remaining){const n=Math.min(32767,remaining-1);if(n<0){chunks.push('x');break;}chunks.push('x'.repeat(n)+'\n');remaining-=n+1;}
 const exact=prefix+chunks.join('');assert.equal(bytes(exact).length,LIMITS.bytes);assert.ok(parse(exact).length>1);
 assert.throws(()=>parseCsv(new Uint8Array(LIMITS.bytes+1)),/10 MiB/);
});
test('OOXML overlapping escape-like sequences and CR are escaped before XML',()=>{
 assert.equal(xmlText('_x005F_x0041_'),'_x005F_x005F_x005F_x0041_');
 assert.equal(xmlText('_x0041__x0042_'),'_x005F_x0041__x005F_x0042_');
 assert.equal(xmlText('<&>\r\n'),'&lt;&amp;&gt;&#13;\n');
});
test('all fields use inline strings and text formats, without formulas or external links',()=>{
 const values=['00123','76E9','123456789012345678901234567890','SEPT2','=1+1','+SUM(A1)','-1','@x',' =1','\t=1','=HYPERLINK("https://example.invalid","x")',''];
 const zip=unzipSync(buildXlsx([['value'],...values.map(x=>[x])]));
 assert.deepEqual(Object.keys(zip).sort(),['[Content_Types].xml','_rels/.rels','xl/_rels/workbook.xml.rels','xl/styles.xml','xl/workbook.xml','xl/worksheets/sheet1.xml']);
 const sheet=strFromU8(zip['xl/worksheets/sheet1.xml']);
 assert.equal((sheet.match(/t="inlineStr"/g)||[]).length,values.length+1);
 assert.doesNotMatch(sheet,/<f(?:\s|>)/);assert.doesNotMatch(sheet,/<hyperlinks/);
 assert.doesNotMatch(strFromU8(zip['xl/_rels/workbook.xml.rels']),/TargetMode|https:\/\//);
 assert.match(strFromU8(zip['xl/styles.xml']),/numFmtId="49"/);
});
test('untrusted HTML is only XML text; unpaired/ragged builder inputs reject',()=>{
 const sheet=strFromU8(unzipSync(buildXlsx([['h'],['<script>alert(1)</script>']]))['xl/worksheets/sheet1.xml']);
 assert.match(sheet,/&lt;script&gt;/);assert.doesNotMatch(sheet,/<script/);
 assert.throws(()=>buildXlsx([['h'],['a','b']]),/width/);
 assert.throws(()=>buildXlsx([['h'],['\ud800']]),/surrogate/);
});
test('workbook expansion limit fails closed',()=>{
 const row='&'.repeat(30000);
 assert.throws(()=>buildXlsx([['h'],...Array.from({length:150},()=>[row])]),/20 MiB/);
});
test('preview is bounded, full workbook still contains full fields',()=>{
 const value='x'.repeat(120);const input='h\n'+Array(12).fill(value).join('\n');
 const result=convertCsv(bytes(input));assert.equal(result.preview.length,6);assert.equal(result.preview[1][0].length,100);
 assert.equal(result.rowCount,13);assert.ok(strFromU8(unzipSync(result.output)['xl/worksheets/sheet1.xml']).includes(value));
});
