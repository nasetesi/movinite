package org.movinite.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.KeyguardManager;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.hardware.biometrics.BiometricManager;
import android.hardware.biometrics.BiometricPrompt;
import android.os.Build;
import android.os.CancellationSignal;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.text.InputFilter;
import android.text.InputType;
import android.view.Gravity;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.nio.charset.StandardCharsets;
import java.security.KeyPairGenerator;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.security.SecureRandom;
import java.security.spec.MGF1ParameterSpec;

import javax.crypto.Cipher;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.OAEPParameterSpec;
import javax.crypto.spec.PBEKeySpec;
import javax.crypto.spec.PSource;

/**
 * Offline sign-in. With a secure lock screen, a Keystore RSA key whose private half needs the fingerprint, face or screen
 * lock (within 30 s) unwraps a random secret; the downloads open only after that works. An optional 6-digit Movinite PIN
 * (PBKDF2, 150k rounds) is asked for as well, or instead when the phone has no screen lock. 10 wrong PINs remove the downloads.
 */
final class Unlock {
    static final String ALIAS = "movinite_unlock_v1";
    private static final String P = "movinite_unlock";
    private Unlock() {}

    static SharedPreferences sp(Context c) { return c.getSharedPreferences(P, Context.MODE_PRIVATE); }

    static boolean deviceSecure(Context c) {
        KeyguardManager k = (KeyguardManager) c.getSystemService(Context.KEYGUARD_SERVICE);
        return k != null && k.isDeviceSecure();
    }

