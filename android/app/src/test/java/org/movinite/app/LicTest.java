package org.movinite.app;

import static org.junit.Assert.*;

import com.google.crypto.tink.Aead;
import com.google.crypto.tink.KeyTemplates;
import com.google.crypto.tink.KeysetHandle;
import com.google.crypto.tink.aead.AeadConfig;

import org.junit.Test;

import java.io.File;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Random;

/** JVM tests for the offline core. Token vectors were made with the server's own format (test-only key, not a real server's). */
public class LicTest {
    static final String PUB = "A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg";
    static final String SRV = "KZDVVJ2UMNDUYAUF35O3";
    static final String TOK = "eyJieXRlcyI6MTIzNDU2LCJkZXYiOiJkZXZGUF9leGFtcGxlIiwiZXhwIjoxNzY2NTkyMDAwLCJnaWQiOjQyLCJpYXQiOjE3NjQwMDAwMDAsIml0ZW0iOjYwMDEsInByb2YiOiI3MjBwIiwicm9sZSI6ImRvd25sb2FkIiwic2hhIjoiYWJhYmFiYWJhYmFiYWJhYmFiYWJhYmFiYWJhYmFiYWJhYmFiYWJhYmFiYWJhYmFiYWJhYmFiYWJhYmFiYWJhYiIsInNydiI6IktaRFZWSjJVTU5EVVlBVUYzNU8zIiwidWlkIjo3LCJ2IjoxfQ.s_XETKnmPPhaDj4eSwoBIQfiAyKyHQKKrqFzg33u19HS2n9KzvxNVSDn-LfV5DIoT_K00-3qwyEdeRkE8vKfBA";

    @Test public void canonicalMatchesServer() {
        String c = Lic.canonical("post", "/api/offline/sync?x=1", 1764000000L, "nonce_nonce_nonce_1", "{\"a\":1}".getBytes(StandardCharsets.UTF_8));
        assertEquals("MOVINITE-DEVICE-1\nPOST\n/api/offline/sync?x=1\n1764000000\nnonce_nonce_nonce_1\n015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862", c);
    }

    @Test public void base64RoundTrip() {
        Random r = new Random(1);
        for (int n = 0; n < 70; n++) {
            byte[] b = new byte[n];
            r.nextBytes(b);
            assertArrayEquals(b, Lic.b64uDec(Lic.b64u(b)));
            assertArrayEquals(b, Lic.b64Dec(Lic.b64(b)));
        }
        assertEquals("aGk=", Lic.b64("hi".getBytes(StandardCharsets.US_ASCII)));
        assertEquals("-_8", Lic.b64u(new byte[]{(byte) 0xfb, (byte) 0xff}));
    }

    @Test public void tokenVerifies() {
        Lic.Token t = Lic.verify(TOK, Lic.b64uDec(PUB), SRV, "devFP_example", 42);
        assertEquals(42, t.gid);
        assertEquals(6001, t.item);
        assertEquals(1766592000L, t.exp);
        assertEquals("720p", t.prof);
        assertEquals("download", t.role);
    }

    private static void refused(String tok, String srv, String dev, long gid, String why) {
        try { Lic.verify(tok, Lic.b64uDec(PUB), srv, dev, gid); fail("accepted: " + why); }
        catch (SecurityException expected) { /* ok */ }
    }

    @Test public void tokenRefusals() {
        refused(TOK, "OTHERSERVER", "devFP_example", 42, "other server");
        refused(TOK, SRV, "otherDevice", 42, "other device");
        refused(TOK, SRV, "devFP_example", 43, "other grant");
        String p = TOK.substring(0, TOK.indexOf('.')), sig = TOK.substring(TOK.indexOf('.') + 1);
        String forged = Lic.b64u(new String(Lic.b64uDec(p), StandardCharsets.UTF_8).replace("1766592000", "1999999999").getBytes(StandardCharsets.UTF_8));
        refused(forged + "." + sig, SRV, "devFP_example", 42, "stretched expiry");
        refused("garbage", SRV, null, 0, "malformed");
        refused(null, SRV, null, 0, "missing");
    }

