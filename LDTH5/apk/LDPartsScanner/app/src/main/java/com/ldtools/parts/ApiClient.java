package com.ldtools.parts;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

import okhttp3.MediaType;
import okhttp3.MultipartBody;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import okio.BufferedSink;

/** LDTools 服务端 API 客户端（登录鉴权 + 配件档案 multipart 上传） */
public final class ApiClient {

    /** 上传进度回调（0-100） */
    public interface Progress {
        void onProgress(int percent);
    }

    /** 401 鉴权失败（token 过期），调用方可重新登录后重试一次 */
    public static class AuthException extends IOException {
        public AuthException(String message) { super(message); }
    }

    private static final OkHttpClient CLIENT = new OkHttpClient.Builder()
            .connectTimeout(5, java.util.concurrent.TimeUnit.SECONDS)
            .readTimeout(120, java.util.concurrent.TimeUnit.SECONDS)
            .writeTimeout(120, java.util.concurrent.TimeUnit.SECONDS)
            .build();

    private ApiClient() {}

    /** 规范化服务器地址：补 http:// 前缀、去尾部斜杠 */
    public static String normalizeBase(String raw) {
        String s = raw == null ? "" : raw.trim();
        if (s.isEmpty()) return s;
        if (!s.startsWith("http://") && !s.startsWith("https://")) s = "http://" + s;
        while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        return s;
    }

    /** POST /api/auth 验证访问密码，成功返回 token，失败抛 IOException（含服务端 message） */
    public static String login(String base, String password) throws IOException {
        JSONObject body = new JSONObject();
        try {
            body.put("password", password == null ? "" : password);
        } catch (JSONException ignored) {
        }
        Request req = new Request.Builder()
                .url(base + "/api/auth")
                .post(RequestBody.create(body.toString(), MediaType.parse("application/json; charset=utf-8")))
                .build();
        try (Response resp = CLIENT.newCall(req).execute()) {
            String text = resp.body() == null ? "" : resp.body().string();
            JSONObject json = parse(text);
            if (resp.isSuccessful() && json.optBoolean("ok")) {
                return json.optString("token", "");
            }
            throw new IOException(json.optString("message", "登录失败（HTTP " + resp.code() + "）"));
        }
    }

    /**
     * GET /api/parts-archive 拉取全量档案（用于上传前 CPU 三元组查重）。
     * 返回 JSON 文本；401 抛 AuthException；其他失败抛 IOException。
     */
    public static String listRecords(String base, String token) throws IOException {
        Request.Builder rb = new Request.Builder().url(base + "/api/parts-archive").get();
        if (token != null && !token.isEmpty()) {
            rb.header("Authorization", "Bearer " + token);
        }
        try (Response resp = CLIENT.newCall(rb.build()).execute()) {
            String text = resp.body() == null ? "" : resp.body().string();
            if (resp.isSuccessful()) return text;
            if (resp.code() == 401) {
                throw new AuthException(parse(text).optString("message", "登录已过期"));
            }
            throw new IOException(parse(text).optString("message", "查询失败（HTTP " + resp.code() + "）"));
        }
    }

    /**
     * POST /api/parts-archive multipart 上传配件档案。
     * photos: {配件类型 → 照片列表}，类型 ∈ {cpu, host, ram, ssd, other}。
     * 成功返回服务端 JSON 文本；失败抛 IOException / AuthException（含服务端 message）。
     */
    public static String upload(String base, String token, Map<String, String> fields,
                                Map<String, List<File>> photos,
                                Progress progress) throws IOException {
        long total = 0;
        for (List<File> fl : photos.values()) {
            for (File f : fl) total += f.length();
        }
        AtomicLong written = new AtomicLong();

        MultipartBody.Builder mb = new MultipartBody.Builder().setType(MultipartBody.FORM);
        for (Map.Entry<String, String> e : fields.entrySet()) {
            mb.addFormDataPart(e.getKey(), e.getValue());
        }
        for (Map.Entry<String, List<File>> e : photos.entrySet()) {
            String type = e.getKey();
            for (File f : e.getValue()) {
                mb.addFormDataPart(type + "File", f.getName(), progressBody(f, total, written, progress));
            }
        }

        Request.Builder rb = new Request.Builder()
                .url(base + "/api/parts-archive")
                .post(mb.build());
        if (token != null && !token.isEmpty()) {
            rb.header("Authorization", "Bearer " + token);
        }
        try (Response resp = CLIENT.newCall(rb.build()).execute()) {
            String text = resp.body() == null ? "" : resp.body().string();
            JSONObject json = parse(text);
            if (resp.isSuccessful() && json.optBoolean("ok")) {
                return text;
            }
            if (resp.code() == 401) {
                throw new AuthException(json.optString("message", "登录已过期"));
            }
            throw new IOException(json.optString("message", "上传失败（HTTP " + resp.code() + "）"));
        }
    }

    /** 带总进度回调的文件 RequestBody */
    private static RequestBody progressBody(final File file, final long total,
                                            final AtomicLong written, final Progress progress) {
        final RequestBody inner = RequestBody.create(MediaType.parse("application/octet-stream"), file);
        return new RequestBody() {
            @Override
            public MediaType contentType() {
                return inner.contentType();
            }

            @Override
            public long contentLength() {
                return file.length();
            }

            @Override
            public void writeTo(BufferedSink sink) throws IOException {
                byte[] buf = new byte[8192];
                InputStream in = new FileInputStream(file);
                try {
                    int n;
                    while ((n = in.read(buf)) > 0) {
                        sink.write(buf, 0, n);
                        long w = written.addAndGet(n);
                        if (progress != null && total > 0) {
                            progress.onProgress((int) Math.min(99, w * 100 / total));
                        }
                    }
                } finally {
                    try {
                        in.close();
                    } catch (IOException ignored) {
                    }
                }
            }
        };
    }

    private static JSONObject parse(String text) {
        try {
            return new JSONObject(text == null || text.isEmpty() ? "{}" : text);
        } catch (JSONException e) {
            return new JSONObject();
        }
    }
}
