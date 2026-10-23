/**
 * Cloudflare Worker - mydata 反向代理
 * 
 * 这是备用方案：如果 Zero Trust 公共主机名方式行不通，
 * 请将此代码更新到你的 mydata Worker 中。
 * 
 * 部署步骤:
 * 1. 打开 https://dash.cloudflare.com/
 * 2. Workers & Pages -> mydata -> 编辑代码
 * 3. 替换为以下代码（将 TUNNEL_UUID_HERE 替换为实际隧道 ID）
 * 4. 部署
 */

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    
    // 改成你的隧道 ID（可以在 config.yml 中找到）
    const TUNNEL_ID = '0fc7e3be-84c0-4a12-b549-c038ed1d0fc0';
    const tunnelUrl = `https://${TUNNEL_ID}.cfargotunnel.com`;
    
    // 构造代理 URL
    const proxyUrl = tunnelUrl + url.pathname + url.search;
    
    // 转发原始请求
    const modifiedRequest = new Request(proxyUrl, {
      method: request.method,
      headers: request.headers,
      body: request.method !== 'GET' && request.method !== 'HEAD' 
        ? request.body 
        : undefined,
      redirect: 'follow',
    });
    
    try {
      const response = await fetch(modifiedRequest);
      return response;
    } catch (e) {
      return new Response(`Tunnel unreachable: ${e.message}`, { status: 502 });
    }
  },
};
