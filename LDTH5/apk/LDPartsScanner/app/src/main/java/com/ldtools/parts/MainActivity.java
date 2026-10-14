package com.ldtools.parts;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.net.Uri;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.HorizontalScrollView;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.PickVisualMediaRequest;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;

import com.google.mlkit.vision.common.InputImage;
import com.google.mlkit.vision.text.Text;
import com.google.mlkit.vision.text.TextRecognition;
import com.google.mlkit.vision.text.TextRecognizer;
import com.google.mlkit.vision.text.latin.TextRecognizerOptions;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * LDParts 配件录入主页（5 类配件：CPU / 主机 / 内存 / 固态 / 其他）
 *   拍照 → ML Kit OCR → 候选点选填表 → 用户确认 → multipart 上传到 LDTools 服务端。
 * [v1.0] 主机编号旁「扫码」入口 → ScanActivity 条码/二维码识别直接填入（无条码可拍标签 OCR）。
 * [v1.01] 恢复 1.0 扫码功能；照片预览支持双指缩放 / 拖动 / 双击放大（ZoomImageView）。
 * [v1.02] 主机型号升级为独立输入框（拍照自动填入+候选点选）；CPU 三项逐行标注；
 *         去掉网卡类目；⚙ 设置展开后自动滚动到设置区（修复"打不开"）。
 */
public class MainActivity extends AppCompatActivity {

    private static final int MAX_PHOTOS_PER_TYPE = 6;

    /** 配件类目（key 与服务端 multipart 字段一一对应）[v1.02 去掉网卡] */
    private static final String[] PART_KEYS = {"cpu", "host", "ram", "ssd", "other"};
    private static final Map<String, String> PART_LABELS = new LinkedHashMap<>();
    private static final Map<String, String> PART_FIELDS = new LinkedHashMap<>();
    static {
        PART_LABELS.put("cpu", "CPU 照片");
        PART_LABELS.put("host", "主机照片");
        PART_LABELS.put("ram", "内存");
        PART_LABELS.put("ssd", "固态硬盘");
        PART_LABELS.put("other", "其他配件");
        PART_FIELDS.put("ram", "ramInfo");
        PART_FIELDS.put("ssd", "ssdInfo");
        PART_FIELDS.put("other", "otherInfo");
    }

    private EditText etHostSn, etHostModel, etCpuModel, etCpuBatch, etCpuCode, etNote;
    private EditText etServer, etPassword;
    private TextView tvServerStatus, hostChipHint, hostModelChipHint;
    private LinearLayout chipRow, hostChipRow, hostModelChipRow, photoCpuRow, photoHostRow, settingsSection;
    private LinearLayout vendorChipRow;
    private EditText etVendorOther;
    private Button btnUpload;

    /** [v1.17] 供应商选项（默认不选=不上传；「其他」→ 手动输入；上次选择自动记忆） */
    private static final String[] VENDORS = {"联想", "戴尔", "建钰", "其他", "无"};
    private String vendorSel = "";

    /** 各类配件照片：key → File 列表 */
    private final Map<String, List<File>> photos = new LinkedHashMap<>();
    /** 动态类目（内存/固态/网卡/其他）：参数输入框 / 候选 chips 行 / 缩略图行 */
    private final Map<String, EditText> infoFields = new LinkedHashMap<>();
    private final Map<String, LinearLayout> infoChipRows = new LinkedHashMap<>();
    private final Map<String, LinearLayout> infoThumbRows = new LinkedHashMap<>();

    /** 当前拍照/选图的目标区（PART_KEYS 之一），回调时用 */
    private String pendingType = "cpu";

    /* [v1.13] 所有类目照片一律追加（CPU 也可能拍多张同款/不同角度，用户自己决定删不删——缩略图 ✕），
       v1.04 的"重拍覆盖"机制（replaceOnCapture）已按用户要求移除 */

    private final ExecutorService exec = Executors.newSingleThreadExecutor();

    // ---------- ActivityResult 注册（须在 onCreate 之前） ----------

    private final ActivityResultLauncher<android.content.Intent> captureLauncher =
            registerForActivityResult(new ActivityResultContracts.StartActivityForResult(), result -> {
                if (result.getResultCode() != RESULT_OK || result.getData() == null) return;
                String path = result.getData().getStringExtra(CaptureActivity.EXTRA_PATH);
                String type = result.getData().getStringExtra(CaptureActivity.EXTRA_TYPE);
                if (path == null || type == null) return;
                onPhotoTaken(type, new File(path));
            });

    private final ActivityResultLauncher<PickVisualMediaRequest> pickLauncher =
            registerForActivityResult(new ActivityResultContracts.PickVisualMedia(), uri -> {
                if (uri == null) return;
                handlePickedImage(uri);
            });

