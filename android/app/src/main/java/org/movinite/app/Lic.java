package org.movinite.app;

import com.google.crypto.tink.subtle.Ed25519Verify;

import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/**
 * 2.0 pure helpers (no Android types, so they are unit-tested on the JVM):
 * - the device request signature string the server checks (offline.canonical),
 * - the licence token: base64url(JSON payload) "." base64url(Ed25519 signature by the server key),
 * - chunk arithmetic for the encrypted store,
 * - the clock guard (licences can't be stretched by turning the phone's clock back).
 */
public final class Lic {
    public static final String SIG_VERSION = "MOVINITE-DEVICE-1";
    private Lic() {}

    // own base64 (java.util.Base64 needs Android 8; the app still runs on Android 7)
    private static final char[] STD = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/".toCharArray();
    private static final char[] URL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_".toCharArray();

    private static String enc(byte[] b, char[] al, boolean pad) {
        StringBuilder sb = new StringBuilder((b.length + 2) / 3 * 4);
        for (int i = 0; i < b.length; i += 3) {
            int n = (b[i] & 0xff) << 16 | (i + 1 < b.length ? (b[i + 1] & 0xff) << 8 : 0) | (i + 2 < b.length ? b[i + 2] & 0xff : 0);
            sb.append(al[n >> 18 & 63]).append(al[n >> 12 & 63]);
            if (i + 1 < b.length) sb.append(al[n >> 6 & 63]); else if (pad) sb.append('=');
            if (i + 2 < b.length) sb.append(al[n & 63]); else if (pad) sb.append('=');
        }
        return sb.toString();
    }

