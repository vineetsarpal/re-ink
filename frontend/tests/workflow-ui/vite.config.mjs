import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {readFileSync} from 'node:fs';
const here=path.dirname(fileURLToPath(import.meta.url));
const frontend=path.resolve(here,'../..');
const corpus=path.resolve(frontend,'../backend/tests/corpus');
export default {
  root:here,envDir:here,
  plugins:[{name:'explicit-corpus-fixtures',configureServer(server){server.middlewares.use((req,res,next)=>{
    const file={'/original.pdf':'ordinary.pdf','/original.docx':'docx.docx'}[req.url?.split('?')[0]];
    if(!file)return next();
    res.setHeader('Content-Type',file.endsWith('.pdf')?'application/pdf':'application/vnd.openxmlformats-officedocument.wordprocessingml.document');
    res.end(readFileSync(path.join(corpus,file)));
  });}}],
  resolve:{alias:{'@':path.join(frontend,'src'),'@workos-inc/authkit-react':path.join(here,'mock-auth.js')}},
  server:{host:'127.0.0.1',port:4174,strictPort:true,fs:{allow:[frontend,path.resolve(frontend,'../backend/tests/corpus')]}}
};
