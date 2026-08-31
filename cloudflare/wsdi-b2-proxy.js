/**
 * WSDI B2 代理 Worker
 * 域名: b2.yanhong.online
 * 作用: 把对 b2.yanhong.online/Drivers/xxx.7z 的请求转发到 B2 私有桶
 *       每次请求前调 B2 API 拿一个临时签名 URL，然后 302 重定向客户端到 B2
 *       客户端直连 B2 下载（走 CF Bandwidth Alliance → 流量免费）
 *
 * 缓存策略:
 *  - 临时签名 URL 本身不缓存（每次 Worker 都重新签）
 *  - 但客户端浏览器/CF 边缘会缓存 302 响应一段时间（默认几分钟）
 *  - 大文件本身不通过 Worker 流式转发，所以 Worker CPU 几乎为 0
 *
 * 部署:
 *  - 在 CF Dashboard 创建一个 Worker，粘贴这段代码
 *  - 在 Workers > Triggers > Custom Domains 加 b2.yanhong.online
 *  - 在 DNS 会自动加一条 CNAME（CF 代理开启）
 */

// B2 API 凭据（与 rclone.conf 一致）
const B2_KEY_ID = '004a547fb4332250000000001';
const B2_APP_KEY = 'K004twY1jKdG2ToSqg00Xq8OBs/ms80';
const B2_BUCKET_NAME = 'wsdi-drivers';
const B2_BUCKET_ID = 'bab594876f4be45393f20215';

// B2 API endpoint（创建桶时显示的 S3 Endpoint 对应的 api 地址）
// us-west-004 的 api 地址: https://api004.backblazeb2.com
const B2_API_BASE = 'https://api004.backblazeb2.com';

// 签名 URL 有效期（秒），1 小时足够大多数大文件下载
const AUTH_DURATION = 3600;

// Cache the auth token in memory for up to 24h (B2 allows up to 7 days)
let _authCache = null; // { token, apiUrl, downloadUrl, expireAt }

async function getAuthToken() {
  const now = Date.now();
  if (_authCache && _authCache.expireAt > now + 60000) {
    return _authCache;
  }
  const basic = btoa(`${B2_KEY_ID}:${B2_APP_KEY}`);
  const resp = await fetch(`${B2_API_BASE}/b2api/v3/b2_authorize_account`, {
    headers: { Authorization: `Basic ${basic}` },
  });
  if (!resp.ok) {
    throw new Error(`b2_authorize_account failed: ${resp.status} ${await resp.text()}`);
  }
  const data = await resp.json();
  _authCache = {
    token: data.authorizationToken,
    apiUrl: data.apiInfo.storageApi.apiUrl,   // https://api004.backblazeb2.com
    downloadUrl: data.apiInfo.storageApi.downloadUrl, // https://f004.backblazeb2.com
    expireAt: now + 23 * 3600 * 1000, // 23 小时刷新
  };
  return _authCache;
}

async function getDownloadUrl(fileName) {
  const auth = await getAuthToken();
  // 关键修复：url.pathname 返回的字符串已经 URL-encoded（%20、%E7 等），
  // 必须先 decodeURIComponent 拿到原始 fileName（含中文/空格等），然后
  // 用 b2_get_download_authorization 直接对原始 fileName 进行授权。
  // 这里不能再 encodeURI，否则会双重编码（%20 → %2520）导致 B2 找不到文件。
  const decodedFileName = decodeURIComponent(fileName);

  // b2_get_download_authorization 返回一个临时签名的下载 URL 前缀
  const resp = await fetch(`${auth.apiUrl}/b2api/v3/b2_get_download_authorization`, {
    method: 'POST',
    headers: {
      Authorization: auth.token,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      bucketId: B2_BUCKET_ID,
      fileNamePrefix: decodedFileName,
      validDurationInSeconds: AUTH_DURATION,
    }),
  });
  if (!resp.ok) {
    throw new Error(`b2_get_download_authorization failed: ${resp.status} ${await resp.text()}`);
  }
  const data = await resp.json();
  // 完整下载 URL: {downloadUrl}/file/{bucket}/{fileName}?Authorization={token}
  // 这里再次 encodeURI 一次，因为我们要构造给浏览器重定向的 URL，
  // 浏览器发送这个 URL 时会再次自动编码（？）—— 不对，浏览器不编码。
  // 实际上 downloadUrl 路径段需要是 URL-encoded 形式，所以 encodeURI 一次是必要的。
  const url = `${auth.downloadUrl}/file/${B2_BUCKET_NAME}/${encodeURI(decodedFileName)}?Authorization=${encodeURIComponent(data.authorizationToken)}`;
  return url;
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    let path = url.pathname;
    // 去掉前导 /
    if (path.startsWith('/')) path = path.slice(1);

    // 根路径给个说明
    if (!path) {
      return new Response('WSDI B2 proxy. Usage: /Drivers/xxx.7z', {
        headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      });
    }

    try {
      // path 形如 "Drivers/DP_xxx.7z" 或 "DP_xxx.7z"
      const downloadUrl = await getDownloadUrl(path);
      // 302 重定向客户端直连 B2（不流式转发，省 Worker CPU）
      return new Response(null, {
        status: 302,
        headers: {
          Location: downloadUrl,
          'Cache-Control': 'public, max-age=300', // 浏览器 5 分钟内不重签
          'Access-Control-Allow-Origin': '*',
        },
      });
    } catch (e) {
      return new Response(`B2 proxy error: ${e.message}`, {
        status: 502,
        headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      });
    }
  },
};
