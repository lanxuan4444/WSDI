package com.ldtools.parts;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.util.AttributeSet;
import android.view.View;

/**
 * [v1.15] CPU 拍摄取景框（身份证式对齐引导）：
 *   长方形 = 12/13/14 代 + Core Ultra（LGA1700/1851 顶盖约 1:1.2）
 *   正方形 = 旧款（LGA1200/1151/1150 等顶盖约 1:1）
 * 用户把 CPU 对齐框内 → 位置/大小标准化，后端按固定区域裁剪边缘窄带识别编号。
 */
public class GuideOverlayView extends View {

    private boolean square = false;   // true=正方形（旧款）
    private final Paint maskPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint borderPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint cornerPaint = new Paint(Paint.ANTI_ALIAS_FLAG);

    public GuideOverlayView(Context context, AttributeSet attrs) {
        super(context, attrs);
        maskPaint.setColor(Color.argb(110, 0, 0, 0));          // 框外半透明遮罩
        maskPaint.setStyle(Paint.Style.FILL);
        borderPaint.setColor(0xFF4ADE80);                        // 绿色边框（对齐提示色）
        borderPaint.setStyle(Paint.Style.STROKE);
        borderPaint.setStrokeWidth(dp(2.5f));
        cornerPaint.setColor(0xFF4ADE80);
        cornerPaint.setStyle(Paint.Style.STROKE);
        cornerPaint.setStrokeWidth(dp(5));
    }

    /** true = 正方形（旧款 LGA1200/1151），false = 长方形（12代+/Ultra） */
    public void setSquare(boolean square) {
        this.square = square;
        invalidate();
    }

    /** 取景框区域（供提示文字避让等使用） */
    public RectF getBox() {
        int w = getWidth(), h = getHeight();
        if (w == 0 || h == 0) return new RectF();
        float boxW = w * 0.74f;
        float boxH = square ? boxW : boxW * 1.2f;   // LGA1700 顶盖 37.5×45mm ≈ 1:1.2
        float left = (w - boxW) / 2f;
        float top = (h - boxH) / 2f * 0.9f;         // 略偏上（下方有按钮）
        return new RectF(left, top, left + boxW, top + boxH);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        RectF box = getBox();
        if (box.isEmpty()) return;
        // 框外遮罩：全屏 - 框
        Path mask = new Path();
        mask.addRect(0, 0, getWidth(), getHeight(), Path.Direction.CW);
        Path hole = new Path();
        hole.addRect(box, Path.Direction.CW);
        mask.op(hole, Path.Op.DIFFERENCE);
        canvas.drawPath(mask, maskPaint);
        // 边框
        canvas.drawRect(box, borderPaint);
        // 四角加粗标记（取景对齐感）
        float len = Math.min(box.width(), box.height()) * 0.12f;
        float cx = len, cy = len;
        Path c1 = new Path(); c1.moveTo(box.left, box.top + cy); c1.lineTo(box.left, box.top); c1.lineTo(box.left + cx, box.top);
        Path c2 = new Path(); c2.moveTo(box.right - cx, box.top); c2.lineTo(box.right, box.top); c2.lineTo(box.right, box.top + cy);
        Path c3 = new Path(); c3.moveTo(box.right, box.bottom - cy); c3.lineTo(box.right, box.bottom); c3.lineTo(box.right - cx, box.bottom);
        Path c4 = new Path(); c4.moveTo(box.left + cx, box.bottom); c4.lineTo(box.left, box.bottom); c4.lineTo(box.left, box.bottom - cy);
        canvas.drawPath(c1, cornerPaint);
        canvas.drawPath(c2, cornerPaint);
        canvas.drawPath(c3, cornerPaint);
        canvas.drawPath(c4, cornerPaint);
    }

    private float dp(float v) {
        return v * getResources().getDisplayMetrics().density;
    }
}