    static boolean biometricAvailable(Context c) {
        if (Build.VERSION.SDK_INT >= 30) {
            BiometricManager m = c.getSystemService(BiometricManager.class);
            return m != null && m.canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_STRONG) == BiometricManager.BIOMETRIC_SUCCESS;
        }
        if (Build.VERSION.SDK_INT >= 29) {
            BiometricManager m = c.getSystemService(BiometricManager.class);
            return m != null && m.canAuthenticate() == BiometricManager.BIOMETRIC_SUCCESS;
        }
        return false;
    }

    static boolean pinSet(Context c) { return sp(c).getString("pin_hash", null) != null; }

    static String lockKind(Context c) {
        if (deviceSecure(c)) return biometricAvailable(c) ? "biometric" : "device";
        return pinSet(c) ? "pin" : "none";
    }

    private static KeyStore ks() throws Exception { KeyStore k = KeyStore.getInstance("AndroidKeyStore"); k.load(null); return k; }

    /** at registration (no prompt needed: encrypting with the public key doesn't need the user) */
    static void setup(Context c) {
        reset(c, false);
        if (!deviceSecure(c)) return;
        try {
            KeyGenParameterSpec.Builder b = new KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_DECRYPT)
                .setKeySize(2048)
                .setDigests(KeyProperties.DIGEST_SHA256, KeyProperties.DIGEST_SHA1)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_RSA_OAEP)
                .setUserAuthenticationRequired(true);
            if (Build.VERSION.SDK_INT >= 30) b.setUserAuthenticationParameters(30, KeyProperties.AUTH_BIOMETRIC_STRONG | KeyProperties.AUTH_DEVICE_CREDENTIAL);
            else b.setUserAuthenticationValidityDurationSeconds(30);
            if (Build.VERSION.SDK_INT >= 24) b.setInvalidatedByBiometricEnrollment(false);
            KeyPairGenerator g = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_RSA, "AndroidKeyStore");
            g.initialize(b.build());
            PublicKey pub = g.generateKeyPair().getPublic();
            byte[] secret = new byte[32];
            new SecureRandom().nextBytes(secret);
            // the Keystore's public key is used through the default provider (no auth needed for public-key operations)
            PublicKey plain = java.security.KeyFactory.getInstance(pub.getAlgorithm()).generatePublic(new java.security.spec.X509EncodedKeySpec(pub.getEncoded()));
            Cipher ci = Cipher.getInstance("RSA/ECB/OAEPWithSHA-256AndMGF1Padding");
            ci.init(Cipher.ENCRYPT_MODE, plain, oaep());
            sp(c).edit().putString("blob", Lic.b64(ci.doFinal(secret))).putString("check", Lic.sha256Hex(secret)).apply();
        } catch (Exception e) {
            sp(c).edit().putString("setup_error", String.valueOf(e.getMessage())).apply();
        }
    }

    private static OAEPParameterSpec oaep() { return new OAEPParameterSpec("SHA-256", "MGF1", MGF1ParameterSpec.SHA1, PSource.PSpecified.DEFAULT); }

    static void reset(Context c) { reset(c, true); }

    private static void reset(Context c, boolean pinToo) {
        try { KeyStore k = ks(); if (k.containsAlias(ALIAS)) k.deleteEntry(ALIAS); } catch (Exception ignored) { }
        SharedPreferences.Editor e = sp(c).edit().remove("blob").remove("check").remove("setup_error");
        if (pinToo) e.remove("pin_hash").remove("pin_salt").remove("pin_fails");
        e.apply();
    }

    /** the auth-bound key can unwrap the secret right now (after a successful prompt) */
    static boolean tryUnwrap(Context c) {
        try {
            String blob = sp(c).getString("blob", null);
            if (blob == null) return false;
            PrivateKey k = (PrivateKey) ks().getKey(ALIAS, null);
            Cipher ci = Cipher.getInstance("RSA/ECB/OAEPWithSHA-256AndMGF1Padding");
            ci.init(Cipher.DECRYPT_MODE, k, oaep());
            byte[] s = ci.doFinal(Lic.b64Dec(blob));
            return Lic.sha256Hex(s).equals(sp(c).getString("check", ""));
        } catch (Exception e) { return false; }
    }

    /** at sync (online): (re)make the unlock key when the lock screen was added or changed since setup */
    static void rearmIfNeeded(Context c) {
        if (!deviceSecure(c)) return;
        if (sp(c).getBoolean("rearm", false) || sp(c).getString("blob", null) == null) { setup(c); sp(c).edit().remove("rearm").apply(); }
    }

    static boolean hasDeviceUnlock(Context c) { return deviceSecure(c) && sp(c).getString("blob", null) != null; }

    interface Done { void done(boolean ok, String why); }

    static final int REQ_CONFIRM = 4711;
    private static Done pendingConfirm;

    /** fingerprint / face / screen lock */
    static void prompt(Activity a, Done cb) {
        if (!hasDeviceUnlock(a)) { cb.done(false, "no_device_lock"); return; }
        if (tryUnwrap(a)) { cb.done(true, null); return; }         // unlocked within the last 30 s
        if (Build.VERSION.SDK_INT >= 28) {
            BiometricPrompt.Builder b = new BiometricPrompt.Builder(a).setTitle("Unlock your downloads")
                .setSubtitle("Movinite is offline. Confirm it's you to watch what you downloaded.");
            if (Build.VERSION.SDK_INT >= 30) b.setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG | BiometricManager.Authenticators.DEVICE_CREDENTIAL);
            else b.setDeviceCredentialAllowed(true);
            b.build().authenticate(new CancellationSignal(), a.getMainExecutor(), new BiometricPrompt.AuthenticationCallback() {
                @Override public void onAuthenticationSucceeded(BiometricPrompt.AuthenticationResult r) {
                    boolean ok = tryUnwrap(a);
                    if (!ok) sp(a).edit().putBoolean("rearm", true).apply();   // key invalidated (lock screen changed): re-made at the next sync
                    cb.done(ok, ok ? null : "rearm");
                }
                @Override public void onAuthenticationError(int code, CharSequence msg) { cb.done(false, String.valueOf(msg)); }
            });
        } else {
            KeyguardManager k = (KeyguardManager) a.getSystemService(Context.KEYGUARD_SERVICE);
            Intent i = k.createConfirmDeviceCredentialIntent("Unlock your downloads", "Movinite is offline. Confirm it's you.");
            if (i == null) { cb.done(false, "no_device_lock"); return; }
            pendingConfirm = cb;
            a.startActivityForResult(i, REQ_CONFIRM);
        }
    }

    /** call from onActivityResult (Android 7-8) */
    static boolean onResult(Activity a, int req, int res) {
        if (req != REQ_CONFIRM || pendingConfirm == null) return false;
        Done cb = pendingConfirm; pendingConfirm = null;
        cb.done(res == Activity.RESULT_OK && tryUnwrap(a), res == Activity.RESULT_OK ? "key" : "cancelled");
        return true;
    }

    // ------------------------------------------------------------------ PIN
    private static byte[] pbkdf2(String pin, byte[] salt) throws Exception {
        return SecretKeyFactory.getInstance("PBKDF2WithHmacSHA1").generateSecret(new PBEKeySpec(pin.toCharArray(), salt, 150000, 256)).getEncoded();
    }

    static void setPin(Context c, String pin) throws Exception {
        byte[] salt = new byte[16];
        new SecureRandom().nextBytes(salt);
        sp(c).edit().putString("pin_salt", Lic.b64(salt)).putString("pin_hash", Lic.b64(pbkdf2(pin, salt))).putInt("pin_fails", 0).apply();
    }

    static void clearPin(Context c) { sp(c).edit().remove("pin_hash").remove("pin_salt").remove("pin_fails").apply(); }

    /** true = right; the 10th wrong PIN wipes the downloads */
    static boolean checkPin(Context c, String pin) {
        try {
            byte[] want = Lic.b64Dec(sp(c).getString("pin_hash", "")), got = pbkdf2(pin, Lic.b64Dec(sp(c).getString("pin_salt", "")));
            if (MessageDigest.isEqual(want, got)) { sp(c).edit().putInt("pin_fails", 0).apply(); return true; }
        } catch (Exception ignored) { }
        int f = sp(c).getInt("pin_fails", 0) + 1;
        sp(c).edit().putInt("pin_fails", f).apply();
        if (f >= 10) Offline.get(c).wipe("too many wrong PINs");
        return false;
    }

    static int pinFails(Context c) { return sp(c).getInt("pin_fails", 0); }

    private static EditText pinField(Context c, String hint) {
        EditText e = new EditText(c);
        e.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_VARIATION_PASSWORD);
        e.setFilters(new InputFilter[]{new InputFilter.LengthFilter(6)});
        e.setHint(hint);
        e.setGravity(Gravity.CENTER);
        e.setTextSize(22);
        e.setLetterSpacing(0.4f);
        return e;
    }

    /** two fields, 6 digits */
    static void setupPinDialog(Activity a, Done cb) {
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (20 * a.getResources().getDisplayMetrics().density);
        box.setPadding(pad, pad / 2, pad, 0);
        TextView t = new TextView(a);
        t.setText(deviceSecure(a) ? "You'll enter this PIN as well as your fingerprint, face or screen lock when you open downloads offline."
                                  : "Your phone has no screen lock, so this PIN protects your downloads when you open them offline.");
        EditText p1 = pinField(a, "6-digit PIN"), p2 = pinField(a, "Repeat the PIN");
        TextView err = new TextView(a);
        err.setTextColor(0xffe5534b);
        box.addView(t); box.addView(p1); box.addView(p2); box.addView(err);
        AlertDialog d = new AlertDialog.Builder(a).setTitle("Set a Movinite PIN").setView(box)
            .setPositiveButton("Save", null).setNegativeButton("Cancel", (x, w) -> cb.done(false, "cancelled"))
            .setOnCancelListener(x -> cb.done(false, "cancelled")).create();
        d.setOnShowListener(x -> d.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            String a1 = p1.getText().toString(), a2 = p2.getText().toString();
            if (!a1.matches("\\d{6}")) { err.setText("Use exactly 6 digits."); return; }
            if (a1.matches("(\\d)\\1{5}") || "123456".equals(a1) || "654321".equals(a1)) { err.setText("Pick a PIN that's harder to guess."); return; }
            if (!a1.equals(a2)) { err.setText("The two PINs don't match."); return; }
            try { setPin(a, a1); d.dismiss(); cb.done(true, null); } catch (Exception e) { err.setText("Couldn't save the PIN."); }
        }));
        d.show();
    }

    static void askPinDialog(Activity a, Done cb) {
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (20 * a.getResources().getDisplayMetrics().density);
        box.setPadding(pad, pad / 2, pad, 0);
        EditText p = pinField(a, "Movinite PIN");
        TextView err = new TextView(a);
        err.setTextColor(0xffe5534b);
        int f = pinFails(a);
        if (f > 0) err.setText((10 - f) + " tries left before your downloads are removed.");
        box.addView(p); box.addView(err);
        AlertDialog d = new AlertDialog.Builder(a).setTitle("Enter your Movinite PIN").setView(box)
            .setPositiveButton("Unlock", null).setNegativeButton("Cancel", (x, w) -> cb.done(false, "cancelled"))
            .setOnCancelListener(x -> cb.done(false, "cancelled")).create();
        d.setOnShowListener(x -> d.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            if (checkPin(a, p.getText().toString())) { d.dismiss(); cb.done(true, null); return; }
            if (!pinSet(a)) { d.dismiss(); cb.done(false, "wiped"); return; }
            p.setText("");
            err.setText("Wrong PIN. " + (10 - pinFails(a)) + " tries left before your downloads are removed.");
        }));
        d.show();
    }

    /** the whole offline sign-in: device unlock (if there is one), then the PIN (if set) */
    static void offlineSignIn(Activity a, Done cb) {
        Runnable pin = () -> {
            if (!pinSet(a)) { cb.done(true, null); return; }
            askPinDialog(a, cb);
        };
        if (hasDeviceUnlock(a)) prompt(a, (ok, why) -> { if (ok) pin.run(); else cb.done(false, why); });
        else if (pinSet(a)) pin.run();
        else if (deviceSecure(a)) cb.done(false, "setup_needed");   // a screen lock was added after setup: sync once to re-arm
        else cb.done(false, "no_lock");
    }

    static String utf8(byte[] b) { return new String(b, StandardCharsets.UTF_8); }
}
