package com.ldtools.parts;

import android.annotation.SuppressLint;
import android.os.Bundle;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import androidx.appcompat.app.AppCompatActivity;

/**
 * [v1.05] LDTools 查询页面：APP 内嵌 WebView 直接打开服务器首页
 *   （日志查询 / 主机配件查询），地址跟随「⚙ 设置」当前服务器（内网/外网）。
 * [v1.09] 去掉悬浮关闭按钮，系统返回键返回。
 */
public class WebActivity extends AppCompatActivity {

    private WebView wv;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        String base = ApiClient.normalizeBase(Prefs.serverBase(this));
        if (base.isEmpty()) {
            finish();
            return;
        }

        wv = new WebView(this);
        WebSettings ws = wv.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);       // 网页 token 存 localStorage，必须开启
        ws.setSupportZoom(true);
        ws.setBuiltInZoomControls(true);
        ws.setDisplayZoomControls(false);
        wv.setWebViewClient(new WebViewClient());   // 站内链接在 APP 内打开

        // [v1.09] 去掉悬浮「✕ 关闭」按钮：系统返回键返回（WebView 内先回退页面历史）
        setContentView(wv);

        wv.loadUrl(base + "/");
    }

    @Override
    public void onBackPressed() {
        // WebView 内先后退页面历史，退无可退再退出
        if (wv != null && wv.canGoBack()) {
            wv.goBack();
            return;
        }
        super.onBackPressed();
    }

    @Override
    protected void onDestroy() {
        if (wv != null) wv.destroy();
        super.onDestroy();
    }
}
