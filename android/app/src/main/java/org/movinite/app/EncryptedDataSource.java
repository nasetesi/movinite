package org.movinite.app;

import android.net.Uri;

import androidx.annotation.Nullable;
import androidx.media3.common.C;
import androidx.media3.common.util.UnstableApi;
import androidx.media3.datasource.BaseDataSource;
import androidx.media3.datasource.DataSource;
import androidx.media3.datasource.DataSpec;

import java.io.File;
import java.io.IOException;

/** Media3 DataSource for "mvo://<gid>/<part>": decrypts the .mvc store on the fly for the offline player. */
@UnstableApi
final class EncryptedDataSource extends BaseDataSource {
    private final Offline off;
    private ChunkStore.Reader reader;
    private Uri uri;
    private long pos, left;

    EncryptedDataSource(Offline off) { super(false); this.off = off; }

    static Uri uri(long gid, String part) { return Uri.parse("mvo://" + gid + "/" + part); }

    @Override
    public long open(DataSpec spec) throws IOException {
        uri = spec.uri;
        transferInitializing(spec);
        long gid;
        try { gid = Long.parseLong(uri.getHost()); } catch (Exception e) { throw new IOException("bad offline address"); }
        String part = uri.getPath() == null ? "video" : uri.getPath().replace("/", "");
        File f = off.partFile(gid, part);
        try { reader = new ChunkStore.Reader(f, off.aead(), gid, part); }
        catch (IOException e) { throw e; }
        catch (Exception e) { throw new IOException("can't open the encrypted download", e); }
        pos = spec.position;
        if (pos > reader.plainLen) throw new IOException("seek past the end");
        left = spec.length != C.LENGTH_UNSET ? Math.min(spec.length, reader.plainLen - pos) : reader.plainLen - pos;
        transferStarted(spec);
        return left;
    }

    @Override
    public int read(byte[] buf, int off, int len) throws IOException {
        if (len == 0) return 0;
        if (left <= 0) return C.RESULT_END_OF_INPUT;
        int n = reader.read(pos, buf, off, (int) Math.min(len, left));
        if (n < 0) return C.RESULT_END_OF_INPUT;
        pos += n; left -= n;
        bytesTransferred(n);
        return n;
    }

    @Nullable @Override public Uri getUri() { return uri; }

    @Override
    public void close() throws IOException {
        if (reader != null) {
            try { reader.close(); } finally { reader = null; transferEnded(); }
        }
        uri = null;
    }

    static final class Factory implements DataSource.Factory {
        private final Offline off;
        Factory(Offline off) { this.off = off; }
        @Override public DataSource createDataSource() { return new EncryptedDataSource(off); }
    }
}