    @Test public void chunkMath() {
        long n = 3L * Lic.CHUNK + 5;
        assertEquals(4, Lic.chunks(n));
        assertEquals(5, Lic.chunkLen(n, 3));
        assertEquals(Lic.CHUNK, Lic.chunkLen(n, 0));
        assertEquals(0, Lic.chunkLen(n, 4));
        assertEquals(Lic.HEADER + 3L * (Lic.CHUNK + Lic.OVERHEAD) + 5 + Lic.OVERHEAD, Lic.storedSize(n));
        assertEquals(0, Lic.completeChunks(Lic.HEADER, n));
        assertEquals(2, Lic.completeChunks(Lic.chunkOffset(2) + 100, n));
        assertEquals(4, Lic.completeChunks(Lic.storedSize(n), n));
        assertEquals(0, Lic.chunks(0));
    }

    @Test public void clockGuard() {
        assertEquals(1000, Lic.trustedNow(1000, 900, 3600));
        assertEquals(5000, Lic.trustedNow(2000, 5000, 3600));          // a little behind: use the high-water mark
        assertEquals(-1, Lic.trustedNow(1000, 10000, 3600));           // turned back by hours: blocked
        assertNotNull(Lic.unusableReason(100, -1, 0, 30));
        assertNotNull(Lic.unusableReason(100, 100, 0, 30));            // expired
        assertNull(Lic.unusableReason(200, 100, 50, 30));
        assertNotNull(Lic.unusableReason(10_000_000, 31 * 86400L + 51, 50, 30));   // offline window over
    }

    private static Aead aead() throws Exception {
        AeadConfig.register();
        return KeysetHandle.generateNew(KeyTemplates.get("AES256_GCM")).getPrimitive(Aead.class);
    }

    @Test public void chunkStoreRoundTripResumeAndTamper() throws Exception {
        Aead a = aead();
        byte[] data = new byte[2 * Lic.CHUNK + 777];
        new Random(7).nextBytes(data);
        String want = Lic.hex(MessageDigest.getInstance("SHA-256").digest(data));
        File f = File.createTempFile("mvc", ".part");
        f.deleteOnExit();
        // first attempt stops after 1.5 chunks (connection lost)
        try (ChunkStore.Writer w = new ChunkStore.Writer(f, a, 9, "video", data.length, 0)) {
            w.write(data, 0, Lic.CHUNK + Lic.CHUNK / 2);
            assertFalse(w.complete());
        }
        long start = Lic.completeChunks(f.length(), data.length);
        assertEquals(1, start);
        try (ChunkStore.Writer w = new ChunkStore.Writer(f, a, 9, "video", data.length, start)) {
            int from = (int) w.position();
            assertEquals(Lic.CHUNK, from);
            w.write(data, from, data.length - from);
            assertTrue(w.complete());
            assertEquals(want, w.sha256());
        }
        assertEquals(Lic.storedSize(data.length), f.length());
        try (ChunkStore.Reader r = new ChunkStore.Reader(f, a, 9, "video")) {
            byte[] out = new byte[data.length];
            int p = 0;
            while (p < out.length) { int n = r.read(p, out, p, Math.min(300_000, out.length - p)); assertTrue(n > 0); p += n; }
            assertArrayEquals(data, out);
            byte[] mid = new byte[10];
            r.read(Lic.CHUNK + 5, mid, 0, 10);                      // random access (seeking)
            for (int i = 0; i < 10; i++) assertEquals(data[Lic.CHUNK + 5 + i], mid[i]);
        }
        try (ChunkStore.Reader r = new ChunkStore.Reader(f, a, 10, "video")) { r.chunk(0); fail("opened with another download id"); }
        catch (java.io.IOException expected) { /* chunks are bound to their download */ }
        try (RandomAccessFile raf = new RandomAccessFile(f, "rw")) { raf.seek(Lic.chunkOffset(1) + 40); raf.write(raf.read() ^ 1); }
        try (ChunkStore.Reader r = new ChunkStore.Reader(f, a, 9, "video")) { r.chunk(0); r.chunk(1); fail("tampered chunk accepted"); }
        catch (java.io.IOException expected) { /* GCM tag */ }
        try (ChunkStore.Reader r = new ChunkStore.Reader(f, aead(), 9, "video")) { r.chunk(0); fail("another key decrypted it"); }
        catch (java.io.IOException expected) { /* other phone's key */ }
    }
}
