import {test,expect} from '@playwright/test';
import {readFile} from 'node:fs/promises';
import {unzipSync,strFromU8} from 'fflate';
const upload=(page,name,contents)=>page.locator('#file').setInputFiles({name,mimeType:'text/csv',buffer:Buffer.from(contents)});

test('one-click sample, all-text download, no processing requests, mobile layout',async({page,context})=>{
 const requests=[],errors=[];context.on('request',request=>requests.push({url:request.url(),method:request.method()}));page.on('pageerror',error=>errors.push(error.message));
 await page.goto('/');await expect(page.locator('#convert')).toBeDisabled();
 await page.getByRole('button',{name:'Try a fictional sample'}).click();
 await expect(page.locator('#result')).toBeVisible();
 await expect(page.locator('#summary')).toContainText('3 data rows + header · 6 columns');
 await expect(page.locator('#preview')).toContainText('নমুনা ব্যক্তি');
 await expect(page.locator('#preview')).toContainText('76E9');
 const pending=page.waitForEvent('download');await page.locator('#download').click();const download=await pending;
 expect(download.suggestedFilename()).toBe('fictional-records-all-text.xlsx');
 await download.saveAs('test-results/browser-sample.xlsx');
 const zip=unzipSync(new Uint8Array(await readFile(await download.path()))),sheet=strFromU8(zip['xl/worksheets/sheet1.xml']);
 expect(sheet).toContain('00000123456');expect(sheet).toContain('12345678901234567890');expect(sheet).toContain('=1+1');expect(sheet).not.toMatch(/<f(?:\s|>)/);
 expect((sheet.match(/t="inlineStr"/g)||[]).length).toBe(24);
 expect(requests.every(r=>r.method==='GET'&&r.url.startsWith('http://127.0.0.1:4175/'))).toBe(true);
 expect(requests.filter(r=>!/(?:\/$|\/style\.css$|\/assets\/(?:app|worker)\.js$)/.test(r.url))).toEqual([]);
 expect(await page.evaluate(()=>Object.keys(localStorage))).toEqual([]);expect(await page.evaluate(()=>Object.keys(sessionStorage))).toEqual([]);
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:'test-results/browser-sample-mobile.png',fullPage:true});
 expect(errors).toEqual([]);
});

test('valid → malformed/oversized input clears stale output; exact separator; HTML-safe preview',async({page})=>{
 await page.goto('/');await page.locator('#sample').click();await expect(page.locator('#result')).toBeVisible();
 await upload(page,'malformed.csv','a,b\n"not closed');await expect(page.locator('#result')).toBeHidden();
 await page.locator('#convert').click();await expect(page.locator('#status')).toContainText('Malformed CSV');await expect(page.locator('#download')).not.toHaveAttribute('href');
 await upload(page,'large.csv',Buffer.alloc(10*1024*1024+1));await page.locator('#convert').click();await expect(page.locator('#status')).toContainText('exceeds 10 MiB');
 await upload(page,'safe.csv','h;value\n001;<img src=x onerror=alert(1)>');await page.locator('#delimiter').selectOption(';');await page.locator('#convert').click();
 await expect(page.locator('#result')).toBeVisible();await expect(page.locator('#preview')).toContainText('<img src=x onerror=alert(1)>');await expect(page.locator('#preview img')).toHaveCount(0);
 await page.locator('#delimiter').selectOption(',');await expect(page.locator('#result')).toBeHidden();await expect(page.locator('#download')).not.toHaveAttribute('href');
 await page.locator('#clear').click();await expect(page.locator('#convert')).toBeDisabled();
});

