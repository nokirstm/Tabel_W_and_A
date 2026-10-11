package org.tabel.bridge;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.text.InputType;
import android.view.Gravity;
import android.view.inputmethod.InputMethodManager;
import android.widget.EditText;
import android.widget.LinearLayout;

import org.kivy.android.PythonActivity;

import java.util.concurrent.LinkedBlockingQueue;

public class FieldEditor {

    private static final LinkedBlockingQueue<String> results = new LinkedBlockingQueue<>();

    public static String poll(long timeoutMs) {
        try {
            return results.poll(timeoutMs, java.util.concurrent.TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            return null;
        }
    }

    public static void open(final String token, final String title,
                            final String current, final String inputKind) {
        final Activity activity = PythonActivity.mActivity;
        if (activity == null) {
            results.offer("{\"token\":\"" + token + "\",\"status\":\"error\",\"text\":\"no activity\"}");
            return;
        }
        activity.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                try {
                    EditText edit = new EditText(activity);

                    if ("number".equals(inputKind)) {
                        edit.setInputType(InputType.TYPE_CLASS_NUMBER);
                    } else {
                        edit.setInputType(
                            InputType.TYPE_CLASS_TEXT
                            | InputType.TYPE_TEXT_FLAG_AUTO_CORRECT
                            | InputType.TYPE_TEXT_FLAG_CAP_WORDS
                        );
                    }
                    edit.setSingleLine(true);
                    edit.setText(current != null ? current : "");
                    edit.setSelection(edit.getText().length());

                    // Отступы внутри поля
                    int pad = (int) (16 * activity.getResources().getDisplayMetrics().density);
                    edit.setPadding(pad, pad, pad, pad);

                    LinearLayout container = new LinearLayout(activity);
                    container.setOrientation(LinearLayout.VERTICAL);
                    int cPad = (int) (12 * activity.getResources().getDisplayMetrics().density);
                    container.setPadding(cPad, cPad, cPad, 0);
                    container.addView(edit);

                    AlertDialog dialog = new AlertDialog.Builder(activity)
                        .setTitle(title)
                        .setView(container)
                        .setPositiveButton("Готово", new DialogInterface.OnClickListener() {
                            @Override
                            public void onClick(DialogInterface d, int which) {
                                String val = edit.getText().toString();
                                String json = "{\"token\":\"" + token
                                    + "\",\"status\":\"ok\",\"text\":\""
                                    + escapeJson(val) + "\"}";
                                results.offer(json);
                            }
                        })
                        .setNegativeButton("Отмена", new DialogInterface.OnClickListener() {
                            @Override
                            public void onClick(DialogInterface d, int which) {
                                String json = "{\"token\":\"" + token
                                    + "\",\"status\":\"cancel\",\"text\":\"\"}";
                                results.offer(json);
                            }
                        })
                        .setOnDismissListener(new DialogInterface.OnDismissListener() {
                            @Override
                            public void onDismiss(DialogInterface d) {
                                // Прячем клавиатуру при закрытии
                                InputMethodManager imm = (InputMethodManager)
                                    activity.getSystemService(Activity.INPUT_METHOD_SERVICE);
                                if (imm != null && activity.getCurrentFocus() != null) {
                                    imm.hideSoftInputFromWindow(
                                        activity.getCurrentFocus().getWindowToken(), 0);
                                }
                            }
                        })
                        .create();

                    dialog.getWindow().setSoftInputMode(
                        android.view.WindowManager.LayoutParams.SOFT_INPUT_STATE_VISIBLE
                        | android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
                    dialog.show();
                    edit.requestFocus();

                } catch (Exception ex) {
                    String json = "{\"token\":\"" + token
                        + "\",\"status\":\"error\",\"text\":\""
                        + escapeJson(ex.getMessage()) + "\"}";
                    results.offer(json);
                }
            }
        });
    }

    private static String escapeJson(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t");
    }
}
