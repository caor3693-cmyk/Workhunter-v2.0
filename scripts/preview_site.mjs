import http from 'node:http';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const module = await import(pathToFileURL(path.resolve('dist/server/index.js')));
const worker = module.default;
const localOnly = process.env.WH_PREVIEW_LOCAL === '1';
const env = {WH_API_ORIGIN:process.env.WH_API_ORIGIN, WH_API_SERVICE_TOKEN:readFileSync('.runtime/service-token','utf8').trim()};
const port = Number(process.env.WH_PREVIEW_PORT || 8767);
const server = http.createServer(async (req,res)=> {
  try {
    const request = new Request('http://127.0.0.1:' + port + req.url, {method:req.method});
    const url = new URL(request.url);
    const response = localOnly && module.isPublicPath(url.pathname) && req.method === 'GET'
      ? await fetch(new URL(url.pathname + url.search,'http://127.0.0.1:8766'),{headers:{Authorization:'Bearer ' + env.WH_API_SERVICE_TOKEN},redirect:'manual'})
      : await worker.fetch(request,env);
    res.writeHead(response.status,Object.fromEntries(response.headers));
    res.end(Buffer.from(await response.arrayBuffer()));
  } catch {res.writeHead(502,{'Content-Type':'application/json'});res.end(JSON.stringify({error:{code:'local_api_unavailable',message:'本机开发服务不可用，请重新加载。'}}));}
});
server.listen(port,'127.0.0.1',()=>console.log('Local preview: http://127.0.0.1:' + port));
