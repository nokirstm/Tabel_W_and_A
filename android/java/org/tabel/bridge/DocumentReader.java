package org.tabel.bridge;

import android.app.Activity;
import android.net.Uri;
import java.io.InputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;

/** A bounded read using the SAF URI, never interpreting it as a filesystem path. */
public final class DocumentReader {
    private DocumentReader() {}
    public static String read(Activity activity, String uri, int limit) throws IOException {
        try (InputStream input = activity.getContentResolver().openInputStream(Uri.parse(uri))) {
            if (input == null) throw new IOException("Document cannot be opened");
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            byte[] buffer = new byte[8192];
            int count;
            while ((count = input.read(buffer)) != -1) {
                if (output.size() + count > limit) throw new IOException("Document exceeds size limit");
                output.write(buffer, 0, count);
            }
            // Reject corrupt UTF-8 instead of silently replacing user's text.
            return java.nio.charset.StandardCharsets.UTF_8.newDecoder()
                    .onMalformedInput(java.nio.charset.CodingErrorAction.REPORT)
                    .onUnmappableCharacter(java.nio.charset.CodingErrorAction.REPORT)
                    .decode(java.nio.ByteBuffer.wrap(output.toByteArray())).toString();
        }
    }
}