test('cancel, in-flight replacement, repeated sample and reload cannot expose stale results',async({page})=>{
 await page.goto('/');
 const holdWorker=async()=>{
  let release,entered=false;const gate=new Promise(resolve=>{release=resolve;});
  await page.route('**/assets/worker.js',async route=>{entered=true;await gate;await route.continue().catch(()=>{});});
  return {release,entered:()=>entered};
 };
 // Verify a worker request actually enters the gate before cancelling it.
 const cancelled=await holdWorker();
 try{
  await page.locator('#sample').click();await expect.poll(cancelled.entered).toBe(true);
  await page.locator('#cancel').click();
  await expect(page.locator('#status')).toContainText('cancelled');await expect(page.locator('#result')).toBeHidden();
 }finally{cancelled.release();}
 await page.unrouteAll({behavior:'wait'});
 // Replace an in-flight sample job before its worker script can run.
 const stale=await holdWorker();
 try{
  await page.locator('#sample').click();await expect.poll(stale.entered).toBe(true);
  await upload(page,'replacement.csv','Identifier\n00077');
  await expect(page.locator('#filename')).toContainText('replacement.csv');await expect(page.locator('#result')).toBeHidden();
 }finally{stale.release();}
 await page.unrouteAll({behavior:'wait'});
 await page.locator('#convert').click();await expect(page.locator('#result')).toBeVisible();
 await expect(page.locator('#preview')).toContainText('00077');await expect(page.locator('#preview')).not.toContainText('76E9');
 await expect(page.locator('#download')).toHaveAttribute('download','replacement-all-text.xlsx');
 await page.locator('#sample').click();await expect(page.locator('#result')).toBeVisible();await expect(page.locator('#preview')).not.toContainText('00077');
 await page.reload();await expect(page.locator('#result')).toBeHidden();await expect(page.locator('#convert')).toBeDisabled();
 await page.locator('#sample').click();await expect(page.locator('#result')).toBeVisible();
 await page.setViewportSize({width:1280,height:900});await page.screenshot({path:'test-results/browser-sample-desktop.png',fullPage:true});
});

// A project Pages-style subdirectory must resolve both script and worker relatively.
test('static build works under a project subdirectory',async({page,context})=>{
 await context.route('**/project-trial/**',async route=>{
  const url=new URL(route.request().url());url.pathname=url.pathname.replace('/project-trial/','/');
  const response=await route.fetch({url:url.href});await route.fulfill({response});
 });
 await page.goto('/project-trial/');await page.locator('#sample').click();
 await expect(page.locator('#result')).toBeVisible();await expect(page.locator('#preview')).toContainText('76E9');
});

test('pending file reads can be cancelled and superseded object URLs are revoked',async({page})=>{
 await page.addInitScript(()=>{
  const read=File.prototype.arrayBuffer;
  File.prototype.arrayBuffer=function(){
   if(this.name!=='deferred.csv')return read.call(this);
   window.__readPending=true;
   return new Promise(resolve=>{window.__releaseRead=()=>{window.__readPending=false;resolve(read.call(this));};});
  };
  const create=URL.createObjectURL.bind(URL),revoke=URL.revokeObjectURL.bind(URL);
  window.__urls={created:[],revoked:[]};
  URL.createObjectURL=blob=>{const url=create(blob);window.__urls.created.push(url);return url;};
  URL.revokeObjectURL=url=>{window.__urls.revoked.push(url);revoke(url);};
 });
 await page.goto('/');await upload(page,'deferred.csv','ID\n00001');await page.locator('#convert').click();
 await expect.poll(()=>page.evaluate(()=>window.__readPending)).toBe(true);
 await page.locator('#cancel').click();await page.evaluate(()=>window.__releaseRead());
 await expect(page.locator('#status')).toContainText('cancelled');await expect(page.locator('#result')).toBeHidden();
 await page.locator('#sample').click();await expect(page.locator('#result')).toBeVisible();
 const firstUrl=await page.locator('#download').getAttribute('href');
 const download1=page.waitForEvent('download');await page.locator('#download').click();await download1;
 const download2=page.waitForEvent('download');await page.locator('#download').click();await download2;
 expect(await page.evaluate(()=>window.__urls.created.length)).toBe(1);
 await page.locator('#sample').click();await expect(page.locator('#result')).toBeVisible();
 expect(await page.evaluate(()=>window.__urls.revoked)).toContain(firstUrl);
 const secondUrl=await page.locator('#download').getAttribute('href');expect(secondUrl).not.toBe(firstUrl);
 await page.locator('#clear').click();expect(await page.evaluate(()=>window.__urls.revoked)).toContain(secondUrl);
 await expect(page.locator('#result')).toBeHidden();
});
