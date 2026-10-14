package com.ldtools.parts;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.media.Image;
import android.os.Bundle;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.appcompat.app.AppCompatActivity;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.ImageAnalysis;
import androidx.camera.core.ImageProxy;
import androidx.camera.core.Preview;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.camera.view.PreviewView;
import androidx.core.content.ContextCompat;

import com.google.common.util.concurrent.ListenableFuture;
import com.google.mlkit.vision.barcode.BarcodeScanner;
import com.google.mlkit.vision.barcode.BarcodeScanning;
import com.google.mlkit.vision.barcode.common.Barcode;
import com.google.mlkit.vision.common.InputImage;

import java.util.concurrent.Executors;

/**
 * 扫码页 [v1.0 恢复，v1.01]：ML Kit Barcode 实时识别条形码 / 二维码 → 回传主机编号；
 * 无条码时点「拍标签识别」走主机照片 OCR（结果原样透传给 MainActivity）。
 */
public class ScanActivity extends AppCompatActivity {

    public static final String EXTRA_VALUE = "value";

    private BarcodeScanner scanner;
    private boolean hit = false;

    // 「没有条码？拍标签识别」→ CaptureActivity(type=host)，结果透传回 MainActivity
    private final ActivityResultLauncher<Intent> captureLauncher =
            registerForActivityResult(new ActivityResultContracts.StartActivityForResult(), result -> {
                if (result.getResultCode() != RESULT_OK || result.getData() == null) return;
                String path = result.getData().getStringExtra(CaptureActivity.EXTRA_PATH);
                if (path != null) {
                    setResult(RESULT_OK, result.getData());
                    finish();
                }
            });

    private final ActivityResultLauncher<String> permLauncher = registerForActivityResult(
            new ActivityResultContracts.RequestPermission(), granted -> {
                if (granted) {
                    startCamera();
                } else {
                    Toast.makeText(this, "需要相机权限才能扫码", Toast.LENGTH_LONG).show();
                    finish();
                }
            });

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_scan);
        scanner = BarcodeScanning.getClient();
        findViewById(R.id.btnPhotoLabel).setOnClickListener(v -> {
            Intent it = new Intent(this, CaptureActivity.class);
            it.putExtra(CaptureActivity.EXTRA_TYPE, "host");
            captureLauncher.launch(it);
        });
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
                PreviewView previewView = findViewById(R.id.previewViewScan);
                Preview preview = new Preview.Builder().build();
                preview.setSurfaceProvider(previewView.getSurfaceProvider());
                ImageAnalysis analysis = new ImageAnalysis.Builder()
                        .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                        .build();
                analysis.setAnalyzer(Executors.newSingleThreadExecutor(),
                        imageProxy -> analyze(imageProxy));
                provider.unbindAll();
                provider.bindToLifecycle(this, CameraSelector.DEFAULT_BACK_CAMERA,
                        preview, analysis);
            } catch (Exception e) {
                Toast.makeText(this, "相机启动失败: " + e.getMessage(), Toast.LENGTH_LONG).show();
                finish();
            }
        }, ContextCompat.getMainExecutor(this));
    }

    private void analyze(ImageProxy imageProxy) {
        Image mediaImage = imageProxy.getImage();
        if (mediaImage == null) {
            imageProxy.close();
            return;
        }
        InputImage image = InputImage.fromMediaImage(mediaImage,
                imageProxy.getImageInfo().getRotationDegrees());
        scanner.process(image)
                .addOnSuccessListener(barcodes -> {
                    for (Barcode b : barcodes) {
                        String v = b.getRawValue();
                        if (v != null && !v.trim().isEmpty()) {
                            onHit(v.trim());
                            break;
                        }
                    }
                })
                .addOnFailureListener(e -> { })
                .addOnCompleteListener(t -> imageProxy.close());
    }

    private void onHit(String value) {
        if (hit) return;
        hit = true;
        runOnUiThread(() -> {
            Toast.makeText(this, "识别到: " + value, Toast.LENGTH_SHORT).show();
            Intent data = new Intent();
            data.putExtra(EXTRA_VALUE, value);
            setResult(RESULT_OK, data);
            finish();
        });
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (scanner != null) {
            scanner.close();
            scanner = null;
        }
    }
}