    private static byte[] dec(String s) {
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream(s.length() * 3 / 4);
        int buf = 0, bits = 0;
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            int v;
            if (c >= 'A' && c <= 'Z') v = c - 'A';
            else if (c >= 'a' && c <= 'z') v = c - 'a' + 26;
            else if (c >= '0' && c <= '9') v = c - '0' + 52;
            else if (c == '+' || c == '-') v = 62;
            else if (c == '/' || c == '_') v = 63;
            else if (c == '=' || c == '\n' || c == '\r' || c == ' ') continue;
            else throw new IllegalArgumentException("bad base64");
            buf = buf << 6 | v; bits += 6;
            if (bits >= 8) { bits -= 8; out.write(buf >> bits & 0xff); }
        }
        return out.toByteArray();
    }

    public static String b64u(byte[] b) { return enc(b, URL, false); }
    public static String b64(byte[] b) { return enc(b, STD, true); }
    public static byte[] b64uDec(String s) { return dec(s); }
    public static byte[] b64Dec(String s) { return dec(s); }

    public static String sha256Hex(byte[] b) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            return hex(md.digest(b == null ? new byte[0] : b));
        } catch (Exception e) { throw new IllegalStateException(e); }
    }

    public static String hex(byte[] d) {
        StringBuilder sb = new StringBuilder(d.length * 2);
        for (byte x : d) sb.append(String.format("%02x", x & 0xff));
        return sb.toString();
    }

    /** exactly the server's canonical(): version, METHOD, path[?query], time, nonce, sha256(body) */
    public static String canonical(String method, String pathAndQuery, long ts, String nonce, byte[] body) {
        return SIG_VERSION + "\n" + method.toUpperCase(java.util.Locale.ROOT) + "\n" + pathAndQuery + "\n" + ts + "\n" + nonce + "\n" + sha256Hex(body);
    }

    /** base64url(sha256(DER SubjectPublicKeyInfo)), the server's device_fp */
    public static String deviceFp(byte[] spkiDer) {
        try { return b64u(MessageDigest.getInstance("SHA-256").digest(spkiDer)); }
        catch (Exception e) { throw new IllegalStateException(e); }
    }

    /** A verified licence. */
    public static final class Token {
        public final long gid, item, uid, exp, iat, bytes;
        public final String dev, srv, prof, sha, role;
        Token(JSONObject p) {
            gid = p.optLong("gid"); item = p.optLong("item"); uid = p.optLong("uid"); exp = p.optLong("exp"); iat = p.optLong("iat");
            bytes = p.optLong("bytes"); dev = p.optString("dev"); srv = p.optString("srv"); prof = p.optString("prof");
            sha = p.isNull("sha") ? null : p.optString("sha"); role = p.optString("role");
        }
    }

    /**
     * Checks the server's Ed25519 signature and that the licence is for this server, this device and this download.
     * Throws SecurityException with a short reason otherwise. Expiry is checked separately (see usable()).
     */
    public static Token verify(String token, byte[] serverPub32, String serverId, String deviceFp, long gid) {
        if (token == null) throw new SecurityException("no licence");
        int dot = token.indexOf('.');
        if (dot <= 0 || dot == token.length() - 1) throw new SecurityException("malformed licence");
        String p = token.substring(0, dot);
        try {
            new Ed25519Verify(serverPub32).verify(b64uDec(token.substring(dot + 1)), p.getBytes(StandardCharsets.US_ASCII));
        } catch (Exception e) { throw new SecurityException("licence signature"); }
        JSONObject o;
        try { o = new JSONObject(new String(b64uDec(p), StandardCharsets.UTF_8)); }
        catch (Exception e) { throw new SecurityException("licence payload"); }
        if (o.optInt("v") != 1) throw new SecurityException("licence version");
        Token t = new Token(o);
        if (serverId != null && !serverId.equals(t.srv)) throw new SecurityException("licence is for another server");
        if (deviceFp != null && !deviceFp.equals(t.dev)) throw new SecurityException("licence is for another device");
        if (gid > 0 && gid != t.gid) throw new SecurityException("licence is for another download");
        return t;
    }

    // ------------------------------------------------------------------ chunks
    public static final int CHUNK = 1 << 20;          // 1 MiB of plaintext per chunk
    public static final int OVERHEAD = 5 + 12 + 16;   // Tink AES-GCM: key-id prefix + IV + tag
    public static final int HEADER = 16;              // "MVC1" + chunk size + plaintext length

    public static long chunks(long plainLen) { return plainLen <= 0 ? 0 : (plainLen + CHUNK - 1) / CHUNK; }
    public static int chunkLen(long plainLen, long i) { long rest = plainLen - i * (long) CHUNK; return (int) Math.max(0, Math.min(CHUNK, rest)); }
    public static long chunkOffset(long i) { return HEADER + i * (long) (CHUNK + OVERHEAD); }
    public static long storedSize(long plainLen) { long n = chunks(plainLen); return n == 0 ? HEADER : chunkOffset(n - 1) + chunkLen(plainLen, n - 1) + OVERHEAD; }
    /** how many whole chunks a partial file already holds (to resume a download at a chunk boundary) */
    public static long completeChunks(long fileLen, long plainLen) {
        if (fileLen <= HEADER) return 0;
        long n = (fileLen - HEADER) / (CHUNK + OVERHEAD);
        long total = chunks(plainLen);
        if (n >= total - 1 && total > 0 && fileLen >= storedSize(plainLen)) return total;
        return Math.min(n, Math.max(0, total - 1));
    }
    public static byte[] aad(long gid, String part, long i, long plainLen) {
        return ("movinite/" + gid + "/" + part + "/" + i + "/" + plainLen).getBytes(StandardCharsets.US_ASCII);
    }

    // ------------------------------------------------------------------ clock guard
    /**
     * The "trusted now": the phone's clock, but never earlier than the latest time we've seen (server time at the last
     * sync, or the clock at an earlier check) minus a small allowance. Returns -1 when the clock was turned back by more
     * than the allowance: offline playback then waits for a sync.
     */
    public static long trustedNow(long wallNow, long highWater, long allowance) {
        if (highWater > 0 && wallNow < highWater - allowance) return -1;
        return Math.max(wallNow, highWater);
    }

    /** usable = verified licence that hasn't expired at the trusted time, and the offline window isn't over */
    public static String unusableReason(long exp, long trustedNow, long lastSync, long wipeDays) {
        if (trustedNow < 0) return "The phone's clock was turned back. Connect to the internet once to keep watching.";
        if (exp > 0 && trustedNow >= exp) return "This download's licence has expired. Connect to the internet to renew it.";
        if (lastSync > 0 && wipeDays > 0 && trustedNow - lastSync > wipeDays * 86400L) return "You haven't been online for " + wipeDays + " days.";
        return null;
    }
}
