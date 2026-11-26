package org.movinite.app;

import com.google.crypto.tink.Aead;

import java.io.Closeable;
import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.ByteBuffer;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;

/**
 * The encrypted file format (".mvc"): a 16-byte header ("MVC1", chunk size, plaintext length), then the plaintext in
 * 1 MiB chunks, each sealed with AES-256-GCM (Tink AEAD). The associated data binds every chunk to its download id,
 * part ("video", "sub-e0" ...), index and total length, so chunks can't be swapped, reordered or truncated unnoticed.
 * Fixed-size chunks give random access for seeking in the player.
 */
public final class ChunkStore {
    private ChunkStore() {}

    static byte[] header(long plainLen) {
        return ByteBuffer.allocate(Lic.HEADER).put(new byte[]{'M', 'V', 'C', '1'}).putInt(Lic.CHUNK).putLong(plainLen).array();
    }

    /** Appends chunks; reopen with resume to continue a partial download at the last whole chunk. */
    public static final class Writer implements Closeable {
        private final RandomAccessFile f;
        private final Aead aead;
        private final long gid, plainLen;
        private final String part;
        private final byte[] buf = new byte[Lic.CHUNK];
        private int fill = 0;
        private long index;
        private final MessageDigest sha;

        /** start = whole chunks already in the file (Lic.completeChunks); their plaintext is re-hashed for the checksum */
        public Writer(File file, Aead aead, long gid, String part, long plainLen, long start) throws IOException, GeneralSecurityException {
            this.aead = aead; this.gid = gid; this.part = part; this.plainLen = plainLen;
            try { sha = MessageDigest.getInstance("SHA-256"); } catch (Exception e) { throw new IOException(e); }
            f = new RandomAccessFile(file, "rw");
            if (start <= 0 || f.length() < Lic.HEADER) {
                f.setLength(0); f.write(header(plainLen)); index = 0;
            } else {
                try (Reader r = new Reader(file, aead, gid, part)) {
                    if (r.plainLen != plainLen) throw new IOException("partial file is for another size");
                    for (long i = 0; i < start; i++) sha.update(r.chunk(i));
                }
                index = start;
                f.setLength(Lic.chunkOffset(start));
                f.seek(f.length());
            }
        }

        public long position() { return index * (long) Lic.CHUNK + fill; }

        public void write(byte[] b, int off, int len) throws IOException, GeneralSecurityException {
            while (len > 0) {
                int want = Lic.chunkLen(plainLen, index) - fill;
                if (want <= 0) throw new IOException("more data than expected");
                int n = Math.min(want, len);
                System.arraycopy(b, off, buf, fill, n);
                fill += n; off += n; len -= n;
                if (fill == Lic.chunkLen(plainLen, index)) flushChunk();
            }
        }

        private void flushChunk() throws IOException, GeneralSecurityException {
            byte[] plain = fill == buf.length ? buf : java.util.Arrays.copyOf(buf, fill);
            sha.update(plain, 0, fill);
            f.write(aead.encrypt(plain, Lic.aad(gid, part, index, plainLen)));
            index++; fill = 0;
        }

        public boolean complete() { return index >= Lic.chunks(plainLen) && fill == 0; }

        /** sha256 hex of all the plaintext (only meaningful once complete) */
        public String sha256() { try { return Lic.hex(((MessageDigest) sha.clone()).digest()); } catch (CloneNotSupportedException e) { throw new IllegalStateException(e); } }

        public void sync() throws IOException { f.getFD().sync(); }

        @Override public void close() throws IOException { f.close(); }
    }

    /** Random-access decryption, one chunk cached. */
    public static final class Reader implements Closeable {
        private final RandomAccessFile f;
        private final Aead aead;
        private final long gid;
        private final String part;
        public final long plainLen;
        private long cachedIndex = -1;
        private byte[] cached;

        public Reader(File file, Aead aead, long gid, String part) throws IOException {
            this.aead = aead; this.gid = gid; this.part = part;
            f = new RandomAccessFile(file, "r");
            byte[] h = new byte[Lic.HEADER];
            f.readFully(h);
            ByteBuffer bb = ByteBuffer.wrap(h);
            if (bb.get() != 'M' || bb.get() != 'V' || bb.get() != 'C' || bb.get() != '1') { f.close(); throw new IOException("not a Movinite download"); }
            if (bb.getInt() != Lic.CHUNK) { f.close(); throw new IOException("unsupported chunk size"); }
            plainLen = bb.getLong();
        }

        public byte[] chunk(long i) throws IOException {
            if (i == cachedIndex) return cached;
            int len = Lic.chunkLen(plainLen, i);
            if (len <= 0) throw new IOException("past the end");
            byte[] ct = new byte[len + Lic.OVERHEAD];
            f.seek(Lic.chunkOffset(i));
            f.readFully(ct);
            try { cached = aead.decrypt(ct, Lic.aad(gid, part, i, plainLen)); }
            catch (GeneralSecurityException e) { throw new IOException("the download is damaged or was changed (chunk " + i + ")"); }
            cachedIndex = i;
            return cached;
        }

        /** reads up to len bytes at a plaintext position; -1 at the end */
        public int read(long pos, byte[] out, int off, int len) throws IOException {
            if (pos >= plainLen) return -1;
            long i = pos / Lic.CHUNK;
            int in = (int) (pos % Lic.CHUNK);
            byte[] c = chunk(i);
            int n = Math.min(len, c.length - in);
            System.arraycopy(c, in, out, off, n);
            return n;
        }

        public byte[] readAll() throws IOException {
            if (plainLen > 64L * 1024 * 1024) throw new IOException("too big to read at once");
            byte[] out = new byte[(int) plainLen];
            int p = 0;
            while (p < out.length) { int n = read(p, out, p, out.length - p); if (n < 0) break; p += n; }
            return out;
        }

        @Override public void close() throws IOException { f.close(); }
    }

    /** small whole files (subtitles): seal in one go */
    public static void writeSmall(File file, Aead aead, long gid, String part, byte[] data) throws IOException, GeneralSecurityException {
        File tmp = new File(file.getPath() + ".part");
        try (Writer w = new Writer(tmp, aead, gid, part, data.length, 0)) { w.write(data, 0, data.length); }
        if (!tmp.renameTo(file)) throw new IOException("couldn't save " + file.getName());
    }
}
