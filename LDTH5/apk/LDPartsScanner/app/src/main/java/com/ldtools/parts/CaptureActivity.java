package com.ldtools.parts;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.view.View;
import android.widget.Button;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.appcompat.app.AppCompatActivity;
import androidx.camera.core.Camera;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.ImageCapture;
import androidx.camera.core.ImageCaptureException;
import androidx.camera.core.Preview;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.camera.view.PreviewView;
import androidx.core.content.ContextCompat;

import com.google.common.util.concurrent.ListenableFuture;

import java.io.File;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/**
 * 相机拍照页：CameraX 取景 + 拍照，照片落到应用专属目录后把路径传回 MainActivity。
 * intent extra：EXTRA_TYPE = "cpu" | "host"（只用于界面提示，也随结果回传）。
 */
public class CaptureActivity extends AppCompatActivity {

    public static final String EXTRA_TYPE = "type";
    public static final String EXTRA_PATH = "path";

    private ImageCapture imageCapture;
    private Camera camera;
    private boolean torchOn = false;
    private String type = "cpu";

    private final ActivityResultLauncher<String> permLauncher = registerForActivityResult(
            new ActivityResultContracts.RequestPermission(),
            granted -> {
                if (granted) {
                    startCamera();
                } else {
                    Toast.makeText(this, "需要相机权限才能拍照", Toast.LENGTH_LONG).show();
                    finish();
                }
            });

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_capture);

        type = getIntent().getStringExtra(EXTRA_TYPE);
        if (type == null) type = "cpu";
        // 白名单：未知类型按其他配件处理 [v1.02 去掉网卡]
        if (!java.util.Arrays.asList("cpu", "host", "ram", "ssd", "other").contains(type)) {
            type = "other";
        }

        TextView hint = findViewById(R.id.captureHint);
        String tip;
        switch (type) {
            case "cpu":  tip = "拍摄类型：CPU 照片（对准 CPU 丝印文字）"; break;
            case "host": tip = "拍摄类型：主机照片（对准标签上的出厂编号/批号）"; break;
            case "ram":  tip = "拍摄类型：内存（对准标签 / 颗粒丝印）"; break;
            case "ssd":  tip = "拍摄类型：固态硬盘（对准标签）"; break;
            default:     tip = "拍摄类型：其他配件（对准标签）"; break;
        }
        hint.setText(tip);

        Button btnTorch = findViewById(R.id.btnTorch);
        Button btnShutter = findViewById(R.id.btnShutter);
        Button btnCancel = findViewById(R.id.btnCancel);
        btnTorch.setOnClickListener(v -> toggleTorch());
        btnShutter.setOnClickListener(v -> takePhoto());
        btnCancel.setOnClickListener(v -> finish());

        // [v1.15] CPU 取景框：身份证式对齐引导（长方形=12代+/Ultra，正方形=旧款 LGA1200/1151）。
        //   CPU 对齐框内后位置/大小标准化，后端边缘窄带识别编号的命中率大幅提升。
        if ("cpu".equals(type)) {
            hint.setText("将 CPU 对齐取景框（顶盖文字保持水平，编号贴边也能识别）");
            GuideOverlayView overlay = findViewById(R.id.guideOverlay);
            Button btnRect = findViewById(R.id.btnShapeRect);
            Button btnSquare = findViewById(R.id.btnShapeSquare);
            btnRect.setOnClickListener(v -> {
                overlay.setSquare(false);
                btnRect.setBackgroundTintList(android.content.res.ColorStateList.valueOf(0xFF33BB77));
                btnSquare.setBackgroundTintList(android.content.res.ColorStateList.valueOf(0xFF556655));
            });
            btnSquare.setOnClickListener(v -> {
                overlay.setSquare(true);
                btnSquare.setBackgroundTintList(android.content.res.ColorStateList.valueOf(0xFF33BB77));
                btnRect.setBackgroundTintList(android.content.res.ColorStateList.valueOf(0xFF556655));
            });
        } else {
            findViewById(R.id.shapeSwitchRow).setVisibility(View.GONE);
            findViewById(R.id.guideOverlay).setVisibility(View.GONE);
        }

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_GRANTED) {
            startCamera();
        } else {
            permLauncher.launch(Manifest.permission.CAMERA);
        }
    }

    private void startCamera() {
        ListenableFuture<ProcessCameraProvider> future = ProcessCameraProvider.getInstance(this);
        future.addListener(() -> {
            try {
                ProcessCameraProvider provider = future.get();
                PreviewView previewView = findViewById(R.id.previewView);
                Preview preview = new Preview.Builder().build();
                preview.setSurfaceProvider(previewView.getSurfaceProvider());
                imageCapture = new ImageCapture.Builder()
                        .setCaptureMode(ImageCapture.CAPTURE_MODE_MAXIMIZE_QUALITY)
                        .build();
                provider.unbindAll();
                camera = provider.bindToLifecycle(this, CameraSelector.DEFAULT_BACK_CAMERA,
                        preview, imageCapture);
            } catch (Exception e) {
                Toast.makeText(this, "相机启动失败: " + e.getMessage(), Toast.LENGTH_LONG).show();
                finish();
            }
        }, ContextCompat.getMainExecutor(this));
    }

    private void toggleTorch() {
        if (camera == null) return;
        torchOn = !torchOn;
        camera.getCameraControl().enableTorch(torchOn);
        ((Button) findViewById(R.id.btnTorch)).setText(torchOn ? "☀ 关灯" : "☀ 手电");
    }

    private void takePhoto() {
        if (imageCapture == null) return;
        File dir = new File(getExternalFilesDir(Environment.DIRECTORY_PICTURES), "parts");
        if (!dir.exists() && !dir.mkdirs()) {
            Toast.makeText(this, "无法创建照片目录", Toast.LENGTH_SHORT).show();
            return;
        }
        String ts = new SimpleDateFormat("yyyyMMdd_HHmmss_SSS", Locale.US).format(new Date());
        File out = new File(dir, "cap_" + type + "_" + ts + ".jpg");
        ImageCapture.OutputFileOptions opts =
                new ImageCapture.OutputFileOptions.Builder(out).build();
        imageCapture.takePicture(opts, ContextCompat.getMainExecutor(this),
                new ImageCapture.OnImageSavedCallback() {
                    @Override
                    public void onImageSaved(@NonNull ImageCapture.OutputFileResults results) {
                        Intent data = new Intent();
                        data.putExtra(EXTRA_PATH, out.getAbsolutePath());
                        data.putExtra(EXTRA_TYPE, type);
                        setResult(RESULT_OK, data);
                        finish();
                    }

                    @Override
                    public void onError(@NonNull ImageCaptureException exc) {
                        Toast.makeText(CaptureActivity.this,
                                "拍照失败: " + exc.getMessage(), Toast.LENGTH_SHORT).show();
                    }
                });
    }
}