    /** [v1.0 恢复，v1.01] 扫码结果：条码 "value" → 填主机编号；ScanActivity 拍标签透传 "path"/"type" → 按主机照片处理 */
    private final ActivityResultLauncher<android.content.Intent> scanLauncher =
            registerForActivityResult(new ActivityResultContracts.StartActivityForResult(), result -> {
                if (result.getResultCode() != RESULT_OK || result.getData() == null) return;
                String path = result.getData().getStringExtra(CaptureActivity.EXTRA_PATH);
                String type = result.getData().getStringExtra(CaptureActivity.EXTRA_TYPE);
                if (path != null && type != null) {
                    // [v1.13] 扫码页拍的标签照作为主机照片追加保存
                    onPhotoTaken(type, new File(path));
                    return;
                }
                String v = result.getData().getStringExtra(ScanActivity.EXTRA_VALUE);
                if (v != null && !v.isEmpty()) {
                    etHostSn.setText(v.trim());
                    toast("已填入主机编号: " + v.trim());
                }
            });

    // ---------- 生命周期 ----------

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        for (String k : PART_KEYS) photos.put(k, new ArrayList<>());

        bindViews();
        buildPartSections();
        loadServerSettings();

        findViewById(R.id.btnTakeCpu).setOnClickListener(v -> openCapture("cpu"));
        findViewById(R.id.btnPickCpu).setOnClickListener(v -> openPicker("cpu"));
        findViewById(R.id.btnTakeHost).setOnClickListener(v -> openCapture("host"));
        findViewById(R.id.btnPickHost).setOnClickListener(v -> openPicker("host"));
        // [v1.0 恢复，v1.01] 扫码填主机编号
        findViewById(R.id.btnScan).setOnClickListener(v -> {
            pendingType = "host";
            scanLauncher.launch(new android.content.Intent(this, ScanActivity.class));
        });
        findViewById(R.id.btnSettingsToggle).setOnClickListener(v -> toggleSettings());
        findViewById(R.id.btnSaveSettings).setOnClickListener(v -> saveServerSettings());
        // [v1.05] 内嵌查询页面 + 内外网一键切换
        findViewById(R.id.btnWeb).setOnClickListener(v -> openWeb());
        findViewById(R.id.btnNetLan).setOnClickListener(v -> switchServer("http://192.168.1.88:9876"));
        findViewById(R.id.btnNetWan).setOnClickListener(v -> switchServer("https://logs.yanhong.online"));
        btnUpload.setOnClickListener(v -> startUpload());
    }

    private void bindViews() {
        etHostSn = findViewById(R.id.etHostSn);
        etHostModel = findViewById(R.id.etHostModel);
        etCpuModel = findViewById(R.id.etCpuModel);
        etCpuBatch = findViewById(R.id.etCpuBatch);
        etCpuCode = findViewById(R.id.etCpuCode);
        etNote = findViewById(R.id.etNote);
        etServer = findViewById(R.id.etServer);
        etPassword = findViewById(R.id.etPassword);
        tvServerStatus = findViewById(R.id.tvServerStatus);
        hostChipHint = findViewById(R.id.hostChipHint);
        hostModelChipHint = findViewById(R.id.hostModelChipHint);
        chipRow = findViewById(R.id.chipRow);
        hostChipRow = findViewById(R.id.hostChipRow);
        hostModelChipRow = findViewById(R.id.hostModelChipRow);
        photoCpuRow = findViewById(R.id.photoCpuRow);
        photoHostRow = findViewById(R.id.photoHostRow);
        settingsSection = findViewById(R.id.settingsSection);
        vendorChipRow = findViewById(R.id.vendorChipRow);
        etVendorOther = findViewById(R.id.etVendorOther);
        btnUpload = findViewById(R.id.btnUpload);
        // [v1.17] 供应商：恢复上次选择（记忆），构建 chips
        vendorSel = Prefs.vendor(this);
        buildVendorChips();
    }

    // ---------- 供应商（[v1.17] 联想/戴尔/建钰/其他/无，默认不选） ----------

    private void buildVendorChips() {
        vendorChipRow.removeAllViews();
        for (String v : VENDORS) {
            Button b = new Button(this);
            b.setText(v);
            b.setTextSize(13);
            b.setMinWidth(0);
            b.setMinHeight(0);
            b.setPadding(dp(16), dp(4), dp(16), dp(4));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            lp.setMargins(0, 0, dp(10), 0);
            b.setLayoutParams(lp);
            applyVendorStyle(b, v);
            b.setOnClickListener(btn -> {
                vendorSel = vendorSel.equals(v) ? "" : v;   // 再点一次取消选择（不上传）
                Prefs.setVendor(this, vendorSel);           // 记忆：下次默认上次选择
                refreshVendorChips();
            });
            vendorChipRow.addView(b);
        }
    }

    private void refreshVendorChips() {
        for (int i = 0; i < vendorChipRow.getChildCount(); i++) {
            android.view.View child = vendorChipRow.getChildAt(i);
            if (child instanceof Button) applyVendorStyle((Button) child, ((Button) child).getText().toString());
        }
        etVendorOther.setVisibility("其他".equals(vendorSel) ? View.VISIBLE : View.GONE);
    }

    private void applyVendorStyle(Button b, String v) {
        boolean on = v.equals(vendorSel);
        b.setBackgroundTintList(android.content.res.ColorStateList.valueOf(on ? 0xFF1A56DB : 0xFF556655));
        b.setTextColor(on ? 0xFFFFFFFF : 0xFFDDDDDD);
    }

    /** 上传用的供应商值：未选→空；「其他」→手动输入（空则"其他"）；其余→所选词 */
    private String vendorValue() {
        if (vendorSel.isEmpty()) return "";
        if ("其他".equals(vendorSel)) {
            String t = etVendorOther.getText().toString().trim();
            return t.isEmpty() ? "其他" : t;
        }
        return vendorSel;
    }

    // ---------- 动态配件区块（内存/固态/网卡/其他） ----------

    private void buildPartSections() {
        LinearLayout container = findViewById(R.id.partSections);
        for (String key : Arrays.asList("ram", "ssd", "other")) {
            LinearLayout box = new LinearLayout(this);
            box.setOrientation(LinearLayout.VERTICAL);
            box.setBackgroundResource(R.drawable.bg_card);
            LinearLayout.LayoutParams boxLp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            boxLp.topMargin = dp(14);
            box.setLayoutParams(boxLp);
            int pad = dp(14);
            box.setPadding(pad, pad, pad, pad);

            // 标题行：标签 + 拍照 + 相册 [v1.04 各类目识别侧重说明]
            LinearLayout head = new LinearLayout(this);
            head.setOrientation(LinearLayout.HORIZONTAL);
            head.setGravity(Gravity.CENTER_VERTICAL);
            TextView label = new TextView(this);
            String focus = "ram".equals(key) ? "品牌/容量/代数频率/序列号"
                    : "ssd".equals(key) ? "品牌/容量/接口/序列号" : "拍照自动识别";
            label.setText(PART_LABELS.get(key) + "（" + focus + "）");
            label.setTextColor(0xFF64748B);
            label.setTextSize(12);
            label.setTypeface(null, android.graphics.Typeface.BOLD);
            label.setLayoutParams(new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
            Button take = new Button(this);
            take.setText("📷 拍照");
            take.setTextColor(0xFFFFFFFF);
            take.getBackground().setTint(0xFF1A56DB);
            take.setTextSize(13);
            take.setMinHeight(0);
            take.setOnClickListener(v -> openCapture(key));
            Button pick = new Button(this);
            pick.setText("相册");
            pick.setTextSize(13);
            pick.setMinHeight(0);
            LinearLayout.LayoutParams pickLp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            pickLp.leftMargin = dp(6);
            pick.setLayoutParams(pickLp);
            pick.setOnClickListener(v -> openPicker(key));
            head.addView(label);
            head.addView(take);
            head.addView(pick);
            box.addView(head);

            // 参数输入框
            EditText et = new EditText(this);
            et.setInputType(android.text.InputType.TYPE_CLASS_TEXT
                    | android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE);
            et.setMinLines(2);
            et.setGravity(Gravity.TOP);
            et.setTextSize(14);
            LinearLayout.LayoutParams etLp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            etLp.topMargin = dp(8);
            et.setLayoutParams(etLp);
            box.addView(et);
            infoFields.put(key, et);

            // 候选 chips 行
            LinearLayout chips = new LinearLayout(this);
            chips.setOrientation(LinearLayout.HORIZONTAL);
            infoChipRows.put(key, chips);
            box.addView(wrapScroll(chips, dp(8)));

            // 照片缩略图行
            LinearLayout thumbs = new LinearLayout(this);
            thumbs.setOrientation(LinearLayout.HORIZONTAL);
            infoThumbRows.put(key, thumbs);
            box.addView(wrapScroll(thumbs, dp(8)));

            container.addView(box);
        }
    }

    private View wrapScroll(View child, int topMargin) {
        HorizontalScrollView hsv = new HorizontalScrollView(this);
        hsv.setHorizontalScrollBarEnabled(false);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = topMargin;
        hsv.setLayoutParams(lp);
        hsv.addView(child);
        return hsv;
    }

    // ---------- 服务器设置（保存后折叠） ----------

    private void toggleSettings() {
        boolean show = settingsSection.getVisibility() != View.VISIBLE;
        settingsSection.setVisibility(show ? View.VISIBLE : View.GONE);
        // [v1.02] 展开后自动滚动到设置区（设置区在页面底部，否则看起来"打不开"）
        if (show) scrollToBottom();
    }

    private void scrollToBottom() {
        ScrollView sv = findViewById(R.id.mainScroll);
        sv.post(() -> sv.smoothScrollTo(0, sv.getChildAt(0).getBottom()));
    }

    private void loadServerSettings() {
        etServer.setText(Prefs.serverBase(this));
        etPassword.setText(Prefs.password(this));
        String base = Prefs.serverBase(this);
        // 首次（未配置）自动展开，保存后收起
        settingsSection.setVisibility(base.isEmpty() ? View.VISIBLE : View.GONE);
        tvServerStatus.setText(base.isEmpty() ? "未配置服务器，请填写后保存"
                : "当前服务器: " + base);
    }

    /** [v1.05] 内外网一键切换：填入地址并立即保存（token 失效自动重登） */
    private void switchServer(String base) {
        String normalized = ApiClient.normalizeBase(base);
        etServer.setText(normalized);
        if (Prefs.password(this).isEmpty()) {
            // 首次使用还没存密码：只填地址，提示保存
            tvServerStatus.setText("已选择: " + normalized + "（填访问密码后点保存）");
            settingsSection.setVisibility(View.VISIBLE);
            scrollToBottom();
            etPassword.requestFocus();
            return;
        }
        Prefs.setServerBase(this, normalized);
        Prefs.clearToken(this);
        tvServerStatus.setText("当前服务器: " + normalized);
        toast("已切换到 " + normalized);
    }

    /** [v1.05] 打开内嵌 LDTools 查询页面（WebView） */
    private void openWeb() {
        String base = ApiClient.normalizeBase(Prefs.serverBase(this));
        if (base.isEmpty()) {
            toast("请先点「⚙ 设置」选择内网/外网并保存");
            settingsSection.setVisibility(View.VISIBLE);
            scrollToBottom();
            return;
        }
        startActivity(new android.content.Intent(this, WebActivity.class));
    }

    private void saveServerSettings() {
        String base = ApiClient.normalizeBase(etServer.getText().toString());
        String pw = etPassword.getText().toString();
        if (base.isEmpty()) {
            toast("服务器地址不能为空");
            return;
        }
        etServer.setText(base);
        Prefs.setServerBase(this, base);
        Prefs.setPassword(this, pw);
        Prefs.clearToken(this);
        tvServerStatus.setText("当前服务器: " + base);
        settingsSection.setVisibility(View.GONE);   // 保存后收起，首页不再显示
        toast("已保存服务器设置");
    }

    // ---------- 拍照 / 选图 ----------

    private void openCapture(String type) {
        if (!canAddPhoto(type)) return;
        pendingType = type;
        // [v1.13] 所有类目拍照一律追加（多张保留，删除由用户通过缩略图 ✕ 决定）
        android.content.Intent it = new android.content.Intent(this, CaptureActivity.class);
        it.putExtra(CaptureActivity.EXTRA_TYPE, type);
        captureLauncher.launch(it);
    }

    private void openPicker(String type) {
        if (!canAddPhoto(type)) return;
        pendingType = type;
        pickLauncher.launch(new PickVisualMediaRequest.Builder()
                .setMediaType(ActivityResultContracts.PickVisualMedia.ImageOnly.INSTANCE)
                .build());
    }

    private boolean canAddPhoto(String type) {
        List<File> list = photos.get(type);
        if (list != null && list.size() >= MAX_PHOTOS_PER_TYPE) {
            toast(PART_LABELS.get(type) + " 最多 " + MAX_PHOTOS_PER_TYPE + " 张照片");
            return false;
        }
        return true;
    }

    private void handlePickedImage(Uri uri) {
        final String type = pendingType;
        exec.execute(() -> {
            try {
                File dir = new File(getCacheDir(), "picked");
                if (!dir.exists()) dir.mkdirs();
                File out = new File(dir, "pick_" + System.currentTimeMillis() + ".jpg");
                InputStream in = getContentResolver().openInputStream(uri);
                if (in == null) throw new IOException("无法打开所选图片");
                OutputStream os = new FileOutputStream(out);
                byte[] buf = new byte[8192];
                int n;
                while ((n = in.read(buf)) > 0) os.write(buf, 0, n);
                os.close();
                in.close();
                runOnUiThread(() -> onPhotoTaken(type, out));
            } catch (Exception e) {
                runOnUiThread(() -> toast("读取图片失败: " + e.getMessage()));
            }
        });
    }

    private void onPhotoTaken(String type, File photo) {
        List<File> list = photos.get(type);
        if (list == null) list = photos.get("other");
        // [v1.13] 追加模式：多张照片都保留（删除由用户通过缩略图 ✕ 决定）
        if (list.size() >= MAX_PHOTOS_PER_TYPE) {
            toast(PART_LABELS.get(type) + " 最多 " + MAX_PHOTOS_PER_TYPE + " 张照片");
            return;
        }
        list.add(photo);
        addPhotoThumb(type, photo);
        runOcr(photo, type);
    }

    /** 按类型把缩略图加到对应的行（cpu/host 固定行，动态类目行） */
    private LinearLayout thumbRowOf(String type) {
        if ("cpu".equals(type)) return photoCpuRow;
        if ("host".equals(type)) return photoHostRow;
        LinearLayout row = infoThumbRows.get(type);
        return row != null ? row : photoHostRow;
    }

    private void addPhotoThumb(String type, File photo) {
        LinearLayout row = thumbRowOf(type);
        // [v1.03] 单元格 = 照片 + 右上角 ✕ 删除按钮
        android.widget.FrameLayout cell = new android.widget.FrameLayout(this);
        int px = dp(96);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(px, px);
        lp.setMargins(0, dp(6), dp(10), 0);
        cell.setLayoutParams(lp);
        cell.setBackgroundColor(0xFFE2E8F0);

        ImageView iv = new ImageView(this);
        iv.setLayoutParams(new android.widget.FrameLayout.LayoutParams(
                android.widget.FrameLayout.LayoutParams.MATCH_PARENT,
                android.widget.FrameLayout.LayoutParams.MATCH_PARENT));
        iv.setScaleType(ImageView.ScaleType.CENTER_CROP);
        // 点击预览（拍好的照片在上传前可放大查看，决定要不要重拍）
        iv.setOnClickListener(v -> showPhotoPreview(photo));
        cell.addView(iv);

        // ✕ 删除按钮：点击直接从本次上传移除该照片
        TextView x = new TextView(this);
        x.setText("✕");
        x.setTextColor(0xFFFFFFFF);
        x.setTextSize(13);
        x.setGravity(Gravity.CENTER);
        x.setBackgroundResource(R.drawable.bg_delete_x);
        android.widget.FrameLayout.LayoutParams xlp = new android.widget.FrameLayout.LayoutParams(
                dp(24), dp(24), Gravity.TOP | Gravity.END);
        xlp.setMargins(0, dp(2), dp(2), 0);
        x.setLayoutParams(xlp);
        x.setOnClickListener(v -> {
            row.removeView(cell);
            List<File> list = photos.get(type);
            if (list != null) list.remove(photo);
            toast("已删除照片");
        });
        cell.addView(x);

        row.addView(cell);
        exec.execute(() -> {
            Bitmap bm = decodeSampled(photo, 256);
            if (bm != null) runOnUiThread(() -> iv.setImageBitmap(bm));
        });
    }

    /** [v1.01] 上传前的照片预览：全屏大图，双指缩放 / 拖动 / 双击放大 */
    private void showPhotoPreview(File photo) {
        runOnUiThread(() -> {
            ZoomImageView iv = new ZoomImageView(this);
            iv.setBackgroundColor(0xFF000000);
            android.app.Dialog dialog = new android.app.Dialog(this,
                    android.R.style.Theme_Black_NoTitleBar_Fullscreen);
            dialog.setContentView(iv, new ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            // 点关闭按钮退出；缩放时不禁用（关闭按钮固定在右上）
            android.widget.Button close = new android.widget.Button(this);
            close.setText("✕ 关闭");
            close.setTextColor(0xFFFFFFFF);
            close.getBackground().setAlpha(120);
            close.setMinHeight(0);
            android.widget.FrameLayout fl = (android.widget.FrameLayout) iv.getParent();
            android.widget.FrameLayout.LayoutParams clp = new android.widget.FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                    Gravity.TOP | Gravity.END);
            int m = dp(12);
            clp.setMargins(0, m, m, 0);
            fl.addView(close, clp);
            close.setOnClickListener(v -> dialog.dismiss());
            dialog.show();
            exec.execute(() -> {
                Bitmap bm = decodeSampled(photo, 2048);
                if (bm != null) runOnUiThread(() -> iv.setImageBitmap(bm));
            });
        });
    }

    private Bitmap decodeSampled(File f, int target) {
        BitmapFactory.Options o = new BitmapFactory.Options();
        o.inJustDecodeBounds = true;
        BitmapFactory.decodeFile(f.getAbsolutePath(), o);
        int sample = 1;
        while (o.outWidth / (sample * 2) >= target && o.outHeight / (sample * 2) >= target) sample *= 2;
        BitmapFactory.Options o2 = new BitmapFactory.Options();
        o2.inSampleSize = sample;
        return BitmapFactory.decodeFile(f.getAbsolutePath(), o2);
    }

    // ---------- OCR ----------

    private void runOcr(File photo, String type) {
        InputImage image;
        try {
            image = InputImage.fromFilePath(this, Uri.fromFile(photo));
        } catch (IOException e) {
            toast("读取照片失败: " + e.getMessage());
            return;
        }
        boolean isCpu = "cpu".equals(type);
        TextRecognizer recognizer = TextRecognition.getClient(
                isCpu ? TextRecognizerOptions.DEFAULT_OPTIONS
                      : new com.google.mlkit.vision.text.chinese.ChineseTextRecognizerOptions.Builder().build());
        recognizer.process(image)
                .addOnSuccessListener(visionText -> {
                    List<String> lines = new ArrayList<>();
                    for (Text.TextBlock block : visionText.getTextBlocks()) {
                        for (Text.Line line : block.getLines()) {
                            String t = line.getText();
                            if (t != null && !t.trim().isEmpty()) lines.add(t.trim());
                        }
                    }
                    if (isCpu) handleCpuOcr(lines);
                    else if ("host".equals(type)) handleHostOcr(lines);
                    else handlePartOcr(type, lines);
                })
                .addOnFailureListener(e -> toast("OCR 识别失败: " + e.getMessage()))
                .addOnCompleteListener(t -> recognizer.close());
    }

    /* [v1.16] CPU 编号小字二次识别（v1.14/v1.15 的竖带裁剪旋转重试链）已按用户要求移除——
       小数字 OCR 识别率上不去且拖慢流程（编号缺失时最多多等 5-10 秒），回归 1.08 的
       一次 OCR 快速体验：识别不到的编号由用户手动输入（候选 chips 仍正常工作）。 */

    private void handleCpuOcr(List<String> lines) {
        OcrParser.CpuResult r = OcrParser.parseCpu(lines);
        // [v1.04] 重拍覆盖：最新一次拍照的识别结果直接覆盖旧值（不再只填空白）
        StringBuilder sb = new StringBuilder("识别：");
        boolean any = false;
        if (r.model != null) {
            etCpuModel.setText(r.model);
            sb.append(" 型号 ").append(r.model);
            any = true;
        }
        if (r.batch != null) {
            etCpuBatch.setText(r.batch);
            sb.append(" 批号 ").append(r.batch);
            any = true;
        }
        if (!r.codeCandidates.isEmpty()) {
            showCodeCandidates(r.codeCandidates);
            etCpuCode.setText(r.codeCandidates.get(0));
            sb.append(" 编号 ").append(r.codeCandidates.get(0));
            any = true;
        }
        toast(any ? sb.toString() : "未识别到 CPU 信息，请离近一点重新拍摄，或手动输入");
    }

    private void showCodeCandidates(List<String> candidates) {
        chipRow.removeAllViews();
        for (String c : candidates) {
            chipRow.addView(makeChip(c, v -> etCpuCode.setText(c)));
        }
    }

    private void handleHostOcr(List<String> lines) {
        OcrParser.HostResult r = OcrParser.parseHost(lines);
        // [v1.04] 重拍覆盖：识别结果直接覆盖旧值（拍错主机 → 重拍即纠正）
        boolean any = false;
        if (!r.snCandidates.isEmpty()) {
            showHostCandidates(r.snCandidates);
            etHostSn.setText(r.snCandidates.get(0));
            any = true;
        }
        if (r.batch != null) {
            replaceNoteLine("主机批号", r.batch);
            any = true;
        }
        if (r.machineModel != null) {
            showHostModelCandidates(r.machineModelCandidates);
            etHostModel.setText(r.machineModel);
            any = true;
        }
        toast(any ? "已提取主机信息（重拍自动覆盖旧结果）"
                : "未识别到出厂编号，请对准标签重拍或手动输入");
    }

    /** [v1.04] 替换备注中的「前缀: 旧值」行（重拍后清掉旧批号，防止错误信息残留） */
    private void replaceNoteLine(String prefix, String newVal) {
        String note = etNote.getText().toString();
        StringBuilder sb = new StringBuilder();
        for (String line : note.split("\n")) {
            if (line.startsWith(prefix + ":")) continue;   // 丢弃旧值
            if (line.trim().isEmpty()) continue;
            if (sb.length() > 0) sb.append('\n');
            sb.append(line);
        }
        if (sb.length() > 0) sb.append('\n');
        sb.append(prefix).append(": ").append(newVal);
        etNote.setText(sb.toString());
    }

    /** [v1.02] 主机型号候选 chips */
    private void showHostModelCandidates(List<String> candidates) {
        hostModelChipRow.removeAllViews();
        if (candidates.isEmpty()) {
            hostModelChipHint.setVisibility(View.GONE);
            return;
        }
        hostModelChipHint.setVisibility(View.VISIBLE);
        for (String c : candidates) {
            hostModelChipRow.addView(makeChip(c, v -> etHostModel.setText(c)));
        }
    }

    /** 主机编号候选 chips */
    private void showHostCandidates(List<String> candidates) {
        hostChipRow.removeAllViews();
        hostChipHint.setVisibility(View.VISIBLE);
        for (String c : candidates) {
            hostChipRow.addView(makeChip(c, v -> etHostSn.setText(c)));
        }
    }

    /**
     * 配件 OCR（内存/固态/其他）[v1.04]：
     *   内存 → 结构化摘要「SAMSUNG 8GB DDR4 3200MHz x2 | SN:…」（品牌/容量/代数/频率/数量/序列号）
     *   固态 → 结构化摘要「SAMSUNG 1TB NVMe | SN:xx」（品牌/容量/接口/序列号）
     * [v1.12] 摘要按行追加去重（多根内存/固态逐行累加，重拍同根不重复）；手动改过的行自然保留。
     *   原始候选 chips 仍可点选。
     */
    private void handlePartOcr(String type, List<String> lines) {
        LinearLayout chipRowDyn = infoChipRows.get(type);
        EditText et = infoFields.get(type);
        if (chipRowDyn == null || et == null) return;
        chipRowDyn.removeAllViews();

        String structured = null;
        if ("ram".equals(type)) structured = OcrParser.parseRam(lines);
        else if ("ssd".equals(type)) structured = OcrParser.parseSsd(lines);

        if (structured != null) {
            fillPartField(et, type, structured);
        }
        // 原始识别行 → chips（点选追加到参数框）
        List<String> candidates = OcrParser.parseGeneric(lines);
        for (String c : candidates) {
            chipRowDyn.addView(makeChip(c, v -> fillPartField(et, type, c)));
        }
        if (structured == null && candidates.isEmpty()) {
            toast("未识别到" + PART_LABELS.get(type) + "信息，请对准标签重拍或手动输入");
            return;
        }
        if (structured != null) {
            toast(PART_LABELS.get(type) + " 识别: " + structured);
        } else {
            toast("识别到 " + candidates.size() + " 条候选（" + PART_LABELS.get(type)
                    + "），点击候选填入参数");
        }
    }

    /**
     * [v1.12] 配件参数写入：按行追加去重。
     *   参数框为空 → 直接填入；已有内容且不含该行 → 换行追加（拍第 2 根内存/固态自动加第 2 行）；
     *   已含该行（重拍同一根）→ 不重复加。手动修改过的行不会被覆盖。
     */
    private void fillPartField(EditText et, String type, String text) {
        String cur = et.getText().toString().trim();
        if (cur.isEmpty()) {
            et.setText(text);
            return;
        }
        for (String line : cur.split("\n")) {
            if (line.trim().equals(text)) return;   // 重拍同一根：内容已存在
        }
        et.setText(cur + "\n" + text);
    }

    /** 统一构造候选 chip 按钮 [v1.04 间距优化] */
    private Button makeChip(String text, View.OnClickListener click) {
        Button chip = new Button(this);
        chip.setText(text);
        chip.setTextSize(12);
        chip.setPadding(dp(14), dp(3), dp(14), dp(3));
        chip.setMinWidth(0);
        chip.setMinHeight(0);
        chip.setMaxLines(2);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.setMargins(0, 0, dp(10), 0);
        chip.setLayoutParams(lp);
        chip.setOnClickListener(click);
        return chip;
    }

    private void appendNoteIfAbsent(String extra) {
        String note = etNote.getText().toString().trim();
        String val = extra.substring(extra.indexOf(':') + 1).trim();
        if (note.contains(val)) return;
        etNote.setText(note.isEmpty() ? extra : note + "\n" + extra);
    }

    // ---------- 上传 ----------

    private void startUpload() {
        String sn = etHostSn.getText().toString().trim();
        if (!sn.matches("[A-Za-z0-9_-]{1,64}")) {
            toast("主机编号必填（仅允许字母数字-_)）");
            return;
        }
        // [2026-09-29 PHOTO-OPTIONAL] 照片可选：识别到关键信息可直接保存（有照片则一并归档）
        String base = ApiClient.normalizeBase(Prefs.serverBase(this));
        if (base.isEmpty() || Prefs.password(this).isEmpty()) {
            toast("请先点右上角「⚙ 设置」配置服务器和访问密码");
            settingsSection.setVisibility(View.VISIBLE);
            scrollToBottom();
            return;
        }
        Map<String, String> fields = new LinkedHashMap<>();
        fields.put("sn", sn);
        fields.put("machineModel", etHostModel.getText().toString().trim());
        fields.put("vendor", vendorValue());
        fields.put("cpuModel", etCpuModel.getText().toString().trim());
        fields.put("cpuBatch", etCpuBatch.getText().toString().trim());
        fields.put("cpuCode", etCpuCode.getText().toString().trim());
        for (Map.Entry<String, String> e : PART_FIELDS.entrySet()) {
            EditText et = infoFields.get(e.getKey());
            fields.put(e.getValue(), et == null ? "" : et.getText().toString().trim());
        }
        fields.put("note", etNote.getText().toString().trim());

        // 上传前查询服务端已有档案，按 CPU 三元组（型号+批号+编号）查重
        setUploadText("查询档案中…");
        btnUpload.setEnabled(false);
        exec.execute(() -> {
            final String dup = findCpuDuplicate(fields);
            runOnUiThread(() -> {
                btnUpload.setEnabled(true);
                setUploadText("确认并上传");
                showConfirmDialog(base, fields, dup);
            });
        });
    }

    /** 上传确认弹窗（含 CPU 三元组查重结果提示，不阻止上传） */
    private void showConfirmDialog(String base, Map<String, String> fields, String dup) {
        int totalPhotos = 0;
        StringBuilder photoLine = new StringBuilder();
        for (String k : PART_KEYS) {
            int n = photos.get(k) == null ? 0 : photos.get(k).size();
            if (n > 0) {
                photoLine.append(PART_LABELS.get(k)).append(' ').append(n).append(" 张、");
                totalPhotos += n;
            }
        }
        if (totalPhotos == 0) photoLine.append("未拍照，仅保存识别参数");
        else photoLine.setLength(photoLine.length() - 1);

        StringBuilder msg = new StringBuilder();
        msg.append("主机编号: ").append(fields.get("sn")).append('\n');
        msg.append("主机型号: ").append(emptyDash(fields.get("machineModel"))).append('\n');
        if (!fields.get("vendor").isEmpty()) {
            msg.append("供应商: ").append(fields.get("vendor")).append('\n');
        }
        msg.append("CPU 型号: ").append(emptyDash(fields.get("cpuModel"))).append('\n');
        msg.append("CPU 批号: ").append(emptyDash(fields.get("cpuBatch"))).append('\n');
        msg.append("CPU 编号: ").append(emptyDash(fields.get("cpuCode"))).append('\n');
        for (Map.Entry<String, String> e : PART_FIELDS.entrySet()) {
            String v = fields.get(e.getValue());
            if (v != null && !v.isEmpty()) {
                msg.append(PART_LABELS.get(e.getKey())).append(": ").append(v).append('\n');
            }
        }
        msg.append("照片: ").append(photoLine).append('\n');
        msg.append("服务器: ").append(base).append('\n');
        if (dup != null) {
            msg.append('\n').append("⚠ ").append(dup).append('\n');
            msg.append("（若是 CPU 正常复用/换机，属正常现象）\n");
        }
        msg.append("\n确认无误后上传？（历史档案不会被覆盖，本次完整新增一条记录）");

        new AlertDialog.Builder(this)
                .setTitle("确认上传")
                .setMessage(msg)
                .setPositiveButton("确认上传", (d, w) -> doUpload(base, fields))
                .setNegativeButton("取消", null)
                .show();
    }

    /**
     * 同一 CPU 认定（用户定义）：CPU 型号 + 批号 + 编号 三者一致才算同一颗；
     * 任一字段为空则不比较。查重失败（网络/服务异常）不阻塞上传，返回 null。
     */
    private String findCpuDuplicate(Map<String, String> fields) {
        String m = fields.get("cpuModel");
        String b = fields.get("cpuBatch");
        String c = fields.get("cpuCode");
        if (m == null || b == null || c == null || m.isEmpty() || b.isEmpty() || c.isEmpty()) {
            return null;
        }
        try {
            String base = ApiClient.normalizeBase(Prefs.serverBase(this));
            String token = Prefs.token(this);
            String text;
            try {
                text = ApiClient.listRecords(base, token);
            } catch (ApiClient.AuthException e) {
                token = ApiClient.login(base, Prefs.password(this));
                Prefs.setToken(this, token);
                text = ApiClient.listRecords(base, token);
            }
            org.json.JSONArray recs = new org.json.JSONObject(text).optJSONArray("records");
            if (recs == null) return null;
            StringBuilder sb = new StringBuilder();
            int n = 0;
            for (int i = 0; i < recs.length(); i++) {
                org.json.JSONObject r = recs.optJSONObject(i);
                if (r == null) continue;
                if (m.equalsIgnoreCase(r.optString("cpuModel").trim())
                        && b.equalsIgnoreCase(r.optString("cpuBatch").trim())
                        && c.equalsIgnoreCase(r.optString("cpuCode").trim())) {
                    n++;
                    if (sb.length() > 0) sb.append("、");
                    sb.append(r.optString("sn")).append("（")
                      .append(r.optString("uploadedAt", "时间未知")).append("）");
                }
            }
            return n > 0 ? "该 CPU（型号+批号+编号 一致）已录入 " + n + " 次: " + sb : null;
        } catch (Exception e) {
            return null;
        }
    }

    private String emptyDash(String s) {
        return (s == null || s.isEmpty()) ? "—" : s;
    }

    private void doUpload(String base, Map<String, String> fields) {
        btnUpload.setEnabled(false);
        setUploadText("上传中…");
        exec.execute(() -> {
            try {
                String token = Prefs.token(this);
                try {
                    ApiClient.upload(base, token, fields, photos,
                            p -> runOnUiThread(() -> setUploadText("上传中 " + p + "%")));
                } catch (ApiClient.AuthException e) {
                    // token 过期 → 重新登录后重试一次
                    token = ApiClient.login(base, Prefs.password(this));
                    Prefs.setToken(this, token);
                    ApiClient.upload(base, token, fields, photos,
                            p -> runOnUiThread(() -> setUploadText("上传中 " + p + "%")));
                }
                runOnUiThread(() -> {
                    btnUpload.setEnabled(true);
                    setUploadText("确认并上传");
                    new AlertDialog.Builder(this)
                            .setTitle("上传成功")
                            .setMessage("已新增一条配件档案：\n" + fields.get("sn")
                                    + "\n\n可在网页「主机配件查询」中查看")
                            .setPositiveButton("好的，录入下一台", (d, w) -> clearForm())
                            .setNegativeButton("保留当前内容", null)
                            .show();
                });
            } catch (Exception e) {
                runOnUiThread(() -> {
                    btnUpload.setEnabled(true);
                    setUploadText("确认并上传");
                    String msg2 = e.getMessage() == null ? "未知错误" : e.getMessage();
                    if (msg2.contains("401") || msg2.contains("登录")) Prefs.clearToken(this);
                    new AlertDialog.Builder(this)
                            .setTitle("上传失败")
                            .setMessage(msg2)
                            .setPositiveButton("知道了", null)
                            .show();
                });
            }
        });
    }

    private void setUploadText(String text) {
        btnUpload.setText(text);
    }

    private void clearForm() {
        etHostSn.setText("");
        etHostModel.setText("");
        etCpuModel.setText("");
        etCpuBatch.setText("");
        etCpuCode.setText("");
        etNote.setText("");
        chipRow.removeAllViews();
        hostChipRow.removeAllViews();
        hostChipHint.setVisibility(View.GONE);
        hostModelChipRow.removeAllViews();
        hostModelChipHint.setVisibility(View.GONE);
        for (String k : PART_KEYS) {
            List<File> list = photos.get(k);
            if (list != null) list.clear();
        }
        photoCpuRow.removeAllViews();
        photoHostRow.removeAllViews();
        for (LinearLayout row : infoChipRows.values()) row.removeAllViews();
        for (LinearLayout row : infoThumbRows.values()) row.removeAllViews();
        for (EditText et : infoFields.values()) et.setText("");
    }

    // ---------- 工具 ----------

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private void toast(String msg) {
        Toast.makeText(this, msg, Toast.LENGTH_LONG).show();
    }
}
