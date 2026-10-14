package com.ldtools.parts;

import android.content.Context;
import android.graphics.Matrix;
import android.graphics.PointF;
import android.graphics.drawable.Drawable;
import android.util.AttributeSet;
import android.view.GestureDetector;
import android.view.MotionEvent;
import android.view.ScaleGestureDetector;

import androidx.appcompat.widget.AppCompatImageView;

/**
 * [v1.01] 可缩放照片预览：
 *   双指捏合缩放（1x ~ 8x）、放大后单指拖动平移、双击在 1x / 2.5x 间切换。
 */
public class ZoomImageView extends AppCompatImageView {

    private static final float MIN_SCALE = 1f;
    private static final float MAX_SCALE = 8f;
    private static final float DOUBLE_TAP_SCALE = 2.5f;

    private final Matrix matrix = new Matrix();
    private final float[] values = new float[9];
    private final PointF last = new PointF();

    /** 基准 fit 缩放比例；saveScale 为当前缩放 / 基准 */
    private float fitScale = 1f;
    private float saveScale = 1f;
    /** fit 状态下图片实际显示宽高（像素） */
    private float fitW, fitH;
    private int viewWidth, viewHeight;

    private final ScaleGestureDetector scaleDetector;
    private final GestureDetector gestureDetector;

    public ZoomImageView(Context context) {
        this(context, null);
    }

    public ZoomImageView(Context context, AttributeSet attrs) {
        super(context, attrs);
        super.setScaleType(ScaleType.MATRIX);
        scaleDetector = new ScaleGestureDetector(context, new ScaleListener());
        gestureDetector = new GestureDetector(context, new GestureListener());
    }

    @Override
    public void setImageDrawable(Drawable drawable) {
        super.setImageDrawable(drawable);
        resetFit();
    }

    @Override
    protected void onSizeChanged(int w, int h, int oldw, int oldh) {
        super.onSizeChanged(w, h, oldw, oldh);
        viewWidth = w;
        viewHeight = h;
        if (getDrawable() != null) resetFit();
    }

    /** 初始/重置：fit-center 居中显示 */
    private void resetFit() {
        Drawable d = getDrawable();
        if (d == null || viewWidth == 0 || viewHeight == 0
                || d.getIntrinsicWidth() <= 0 || d.getIntrinsicHeight() <= 0) return;
        fitScale = Math.min(viewWidth / (float) d.getIntrinsicWidth(),
                viewHeight / (float) d.getIntrinsicHeight());
        fitW = d.getIntrinsicWidth() * fitScale;
        fitH = d.getIntrinsicHeight() * fitScale;
        saveScale = 1f;
        matrix.reset();
        matrix.postScale(fitScale, fitScale);
        matrix.postTranslate((viewWidth - fitW) / 2f, (viewHeight - fitH) / 2f);
        setImageMatrix(matrix);
    }

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        scaleDetector.onTouchEvent(event);
        gestureDetector.onTouchEvent(event);

        if (!scaleDetector.isInProgress()) {
            if (event.getActionMasked() == MotionEvent.ACTION_DOWN) {
                last.set(event.getX(), event.getY());
            } else if (event.getActionMasked() == MotionEvent.ACTION_MOVE) {
                float dx = event.getX() - last.x;
                float dy = event.getY() - last.y;
                translate(dx, dy);
                last.set(event.getX(), event.getY());
            }
        }
        return true;
    }

    /** 拖动平移（放大超出视野时贴边约束；未超出时保持居中） */
    private void translate(float dx, float dy) {
        matrix.getValues(values);
        float transX = values[Matrix.MTRANS_X];
        float transY = values[Matrix.MTRANS_Y];
        float imgW = fitW * saveScale;
        float imgH = fitH * saveScale;

        if (imgW >= viewWidth) transX = Math.min(Math.max(transX + dx, viewWidth - imgW), 0);
        else transX = (viewWidth - imgW) / 2f;
        if (imgH >= viewHeight) transY = Math.min(Math.max(transY + dy, viewHeight - imgH), 0);
        else transY = (viewHeight - imgH) / 2f;

        values[Matrix.MTRANS_X] = transX;
        values[Matrix.MTRANS_Y] = transY;
        matrix.setValues(values);
        setImageMatrix(matrix);
    }

    private class ScaleListener extends ScaleGestureDetector.SimpleOnScaleGestureListener {
        @Override
        public boolean onScale(ScaleGestureDetector detector) {
            float factor = detector.getScaleFactor();
            float newScale = Math.min(Math.max(saveScale * factor, MIN_SCALE), MAX_SCALE);
            if (newScale == saveScale) return true;
            factor = newScale / saveScale;
            saveScale = newScale;
            matrix.postScale(factor, factor, detector.getFocusX(), detector.getFocusY());
            clampTranslation();
            setImageMatrix(matrix);
            return true;
        }
    }

    /** 缩放后把图片拉回允许范围（小于视窗居中，超出边界贴边） */
    private void clampTranslation() {
        matrix.getValues(values);
        float transX = values[Matrix.MTRANS_X];
        float transY = values[Matrix.MTRANS_Y];
        float imgW = fitW * saveScale;
        float imgH = fitH * saveScale;

        if (imgW >= viewWidth) transX = Math.min(Math.max(transX, viewWidth - imgW), 0);
        else transX = (viewWidth - imgW) / 2f;
        if (imgH >= viewHeight) transY = Math.min(Math.max(transY, viewHeight - imgH), 0);
        else transY = (viewHeight - imgH) / 2f;

        values[Matrix.MTRANS_X] = transX;
        values[Matrix.MTRANS_Y] = transY;
        matrix.setValues(values);
    }

    private class GestureListener extends GestureDetector.SimpleOnGestureListener {
        @Override
        public boolean onDoubleTap(MotionEvent e) {
            float target = saveScale < DOUBLE_TAP_SCALE ? DOUBLE_TAP_SCALE : MIN_SCALE;
            float factor = target / saveScale;
            saveScale = target;
            matrix.postScale(factor, factor, e.getX(), e.getY());
            clampTranslation();
            setImageMatrix(matrix);
            return true;
        }
    }
}
