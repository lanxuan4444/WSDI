package com.ldtools.parts;

import android.content.Context;
import android.content.SharedPreferences;

/** 服务器地址 / 访问密码 / token 的本地存储 */
public final class Prefs {

    private static final String FILE = "ldparts";

    private Prefs() {}

    private static SharedPreferences sp(Context c) {
        return c.getApplicationContext().getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    public static String serverBase(Context c) {
        return sp(c).getString("serverBase", "");
    }

    public static void setServerBase(Context c, String v) {
        sp(c).edit().putString("serverBase", v == null ? "" : v).apply();
    }

    public static String password(Context c) {
        return sp(c).getString("password", "");
    }

    public static void setPassword(Context c, String v) {
        sp(c).edit().putString("password", v == null ? "" : v).apply();
    }

    public static String token(Context c) {
        return sp(c).getString("token", "");
    }

    public static void setToken(Context c, String token) {
        sp(c).edit().putString("token", token == null ? "" : token).apply();
    }

    public static void clearToken(Context c) {
        sp(c).edit().remove("token").apply();
    }

    /** [v1.17] 上次选择的供应商（记忆：下次打开默认选中） */
    public static String vendor(Context c) {
        return sp(c).getString("vendor", "");
    }

    public static void setVendor(Context c, String v) {
        sp(c).edit().putString("vendor", v == null ? "" : v).apply();
    }
}
