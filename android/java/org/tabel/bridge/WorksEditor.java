package org.tabel.bridge;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.text.InputType;
import android.util.Log;
import android.view.ContextThemeWrapper;
import android.view.Gravity;
import android.view.WindowManager;
import android.view.inputmethod.InputMethodManager;
import android.widget.EditText;
import org.json.JSONObject;
import java.util.concurrent.ConcurrentLinkedQueue;

/** Native listeners stay in Java; Python only polls immutable JSON results. */
public final class WorksEditor {
    private static final ConcurrentLinkedQueue<String> results = new ConcurrentLinkedQueue<>();
    // Accessed exclusively on the Android UI thread.
    private static AlertDialog active;
    private WorksEditor() {}

    private static void emit(String token, String status, String text) {
        try {
            JSONObject result = new JSONObject();
            result.put("token", token);
            result.put("status", status);
            result.put("text", text);
            results.offer(result.toString());
        } catch (Exception ex) {
            Log.e("TabelEditor", "Cannot encode result", ex);
        }
    }

    public static String poll() {
        String value = results.poll();
        return value == null ? "" : value;
    }

    public static void open(final Activity activity, final String title,
                            final String text, final String token) {
        activity.runOnUiThread(new Runnable() {
            @Override public void run() {
                if (active != null) {
                    emit(token, "error", "Editor is already open");
                    return;
                }
                final boolean[] completed = {false};
                try {
                    if (activity.isFinishing() || activity.isDestroyed()) {
                        throw new IllegalStateException("Activity is not available");
                    }
                    Context context = new ContextThemeWrapper(activity,
                            android.R.style.Theme_Material_Light_Dialog_Alert);
                    final EditText edit = new EditText(context);
                    edit.setInputType(InputType.TYPE_CLASS_TEXT
                            | InputType.TYPE_TEXT_FLAG_MULTI_LINE
                            | InputType.TYPE_TEXT_FLAG_AUTO_CORRECT
                            | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
                    edit.setSingleLine(false);
                    edit.setMinLines(5);
                    edit.setMaxLines(12);
                    edit.setGravity(Gravity.TOP | Gravity.START);
                    int pad = (int)(16 * activity.getResources().getDisplayMetrics().density);
                    edit.setPadding(pad, pad, pad, pad);
                    edit.setText(text);
                    edit.setSelection(edit.length());
                    final AlertDialog dialog = new AlertDialog.Builder(context)
                            .setTitle(title).setView(edit)
                            .setPositiveButton("Готово", new DialogInterface.OnClickListener() {
                                @Override public void onClick(DialogInterface d, int which) {
                                    try {
                                        String value = edit.getText().toString();
                                        emit(token, "ok", value);
                                    } catch (Exception ex) {
                                        Log.e("TabelEditor", "Read text failed", ex);
                                        emit(token, "error", ex.toString());
                                    } finally { completed[0] = true; }
                                }
                            })
                            .setNegativeButton("Отмена", null).create();
                    active = dialog;
                    dialog.setCanceledOnTouchOutside(false);
                    dialog.setOnDismissListener(new DialogInterface.OnDismissListener() {
                        @Override public void onDismiss(DialogInterface d) {
                            if (!completed[0]) emit(token, "cancel", "");
                            completed[0] = true;
                            if (active == dialog) active = null;
                        }
                    });
                    dialog.getWindow().setSoftInputMode(
                            WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_VISIBLE
                            | WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
                    dialog.show();
                    edit.requestFocus();
                    edit.post(new Runnable() {
                        @Override public void run() {
                            if (active != dialog || !dialog.isShowing()) return;
                            try {
                                InputMethodManager ime = (InputMethodManager)
                                        activity.getSystemService(Context.INPUT_METHOD_SERVICE);
                                if (ime != null) ime.showSoftInput(edit, InputMethodManager.SHOW_IMPLICIT);
                            } catch (Exception ex) {
                                // The user can still focus the field manually.
                                Log.w("TabelEditor", "Keyboard request failed", ex);
                            }
                        }
                    });
                } catch (Exception ex) {
                    Log.e("TabelEditor", "Open failed", ex);
                    completed[0] = true;
                    if (active != null) {
                        try { active.dismiss(); } catch (Exception ignored) {}
                        active = null;
                    }
                    emit(token, "error", ex.toString());
                }
            }
        });
    }

    public static void close(final Activity activity) {
        activity.runOnUiThread(new Runnable() {
            @Override public void run() {
                if (active != null) {
                    try { active.dismiss(); } catch (Exception ex) {
                        Log.w("TabelEditor", "Dismiss failed", ex);
                        active = null;
                    }
                }
            }
        });
    }
}
