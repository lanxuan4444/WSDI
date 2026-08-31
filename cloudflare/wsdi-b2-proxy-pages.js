/**
 * WSDI B2 代理 (Pages Functions 格式)
 * 部署: 在 Pages 项目里建 functions/[[path]].js，粘贴这段代码
 */

const B2_KEY_ID = '004a547fb4332250000000001';
const B2_APP_KEY = 'K004twY1jKdG2ToSqg00Xq8OBs/ms80';
const B2_BUCKET_NAME = 'wsdi-drivers';
const B2_BUCKET_ID = 'bab594876f4be45393f20215';
const B2_API_BASE = 'https://api004.backblazeb2.com';
const AUTH_DURATION = 3600;

let _authCache = null;

async function getAuthToken() {
  const now = Date.now();
  if (_authCache && _authCache.expireAt > now + 60000) return _authCache;
  const basic = btoa(`${B2_KEY_ID}:${B2_APP_KEY}`);
  const resp = await fetch(`${B2_API_BASE}/b2api/v3/b2_authorize_account`, {
    headers: { Authorization: `Basic ${basic}` },
  });
  if (!resp.ok) throw new Error(`auth failed: ${resp.status} ${await resp.text()}`);
  const data = await resp.json();
  _authCache = {
    token: data.authorizationToken,
    apiUrl: data.apiInfo.storageApi.apiUrl,
    downloadUrl: data.apiInfo.storageApi.downloadUrl,
    expireAt: now + 23 * 3600 * 1000,
  };
  return _authCache;
}

async function getDownloadUrl(fileName) {
  const auth = await getAuthToken();
  const resp = await fetch(`${auth.apiUrl}/b2api/v3/b2_get_download_authorization`, {
    method: 'POST',
    headers: { Authorization: auth.token, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      bucketId: B2_BUCKET_ID,
      fileNamePrefix: fileName,
      validDurationInSeconds: AUTH_DURATION,
    }),
  });
  if (!resp.ok) throw new Error(`getDownloadUrl failed: ${resp.status} ${await resp.text()}`);
  const data = await resp.json();
  return `${auth.downloadUrl}/file/${B2_BUCKET_NAME}/${encodeURI(fileName)}?Authorization=${encodeURIComponent(data.authorizationToken)}`;
}

export async function onRequest(context) {
  const url = new URL(context.request.url);
  let path = url.pathname.replace(/^\//, '');
  if (!path) {
    return new Response('WSDI B2 proxy. Usage: /Drivers/xxx.7z', {
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    });
  }
  try {
    const downloadUrl = await getDownloadUrl(path);
    return new Response(null, {
      status: 302,
      headers: {
        Location: downloadUrl,
        'Cache-Control': 'public, max-age=300',
        'Access-Control-Allow-Origin': '*',
      },
    });
  } catch (e) {
    return new Response(`B2 proxy error: ${e.message}`, {
      status: 502,
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    });
  }
}