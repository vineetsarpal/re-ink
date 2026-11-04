async (page) => {
  const base='http://127.0.0.1:4174';
  async function upload(scenario,docx=false) {
    await page.goto(base+'/?case='+scenario);
    const bytes=await (await page.request.get(base+(docx?'/original.docx':'/original.pdf'))).body();
    await page.locator('input[type="file"]').setInputFiles({name:docx?'synthetic.docx':'synthetic.pdf',mimeType:docx?'application/vnd.openxmlformats-officedocument.wordprocessingml.document':'application/pdf',buffer:bytes});
    await page.getByRole('button',{name:'Upload & Process'}).click();
  }
  await upload('pdf');
  await page.getByRole('heading',{name:'Review Extracted Data'}).waitFor();
  await page.getByRole('button',{name:'Source · p.1',exact:true}).click();
  await page.getByText('Page 1 / 1',{exact:true}).waitFor();
  await page.locator('canvas.doc-preview__canvas').waitFor({state:'visible'});
  await page.locator('.doc-box--active').waitFor({state:'visible'});
  await upload('missing');
  await page.getByRole('heading',{name:'Review Extracted Data'}).waitFor();
  if(await page.getByLabel('Currency *',{exact:true}).inputValue()!=='')throw Error('Unknown currency was defaulted');
  if(await page.getByRole('combobox').first().inputValue()!=='')throw Error('Unknown role was defaulted');
  await page.getByText('No source evidence available for this extraction — verify fields manually.',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Edit Mode'}).click();
  await page.getByLabel('Currency *',{exact:true}).fill('CAD');
  await page.getByRole('combobox').first().selectOption('cedant');
  page.once('dialog',d=>d.accept());
  await page.getByRole('button',{name:'Approve & Create'}).click();
  await page.waitForURL('**/contracts/123');
  const approved=await page.evaluate(()=>window.fixture.approval);
  if(approved.contract.currency!=='CAD'||approved.parties[0].role!=='cedant')throw Error('Corrections not preserved');
  await upload('docx',true);
  await page.getByRole('heading',{name:'Review Extracted Data'}).waitFor();
  const downloadPromise=page.waitForEvent('download');
  await page.getByRole('button',{name:'Download original DOCX'}).click();
  await (await downloadPromise).delete();
  if(await page.locator('canvas').count())throw Error('DOCX received a fabricated inline preview');
  if(await page.evaluate(()=>window.fixture.downloads)!==1)throw Error('DOCX original not fetched');
  await upload('timeout');
  await page.getByRole('heading',{name:'Extraction timed out',exact:true}).waitFor();
  const polls=await page.evaluate(()=>window.fixture.polls);
  await page.waitForTimeout(3500);
  if(await page.evaluate(()=>window.fixture.polls)!==polls)throw Error('Terminal state kept polling');
  await page.getByRole('button',{name:'Retry extraction'}).click();
  await page.getByRole('heading',{name:'Review Extracted Data'}).waitFor();
  await page.goto(base+'/?viewer=1');
  await page.getByText('Document uploads are currently unavailable.',{exact:true}).waitFor();
  if(await page.locator('input[type="file"]').count())throw Error('Viewer can select upload');
  await page.evaluate(()=>{window.fixtureUiChecksPassed=true;});
  return 'Fixture UI checks passed: PDF preview/highlight, missing evidence/currency/role, corrections+approval, DOCX download/no preview, timeout polling+Retry, viewer upload gate';
}
